"""Independent behavioral and protocol checks for globally shared register RAM.

Two different checks deliberately remain distinct:
  * sequential reference runs compare each source process with an independent
    AST interpreter while every other client is idle;
  * simultaneous access uses a separate cycle-accurate memory-port scoreboard
    that checks bank state, accepted request ownership and data at each grant.
Concurrent source-level serializability is NOT proven for arbitrary conflicts.
"""
from __future__ import annotations
import random
from .transactional_verify import Reference, MemoryFault


def verify_shared_memory(source, design, issues, rounds=6, seed=13013):
    info=design.metadata['schedule'];clients=info['source_bindings']
    depth=info['shared_memory_depth'];data_width=info['shared_memory_data_width']
    rng=random.Random(seed);sim=design.new_simulator()
    values={key:0 for key in design.inputs};values['reset']=1
    sim.step(values);values['reset']=0
    mem=[0]*depth;completed=0;grants_seen=0;reads=0;writes=0;faults=0
    def fail(reason,**data):return {'status':'FAIL','reason':reason,**data}
    def check_bank(edge,stage):
        snap=sim.register_snapshot()
        for j,expected in enumerate(mem):
            actual=snap[f'{design.name}/r_shared_mem_{j}']
            if actual!=expected:
                return fail('shared memory bank differs from independent scoreboard',
                            stage=stage,edge=edge,address=j,expected=expected,actual=actual)
        return None
    def clock(stage,edge):
        nonlocal reads,writes,grants_seen,faults
        output=sim.step(values,clock=False)
        selected=[];pending=[]
        for c in clients:
            n=c['client'];request=output[f'arb_request_mem_{n}'];grant=output[f'arb_grant_mem_{n}']
            if request:pending.append(n)
            if grant:
                selected.append(n)
                if not request or values['reset'] or values[f'{n}_stall']:
                    return fail('memory service grant without valid request',stage=stage,edge=edge,client=n)
        if len(selected)>1 or (pending and not selected and not values['reset']):
            return fail('memory arbitration lost a request or double-granted',stage=stage,edge=edge,
                        pending=pending,selected=selected)
        if selected:
            n=selected[0];address=output[f'arb_mem_addr_{n}'];writing=output[f'arb_mem_write_{n}']
            grants_seen+=1
            if address<depth:
                if writing:
                    mem[address]=output[f'arb_mem_wdata_{n}'] & ((1<<data_width)-1)
                    writes+=1
                else:
                    expected=mem[address];actual=output[f'arb_mem_rdata_{n}']
                    # Validate the real datapath feeding the selected source FSM.
                    bit_wires=[sim.last_signals[f'shared_mem_{n}_result_{j}'] for j in range(data_width)]
                    internal=sum(bit<<j for j,bit in enumerate(bit_wires))
                    if actual!=expected or internal!=expected:
                        return fail('memory read result differs from independent bank model',
                                    stage=stage,edge=edge,client=n,address=address,
                                    expected=expected,observed=actual,internal=internal)
                    reads+=1
            else:faults+=1
        sim.step(values)
        return check_bank(edge,stage)
    # Isolated source equivalence: each process uses the same shared RAM, but
    # only one source FSM runs at a time. This is stronger than a bus-only check.
    for c in clients:
        n=c['client'];reference=Reference(source,c['function'],depth,data_width)
        for round_number in range(rounds):
            reference.memory=mem[:]
            args={k:rng.getrandbits(design.inputs[f'{n}_{k}']) for k in c['source_inputs']}
            for k,v in args.items():values[f'{n}_{k}']=v
            try:expected=reference.step(args)['result'];fault=0
            except MemoryFault:expected=None;fault=1
            except Exception as exc:return fail('source interpreter raised error',client=n,error=str(exc))
            values[f'{n}_start']=1;values[f'{n}_stall']=0
            if sim.step(values,clock=False)[n+'_ready']!=1:
                return fail('source process not ready before isolated request',client=n)
            failure=clock('isolated',0)
            if failure:return failure
            values[f'{n}_start']=0
            for edge in range(320):
                values[f'{n}_stall']=int(edge>0 and edge%21==0)
                failure=clock('isolated',edge+1)
                if failure:return failure
                output=sim.step(values,clock=False)
                if output[n+'_done']:
                    if output[n+'_fault']!=fault or (not fault and output[n+'_result']!=expected):
                        return fail('isolated source result differs from AST reference',
                          client=n,inputs=args,expected={'result':expected,'fault':fault},
                          observed={'result':output[n+'_result'],'fault':output[n+'_fault']})
                    if mem!=reference.memory:
                        return fail('isolated source memory side effects differ from AST reference',
                                    client=n,expected=reference.memory,actual=mem)
                    completed+=1
                    break
            else:return fail('isolated source process did not finish',client=n)
            values[f'{n}_stall']=0
            failure=clock('drain',0)
            if failure:return failure
    # Parallel contention: scoreboard checks bus-level ownership and storage
    # order, rather than claiming atomic source-level execution.
    for round_number in range(rounds):
        for c in clients:
            n=c['client']
            if sim.step(values,clock=False)[n+'_ready']!=1:
                return fail('source process was not ready for concurrent request',client=n)
            for key in c['source_inputs']:
                values[f'{n}_{key}']=rng.getrandbits(design.inputs[f'{n}_{key}'])
            values[f'{n}_start']=1;values[f'{n}_stall']=0
        failure=clock('concurrent',0)
        if failure:return failure
        for c in clients:values[f'{c["client"]}_start']=0
        seen=set()
        for edge in range(400):
            for c in clients:
                n=c['client'];values[f'{n}_stall']=int(edge>0 and (edge+len(n))%19==0)
                for key in c['source_inputs']:
                    values[f'{n}_{key}']=rng.getrandbits(design.inputs[f'{n}_{key}'])
            failure=clock('concurrent',edge+1)
            if failure:return failure
            output=sim.step(values,clock=False)
            seen.update(c['client'] for c in clients if output[c['client']+'_done'])
            if len(seen)==len(clients):
                completed+=len(clients);break
        else:return fail('concurrent execution timeout',round=round_number,finished=sorted(seen))
        for c in clients:values[f'{c["client"]}_stall']=0
        failure=clock('drain',round_number)
        if failure:return failure
    issues.add('VERIFY.GLOBAL_MEMORY_PROTOCOL','WARNING','VERIFIER','equivalence',
        'Shared RAM passed isolated source comparisons and concurrent bus-scoreboard checks; arbitrary interleaving is not formally proven.',
        evidence={'isolated_iterations':rounds*len(clients),'concurrent_batches':rounds,'seed':seed})
    return {'status':'PASS','verification':'isolated AST-source equivalence plus concurrent grant/bank scoreboard',
            'concurrent_atomic_source_equivalence':'NOT_PROVEN','seed':seed,'completed':completed,
            'grants':grants_seen,'read_grants':reads,'write_grants':writes,'invalid_address_grants':faults}
