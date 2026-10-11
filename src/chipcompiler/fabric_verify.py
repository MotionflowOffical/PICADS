"""Independent transactional protocol checks for the generated fabric.

These checks are deterministic functional scenarios, NOT formal verification,
external RTL equivalence, or proof of physical timing. Failure includes the
scenario name, clock edge and bounded replay input trace.
"""
from __future__ import annotations
from .concurrent import FabricConfig
from .ir import DLS

class FabricCheckFailure(AssertionError):
    pass

def check_fabric_protocol(design:DLS,config:FabricConfig)->dict:
    scenarios=[];checks=0
    current='startup';inputs_trace=[];clock=0
    def assert_that(ok,message,**details):
        nonlocal checks
        checks+=1
        if not ok:
            raise FabricCheckFailure(f'{message}; details={details}')
    def setup():
        sim=design.new_simulator()
        values={name:0 for name in design.inputs}
        for i in range(config.clients):values[f'response_ready_{i}']=0
        if config.operator=='external':values['operator_request_ready']=1
        return sim,values
    def sample(sim,v):return sim.step(v,clock=False)
    def edge(sim,v):
        nonlocal clock
        inputs_trace.append({'edge':clock,'inputs':dict(v)})
        inputs_trace[:]=inputs_trace[-24:]
        clock+=1
        sim.step(v,clock=True)
        return sample(sim,v)
    def run_to_response(sim,v,i,limit=32):
        for _ in range(limit):
            observed=sample(sim,v)
            if observed[f'response_valid_{i}']:return observed
            observed=edge(sim,v)
            if observed[f'response_valid_{i}']:return observed
        raise FabricCheckFailure(f'Client {i} response timeout after {limit} clocks')
    def send(sim,v,i,opcode,a,b):
        v.update({f'request_{i}':1,f'opcode_{i}':opcode,f'a_{i}':a,f'b_{i}':b})
        assert_that(sample(sim,v)[f'request_ready_{i}']==1,'Expected available client request slot',client=i)
        edge(sim,v);v[f'request_{i}']=0
    def complete(sim,v,i,expected,fault=0):
        result=run_to_response(sim,v,i)
        assert_that(result[f'response_fault_{i}']==fault,'Incorrect memory fault',client=i,result=result)
        assert_that(result[f'response_data_{i}']==expected,'Incorrect returned data',client=i,result=result)
        stable=tuple(result[f'response_{k}_{i}'] for k in ('valid','data','fault'))
        for _ in range(3):
            later=edge(sim,v)
            assert_that(tuple(later[f'response_{k}_{i}'] for k in ('valid','data','fault'))==stable,
                        'Response must be held under client backpressure',client=i)
        v[f'response_ready_{i}']=1
        edge(sim,v);v[f'response_ready_{i}']=0
        assert_that(sample(sim,v)[f'response_valid_{i}']==0,'Response handshake did not clear valid',client=i)

    try:
        current='parallel operator and memory issuance';sim,v=setup()
        send(sim,v,0,0,3,2)
        # A second client can be accepted while the first is outstanding.
        send(sim,v,1,3,1,9)
        assert_that(sample(sim,v)['pending_1'] or sample(sim,v)['response_valid_1'],
                    'Second request was not buffered or completed')
        if config.operator=='builtin':
            complete(sim,v,0,5 & ((1<<config.width)-1))
        else:
            # External completion happens ONLY when the environment returns it.
            for _ in range(6):edge(sim,v)
            state=sample(sim,v)
            assert_that(state['operator_busy']==1,'External operator request not active')
            assert_that(state['response_valid_0']==0,'External operator completed without response')
            v['operator_response_valid']=1;v['operator_response_data']=5 & ((1<<config.width)-1)
            edge(sim,v);v['operator_response_valid']=0
            complete(sim,v,0,5 & ((1<<config.width)-1))
        complete(sim,v,1,0)
        scenarios.append(current)

        current='memory read-after-write, bank contents and error reporting';sim,v=setup()
        send(sim,v,0,3,1,7)
        complete(sim,v,0,0)
        send(sim,v,1,2,1,0)
        complete(sim,v,1,7)
        if config.depth < (1<<config.width):
            send(sim,v,0,2,config.depth,0)
            complete(sim,v,0,0,1)
        scenarios.append(current)

        current='stall freezes all registers and request accepts';sim,v=setup()
        send(sim,v,0,0,2,3)
        v['stall']=1
        snapshot=sim.register_snapshot()
        for _ in range(3):
            observed=edge(sim,v)
            assert_that(sim.register_snapshot()==snapshot,'Stall changed registered state')
            assert_that(observed['operator_request_valid']==0,'Stall did not disable external transfer')
        v['stall']=0
        scenarios.append(current)

        current='synchronous reset clears pending requests, results and memory';sim,v=setup()
        send(sim,v,0,3,0,5)
        v['reset']=1;edge(sim,v);v['reset']=0
        state=sample(sim,v)
        for i in range(config.clients):
            assert_that(state[f'request_ready_{i}']==1,'Reset left client occupied',client=i)
            assert_that(state[f'response_valid_{i}']==0,'Reset left response valid',client=i)
        send(sim,v,1,2,0,0)
        complete(sim,v,1,0)
        scenarios.append(current)

        if config.operator=='external':
            current='external request remains stable under ready backpressure';sim,v=setup()
            v['operator_request_ready']=0
            send(sim,v,0,1,2,3)
            for _ in range(4):edge(sim,v)
            original=sample(sim,v)
            assert_that(original['operator_request_valid']==1,'Operator offer not asserted')
            values=(original['operator_request_opcode'],original['operator_request_a'],original['operator_request_b'])
            send(sim,v,1,0,1,1)
            for _ in range(5):
                actual=edge(sim,v)
                assert_that(actual['operator_request_valid']==1,'Backpressured request VALID disappeared')
                assert_that((actual['operator_request_opcode'],actual['operator_request_a'],actual['operator_request_b'])==values,
                            'Backpressured operator payload changed')
            v['operator_request_ready']=1
            edge(sim,v)
            assert_that(sample(sim,v)['operator_busy']==1,'External acceptance not recorded')
            v['operator_request_ready']=0
            for _ in range(5):
                actual=edge(sim,v)
                assert_that(actual['response_valid_0']==0,'Spurious operator completion')
            v['operator_response_data']=6;v['operator_response_valid']=1
            edge(sim,v);v['operator_response_valid']=0
            complete(sim,v,0,6)
            scenarios.append(current)
        return {'status':'PASS','scenarios':scenarios,'checks':checks,'exhaustive':False,
                'method':'Deterministic executable DLS protocol checks, independent expected outputs',
                'note':'An actual external RTL simulation is still required; no timing/PDK signoff performed.'}
    except (FabricCheckFailure,ValueError,TypeError) as exc:
        return {'status':'FAIL','scenario':current,'checks_before_failure':checks,
                'message':str(exc),'last_edge':clock,'replay_last_24':inputs_trace,
                'exhaustive':False}


def randomized_fabric_check(design:DLS,config:FabricConfig,cycles:int=160,seed:int=8291)->dict:
    """Independent register-bank/transaction scoreboard across concurrent clients.

    Checks accepted requests, one-hot service grants, held responses,
    memory ordering at the *actual* granted edge, and external delayed
    completions. It does not derive expected results from DLS output data.
    """
    import random
    rng=random.Random(seed);sim=design.new_simulator()
    n,w=config.clients,config.width
    memory=[0]*config.depth
    slots=[None]*n
    expected=[None]*n
    ext_value=None;ext_due=0
    accepted=completed=memory_grants=alu_grants=0
    mask=(1<<w)-1
    recent=[]
    try:
        for clock in range(cycles):
            drive={port:0 for port in design.inputs}
            drive['reset']=int(clock==0 or clock==cycles//2)
            drive['stall']=int(clock%29 in (11,12))
            if config.operator=='external':
                drive['operator_request_ready']=int(clock%17 not in (6,7,8))
                if ext_value is not None and clock>=ext_due:
                    drive['operator_response_valid']=1
                    drive['operator_response_data']=ext_value
            for i in range(n):drive[f'response_ready_{i}']=int(clock%13 not in (4,5,6))
            prior=sim.step(drive,clock=False)
            for i in range(n):
                if prior[f'request_ready_{i}'] and not drive['reset'] and rng.randrange(4)!=0:
                    opcode=rng.randrange(4)
                    drive.update({f'request_{i}':1,f'opcode_{i}':opcode,
                                  f'a_{i}':rng.randrange(1<<w),f'b_{i}':rng.randrange(1<<w)})
            prior=sim.step(drive,clock=False)
            recent.append({'cycle':clock,'inputs':drive,'signals':{k:v for k,v in prior.items()
                    if k.startswith(('memory_grant','operator_grant','response_valid','response_data','response_fault'))}})
            recent=recent[-10:]
            mg=[i for i in range(n) if prior[f'memory_grant_{i}']]
            ag=[i for i in range(n) if prior[f'operator_grant_{i}']]
            assert len(mg)<=1, 'Two clients received the single memory port in one cycle'
            assert len(ag)<=1, 'Two clients received the single ALU port in one cycle'
            if drive['stall']:
                assert not mg and not ag, 'Service dispatched despite global stall'
            if drive['reset']:
                memory=[0]*config.depth;slots=[None]*n;expected=[None]*n;ext_value=None
            else:
                for i in range(n):
                    if prior[f'response_valid_{i}']:
                        assert expected[i] is not None, f'Unexpected response for client {i}'
                        assert (prior[f'response_data_{i}'],prior[f'response_fault_{i}'])==expected[i],(
                            f'Client {i} completion does not match independent reference: '
                            f'{(prior[f"response_data_{i}"],prior[f"response_fault_{i}"])} != {expected[i]}')
                        if prior[f'response_accepted_{i}']:
                            expected[i]=None;slots[i]=None;completed+=1
                for i in range(n):
                    if prior[f'request_accepted_{i}']:
                        assert slots[i] is None,f'Client {i} accepted another request before response consumed'
                        slots[i]=(drive[f'opcode_{i}'],drive[f'a_{i}'],drive[f'b_{i}'])
                        accepted+=1
                for i in mg:
                    assert slots[i] is not None,f'Memory grant for nonqueued client {i}'
                    op,a,b=slots[i]
                    assert op in (2,3),'Memory port dispatched an arithmetic opcode'
                    if a>=config.depth:out=(0,1)
                    elif op==2:out=(memory[a],0)
                    else:memory[a]=b;out=(0,0)
                    expected[i]=out;memory_grants+=1
                for i in ag:
                    assert slots[i] is not None,f'ALU grant for nonqueued client {i}'
                    op,a,b=slots[i]
                    assert op in (0,1),'ALU port dispatched a memory opcode'
                    expected[i]=((a+b if op==0 else a*b)&mask,0)
                    alu_grants+=1
                    if config.operator=='external':
                        assert ext_value is None,'External ALU received overlapping transaction'
                        ext_value=expected[i][0]
                        ext_due=clock+2+rng.randrange(6)
                if config.operator=='external' and prior['operator_response_ready'] and drive['operator_response_valid']:
                    assert ext_value is not None,'Operator completed without an active request'
                    ext_value=None
            previous=sim.register_snapshot()
            sim.step(drive,clock=True)
            if drive['stall'] and not drive['reset']:
                assert previous==sim.register_snapshot(),'Stall modified the storage state'
        assert accepted>8 and completed>5,'Not enough transactions completed for a meaningful test'
        assert memory_grants>3 and alu_grants>3,'One of the resource ports was not exercised'
        return {'status':'PASS','seed':seed,'cycles':cycles,'requests_accepted':accepted,
                'responses_consumed':completed,'memory_grants':memory_grants,
                'operator_grants':alu_grants,'reference':'Independent transaction/memory scoreboard',
                'exhaustive':False}
    except (AssertionError,KeyError,IndexError,TypeError,ValueError) as exc:
        return {'status':'FAIL','seed':seed,'cycle':clock,'message':str(exc),
                'trace_last_10':recent,'reference':'Independent transaction/memory scoreboard'}
