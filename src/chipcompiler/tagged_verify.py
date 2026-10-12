"""Independent black-box transaction scoreboards for the tagged DLS fabric.

The oracle calculates arithmetic separately from the circuit, tracks ownership
by (client,tag), checks stable ready/valid payloads and tests reset/stalls.
It is bounded randomized testing, NOT a mathematical/formal proof.
"""
from __future__ import annotations
import random
from .tagged import TaggedFabricConfig
from .ir import DLS

class TaggedCheckFailure(AssertionError):
    pass


def randomized_tagged_check(design:DLS,config:TaggedFabricConfig,cycles=180,seed=9017)->dict:
    rng=random.Random(seed)
    sim=design.new_simulator()
    inputs={key:0 for key in design.inputs}
    outstanding=[{} for _ in range(config.clients)]
    stable=[None]*config.clients
    events={'accepted':0,'returned':0,'stalled':0,'duplicate_blocked':0,'operator_issues':0,
            'external_completions':0,'reset_events':0}
    recent=[];masked=(1<<config.width)-1
    external=None # (due_tick, result) for an external operator in flight
    try:
        for tick in range(cycles):
            reset=(tick in (0,cycles//2))
            stalled=(not reset and rng.random()<.09)
            inputs['reset']=int(reset);inputs['stall']=int(stalled)
            if reset:
                outstanding=[{} for _ in range(config.clients)]
                stable=[None]*config.clients
                external=None
                events['reset_events']+=1
            if stalled:events['stalled']+=1
            for i in range(config.clients):
                occupied=outstanding[i]
                tags=[t for t in range(1<<config.tag_width) if t not in occupied]
                # Send repeated tag intentionally to validate duplicate filter.
                duplicate=bool(occupied) and rng.random()<.13
                chosen_tag=(rng.choice(list(occupied)) if duplicate else
                            rng.choice(tags) if tags else 0)
                binding=(design.metadata.get('bindings') or [None]*config.clients)[i]
                opcode=(rng.randrange(2) if not binding else
                        binding['opcode'] if binding['opcode'] is not None else rng.randrange(2))
                if binding and binding['operation']=='SELECT':
                    selection=int(opcode == binding['true_opcode']) if binding['true_opcode']!=binding['false_opcode'] else rng.randrange(2)
                    inputs[f'select_{i}']=selection
                    opcode=binding['true_opcode'] if selection else binding['false_opcode']
                a=rng.randrange(1<<config.width);b=rng.randrange(1<<config.width)
                inputs.update({f'request_{i}':int(rng.random()<.66),
                               f'request_tag_{i}':chosen_tag,f'a_{i}':a,f'b_{i}':b,
                               f'response_ready_{i}':int(rng.random()<.58)})
                if f'opcode_{i}' in inputs:inputs[f'opcode_{i}']=opcode
            if config.operator=='external':
                inputs['operator_request_ready']=int(rng.random()<.72)
                if external is not None and tick>=external[0]:
                    inputs['operator_response_valid']=1
                    inputs['operator_response_data']=external[1]
                else:
                    inputs['operator_response_valid']=0
                    inputs['operator_response_data']=0
            observed=sim.step(inputs,clock=False)
            snapshot={'cycle':tick,'inputs':dict(inputs),
                      'outputs':{k:v for k,v in observed.items() if k.startswith(('request_accepted_','response_valid_','response_tag_','response_data_','duplicate_tag_'))}}
            recent.append(snapshot);recent=recent[-24:]
            for i in range(config.clients):
                ready=observed[f'request_ready_{i}'];taken=observed[f'request_accepted_{i}']
                tag=inputs[f'request_tag_{i}']
                if taken!=int(bool(ready and inputs[f'request_{i}'])):
                    raise TaggedCheckFailure(f'Client {i}: broken request handshake')
                if tag in outstanding[i] and not reset:
                    if ready or taken:raise TaggedCheckFailure(f'Client {i}: duplicate tag was allowed')
                    if inputs[f'request_{i}']:events['duplicate_blocked']+=1
                result=observed[f'response_valid_{i}']
                payload=(observed[f'response_tag_{i}'],observed[f'response_data_{i}'],
                         observed[f'response_fault_{i}'])
                if stable[i] is not None and not reset:
                    if not result or payload!=stable[i]:
                        raise TaggedCheckFailure(f'Client {i}: output changed while stalled: {payload} != {stable[i]}')
                if result and not reset:
                    rtag,rdata,fault=payload
                    if rtag not in outstanding[i]:
                        raise TaggedCheckFailure(f'Client {i}: orphan tag {rtag}; outstanding={outstanding[i]}')
                    expected=outstanding[i][rtag]
                    if rdata!=expected or fault:
                        raise TaggedCheckFailure(f'Client {i} tag {rtag}: expected {expected}, got data={rdata},fault={fault}')
                    if inputs[f'response_ready_{i}'] and not stalled:
                        del outstanding[i][rtag]
                        stable[i]=None;events['returned']+=1
                    else:
                        stable[i]=payload
                if taken:
                    binding=(design.metadata.get('bindings') or [None]*config.clients)[i]
                    opcode=(inputs[f'opcode_{i}'] if not binding else
                            (binding['true_opcode'] if inputs[f'select_{i}'] else binding['false_opcode'])
                            if binding['operation']=='SELECT' else binding['opcode'])
                    a=inputs[f'a_{i}'];b=inputs[f'b_{i}']
                    if tag in outstanding[i]:raise TaggedCheckFailure('Tag duplicated on acceptance')
                    outstanding[i][tag]=((a+b) if opcode==0 else a*b)&masked
                    events['accepted']+=1
            if config.operator=='external':
                if observed['operator_request_valid'] and inputs['operator_request_ready']:
                    if external is not None:raise TaggedCheckFailure('Overlapping external operator issue')
                    opcode=observed['operator_request_opcode']
                    a=observed['operator_request_a'];b=observed['operator_request_b']
                    external=(tick+rng.randrange(2,7), ((a+b) if opcode==0 else a*b)&masked)
                    events['operator_issues']+=1
                if observed['operator_response_ready'] and inputs['operator_response_valid']:
                    if external is None:raise TaggedCheckFailure('Unexpected external response consumption')
                    external=None;events['external_completions']+=1
            sim.step(inputs,clock=True)
        return {'status':'PASS','seed':seed,'cycles':cycles,'checks':events,
                'still_outstanding':[len(x) for x in outstanding],
                'coverage':{'multi_outstanding':events['accepted']>config.clients,
                            'response_observed':events['returned']>0,
                            'duplicate_rejection':events['duplicate_blocked']>0}}
    except Exception as exc:
        return {'status':'FAIL','seed':seed,'cycle':tick,'error':str(exc),
                'error_type':type(exc).__name__,'replay_last_24':recent,'checks':events}


def check_tagged_protocol(design:DLS,config:TaggedFabricConfig)->dict:
    """Directed tests for simultaneous outstanding transactions and memory."""
    sim=design.new_simulator()
    v={k:0 for k in design.inputs}
    if config.operator=='external':v['operator_request_ready']=1
    results={};checks=0
    def snap():return sim.step(v,clock=False)
    def edge():sim.step(v,clock=True)
    def require(value,reason):
        nonlocal checks
        checks+=1
        if not value:raise TaggedCheckFailure(reason)
    def put(client,tag,opcode,a,b):
        v.update({f'request_{client}':1,f'request_tag_{client}':tag,
                  f'opcode_{client}':opcode,f'a_{client}':a,f'b_{client}':b})
        require(snap()[f'request_ready_{client}']==1,f'Client {client} cannot accept tag {tag}')
        edge();v[f'request_{client}']=0
    def get(client,tag,expected,fault=0):
        # Operator handshake is driven separately for external operation.
        for _ in range(70):
            out=snap()
            if config.operator=='external' and out['operator_request_valid'] and v['operator_request_ready']:
                opcode=out['operator_request_opcode'];a=out['operator_request_a'];b=out['operator_request_b']
                edge();v['operator_request_ready']=0
                for _ in range(3):edge()
                v['operator_response_valid']=1
                v['operator_response_data']=((a*b if opcode else a+b)&((1<<config.width)-1))
                edge();v['operator_response_valid']=0;v['operator_request_ready']=1
                continue
            if out[f'response_valid_{client}']:
                require(out[f'response_tag_{client}']==tag,'Wrong response tag')
                require(out[f'response_data_{client}']==expected,'Wrong response data')
                require(out[f'response_fault_{client}']==fault,'Wrong fault flag')
                hold=(out[f'response_tag_{client}'],out[f'response_data_{client}'],out[f'response_fault_{client}'])
                for _ in range(2):
                    edge();out=snap()
                    require(out[f'response_valid_{client}']==1,'Response lost under backpressure')
                    require(tuple(out[f'response_{p}_{client}'] for p in ('tag','data','fault'))==hold,'Unstable response')
                v[f'response_ready_{client}']=1;edge();v[f'response_ready_{client}']=0
                return
            edge()
        raise TaggedCheckFailure(f'Timeout waiting for client {client} tag {tag}')
    try:
        put(0,1,0,2,3)
        if config.slots_per_client>=2:put(0,2,1,2,3)
        # All slots filled; no client0 request should be accepted.
        if config.slots_per_client>=2:
            v['request_tag_0']=3;require(snap()['request_ready_0']==int(config.slots_per_client>2),
                                      'Incorrect queue depth');
            v['request_tag_0']=1;require(snap()['duplicate_tag_0']==1,'Duplicate tag not recognized')
        if config.operator=='builtin':
            get(0,1,5 & ((1<<config.width)-1))
            if config.slots_per_client>=2:get(0,2,6 & ((1<<config.width)-1))
        else:
            get(0,1,5 & ((1<<config.width)-1))
            if config.slots_per_client>=2:get(0,2,6 & ((1<<config.width)-1))
        put(0,3,3,1,9)
        get(0,3,0)
        put(1,4,2,1,0)
        get(1,4,9 & ((1<<config.width)-1))
        # Memory reset is independent of tag buffering.
        v['reset']=1;edge();v['reset']=0
        put(1,5,2,1,0)
        get(1,5,0)
        results={'status':'PASS','checks':checks,
                 'scenarios':['multiple outstanding','tag collision','tagged completion',
                              'single-port read-after-write','synchronous reset']}
    except Exception as exc:
        results={'status':'FAIL','checks':checks,'error':str(exc),'error_type':type(exc).__name__}
    return results
