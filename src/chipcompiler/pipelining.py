"""Gate-preserving synchronous pipelining for combinational DLS.

Retimes DAG paths across explicitly clocked stages. No operator time-sharing is
claimed: this changes register placement/latency, not area-reduced scheduling.
The gate graph, stage-crossing registers and valid pipeline are all executable
by the existing DLS interpreter and emitted by the existing RTL exporter.
"""
from __future__ import annotations
from dataclasses import dataclass
from .ir import DLS,Node

class PipelineError(ValueError):
    pass

def pipeline_dls(design:DLS, stages:int)->DLS:
    if type(stages) is not int or not 1<=stages<=32:
        raise PipelineError('CO schedule.pipeline_stages must be an integer in [1, 32]')
    design.validate()
    if design.registers:
        raise PipelineError('Cannot automatically pipeline stateful DLS; existing registers need a temporal contract')
    if getattr(design,'instances',None):
        raise PipelineError('Cannot automatically pipeline DLS with hierarchical instances yet')
    if 'input_valid' in design.inputs or 'valid' in design.outputs:
        raise PipelineError('Reserved handshake port name input_valid or valid already exists')
    depth={'@0':0,'@1':0}
    for name,w in design.inputs.items():
        for i in range(w):depth[f'{name}[{i}]']=0
    for n in design.nodes:depth[n.name]=1+max(depth[x] for x in n.inputs)
    max_depth=max((depth[n.name] for n in design.nodes),default=1)
    stage={n.name:min(stages-1,(depth[n.name]-1)*stages//max_depth) for n in design.nodes}
    inputs=dict(design.inputs);inputs['input_valid']=1
    result=DLS(design.name,inputs,{},[],{},dict(design.metadata))
    memo={}
    # Return a source signal propagated to the requested pipeline stage.
    def delayed(pin:str,target:int)->str:
        if pin in ('@0','@1'):return pin
        source=stage.get(pin,-1)  # primary inputs exist in stage zero
        if source==target or (source==-1 and target==0):return pin
        if source>target:raise PipelineError(f'Invalid backwards pipeline edge {pin} ({source}->{target})')
        last=pin
        for k in range(max(source,0),target):
            key=(pin,k)
            if key not in memo:
                name=f'pipe_{len(memo):06d}'
                result.registers[name]={'next':[last],'init':0}
                memo[key]=f'${name}[0]'
            last=memo[key]
        return last
    for node in design.nodes:
        target=stage[node.name]
        result.nodes.append(Node(node.name,node.op,[delayed(x,target) for x in node.inputs],node.origin))
    for output,bits in design.outputs.items():
        names=[]
        for i,pin in enumerate(bits):
            name=f'out_{output}_{i}'
            if not name.isidentifier():raise PipelineError(f'Unusable pipeline output name {output!r}')
            result.registers[name]={'next':[delayed(pin,stages-1)],'init':0}
            names.append(f'${name}[0]')
        result.outputs[output]=names
    last='input_valid[0]'
    for i in range(stages):
        name=f'valid_stage_{i}'
        result.registers[name]={'next':[last],'init':0}
        last=f'${name}[0]'
    result.outputs['valid']=[last]
    result.metadata['pipeline']={
        'stages':stages,'latency_cycles':stages,'initiation_interval_cycles':1,
        'semantics':'rising-edge result and valid available AFTER Nth input clock edge',
        'stage_mapping':stage,'logic_depth':max_depth,
        'registers_are_generated':True,
        'note':'All operators are spatially instantiated; NOT time-multiplexed resource scheduling.'}
    result.validate()
    return result


def verify_pipeline(source,design,issues,limit=4096,random_vectors=256):
    """Compare post-clock output against independent combinational source at N-cycle latency."""
    import itertools,random
    from collections import deque
    from .reference import SourceInterpreter
    from .verification import VerificationReport
    n=design.metadata['pipeline']['latency_cycles']
    widths={k:v for k,v in design.inputs.items() if k!='input_valid'}
    bits=sum(widths.values())
    exhaustive=bits<=12 and 2**bits<=limit
    if exhaustive: vectors=(dict(zip(widths,x)) for x in itertools.product(*(range(1<<w) for w in widths.values())))
    else:
        rng=random.Random(1729)
        vectors=iter([{k:0 for k in widths}, {k:(1<<v)-1 for k,v in widths.items()}]+[
                {k:rng.getrandbits(w) for k,w in widths.items()} for _ in range(random_vectors)])
        issues.add('VERIFY.SAMPLING','WARNING','VERIFIER','equivalence',
            'Pipelined design checked using deterministic samples, not formal proof.',
            remedy='Use formal sequential equivalence for exhaustive guarantees.',
            evidence={'seed':1729,'samples':random_vectors+2,'input_bits':bits})
    try:ref=SourceInterpreter(source,design.metadata.get('top',design.name));sim=design.new_simulator()
    except Exception as ex:
        issues.add('VERIFY.PIPELINE_SETUP','ERROR','VERIFIER','equivalence',str(ex))
        return VerificationReport('ERROR',0,False,[])
    # A sample enters on a rising edge and leaves after ``stages`` edges.
    # Empty bubbles track invalid inputs; no speculative output comparisons.
    pending=deque([None]*(n-1));failures=[];tested=0
    last={k:0 for k in widths}
    def tick(inp,expected):
        nonlocal tested
        valid=expected is not None
        data={**inp,'input_valid':int(valid)}
        pending.append(expected)
        sim.step(data,clock=True)
        actual=sim.step(data,clock=False)
        expected_out=pending.popleft()
        expected_valid=int(expected_out is not None)
        if actual.get('valid')!=expected_valid:
            failures.append({'index':tested,'inputs':inp,'actual':actual,'expected_valid':expected_valid,
                             'reason':'invalid pipeline handshake alignment','cycle':sim.cycle})
            return
        if expected_out is not None:
            measured={key:actual.get(key) for key in expected_out}
            if measured!=expected_out:
                failures.append({'index':tested,'inputs':inp,'actual':measured,'expected':expected_out,
                                 'reason':'latency-aligned behavioral mismatch','cycle':sim.cycle})
    for inp in vectors:
        tested+=1;last=inp
        try:
            tick(inp,ref.step(inp))
        except Exception as exc:
            issues.add('VERIFY.PIPELINE_EXECUTION','ERROR','VERIFIER','equivalence',str(exc),
                       evidence={'inputs':inp,'cycle':tested})
            return VerificationReport('ERROR',tested,exhaustive,failures)
        if len(failures)>=8:break
    if not failures:
        for i in range(n-1):
            tested+=1;tick(last,None)
            if len(failures)>=8:break
    if any(x is not None for x in pending) and not failures:
        failures.append({'reason':'Pipeline failed to drain', 'pending_valid':sum(x is not None for x in pending)})
    if failures:
        issues.add('VERIFY.PIPELINE_MISMATCH','ERROR','VERIFIER','equivalence',
                   f'Pipelined DLS differs from source ({len(failures)} counterexamples).',
                   evidence={'first_counterexample':failures[0], 'failures':failures},
                   cause='Generated pipeline latency, valid alignment or logic is incorrect.',
                   remedy='Inspect stage_mapping, DLS registers and the first failing cycle.')
    return VerificationReport('FAIL' if failures else 'PASS_EXHAUSTIVE' if exhaustive else 'PASS_SAMPLED',
                              tested,exhaustive,failures)
