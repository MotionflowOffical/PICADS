"""Independent source-behavior comparison for transactional DLS.

The source interpreter operates on AST bitvectors, NOT on generated CFG/DLS.
Reports deterministic vectors, exact simulator cycles, memory state and causes.
"""
from __future__ import annotations
import ast, random, re
from .reference import SourceInterpreter,V,annotation_type
from .verification import VerificationReport

class MemoryFault(Exception):pass

class Reference(SourceInterpreter):
    def __init__(self,source,top,depth=0,width=0):
        super().__init__(source,top)
        self.memory=[0]*depth
        self.memory_width=width
        self.local_types={}

    def _expr(self,n,env):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='mem_read':
            addr=self._expr(n.args[0],env).num
            if addr>=len(self.memory):raise MemoryFault(f'Memory read out of range: {addr}')
            return V(self.memory[addr],self.memory_width)
        return super()._expr(n,env)

    def _block(self,statements,env):
        for s in statements:
            if isinstance(s,ast.Return):return self._expr(s.value,env)
            if isinstance(s,(ast.Assign,ast.AnnAssign)):
                target=s.target if isinstance(s,ast.AnnAssign) else s.targets[0]
                v=self._expr(s.value,env)
                if isinstance(s,ast.AnnAssign):
                    t=annotation_type(s.annotation);self.local_types[target.id]=t
                if target.id in self.local_types:
                    t=self.local_types[target.id];v=v.cast(t.width,t.signed)
                env[target.id]=v
            elif isinstance(s,ast.If):
                value=self._expr(s.test,env).truth()
                result=self._block(s.body if value else s.orelse,env)
                if result is not None:return result
            elif isinstance(s,ast.For):
                args=[x.value for x in s.iter.args]
                for j in range(*args):
                    env[s.target.id]=V(j,max(1,j.bit_length()+int(j<0)),j<0)
                    result=self._block(s.body,env)
                    if result is not None:return result
            elif isinstance(s,ast.Expr) and isinstance(s.value,ast.Call) and isinstance(s.value.func,ast.Name) and s.value.func.id=='mem_write':
                addr=self._expr(s.value.args[0],env).num
                value=self._expr(s.value.args[1],env).num
                if addr>=len(self.memory):raise MemoryFault(f'Memory write out of range: {addr}')
                self.memory[addr]=value&((1<<self.memory_width)-1)
            elif isinstance(s,ast.Pass):pass
            else:raise ValueError(f'Unsupported reference statement {type(s).__name__}')
        return None


def verify_transactional(source,design,issues,random_vectors=48):
    sched=design.metadata['schedule']
    memory=sched.get('memory') or {}
    depth=memory.get('depth') or 0
    width=memory.get('data_width') or 0
    rng=random.Random(17071)
    inputs={k:v for k,v in design.inputs.items() if k not in ('start','stall','reset') and not k.startswith('unit_ready_')}
    ctrl={k:1 for k in design.inputs if k.startswith('unit_ready_')}
    try:
        sim=design.new_simulator()
        ref=Reference(source,design.metadata.get('top',design.name),depth,width)
    except Exception as exc:
        issues.add('VERIFY.CFG_SETUP','ERROR','VERIFIER','equivalence',str(exc))
        return VerificationReport('ERROR',0,False,[])
    tests=[{k:0 for k in inputs},{k:(1<<w)-1 for k,w in inputs.items()}]
    tests.extend({k:rng.getrandbits(w) for k,w in inputs.items()} for _ in range(random_vectors))
    failures=[]
    last_result=0
    instructions=sched['instructions']
    max_edges=sum(int(x.get('latency',1)) for x in instructions)+48
    for index,test in enumerate(tests):
        try:
            expected=ref.step(test)['result'];fault=0
        except MemoryFault:
            expected=last_result;fault=1
        except Exception as exc:
            issues.add('VERIFY.CFG_REFERENCE','ERROR','VERIFIER','equivalence',str(exc),
                       evidence={'vector':index,'inputs':test})
            return VerificationReport('ERROR',index,False,failures)
        start={**test,**ctrl,'start':1,'stall':0,'reset':0}
        if sim.step(start,clock=False)['ready']!=1:
            failures.append({'index':index,'reason':'Controller not READY at transaction start',
                             'state':sim.register_snapshot()});break
        sim.step(start,clock=True)
        complete=False;trace=[]
        for edge in range(max_edges):
            # Exercise both global stalls and shared-unit backpressure while
            # changing original inputs to catch accidental live-input use.
            stall=int(edge>0 and edge%11==0)
            active_controls={k:(0 if edge%7==3 else 1) for k in ctrl}
            inputs_changed={k:rng.getrandbits(w) for k,w in inputs.items()}
            driver={**inputs_changed,**active_controls,'start':1 if edge%5==0 else 0,'stall':stall,'reset':0}
            snapshot=sim.register_snapshot()
            current=[(int(m.group(1)),int(m.group(2))) for k,v in snapshot.items()
                     if v and (m:=re.search(r'/r_pc_(\d+)_(\d+)$',k))]
            trace.append({'edge':edge,'active_instruction':current[0][0] if current else None,
                          'phase':current[0][1] if current else None,
                          'source_line':instructions[current[0][0]]['lineno'] if current else None,
                          'operation':instructions[current[0][0]]['kind'] if current else None,
                          'stall':stall,
                          'unit_ready':active_controls})
            if len(trace)>40:trace.pop(0)
            before=snapshot if stall else None
            sim.step(driver,clock=True)
            post=sim.step(driver,clock=False)
            if stall and before!=sim.register_snapshot():
                failures.append({'index':index,'edge':edge,'reason':'State changed while STALL asserted',
                                 'before':before,'after':sim.register_snapshot()});break
            active=[k for k,v in sim.register_snapshot().items() if '/r_pc_' in k and v]
            if len(active)>1:
                failures.append({'index':index,'edge':edge,'reason':'Multiple one-hot controller states active',
                                 'active':active});break
            if post['done']:
                complete=True
                if post['result']!=expected or post['fault']!=fault or not post['ready']:
                    failures.append({'index':index,'edge':edge,'inputs':test,
                                     'expected':{'result':expected,'fault':fault,'ready':1},'actual':post,
                                     'reason':'Source/DLS result or handshake mismatch'})
                if not fault:last_result=expected
                if depth:
                    state=sim.register_snapshot()
                    physical=[state[f'{design.name}/r_mem_{j}'] for j in range(depth)]
                    if physical!=ref.memory:
                        failures.append({'index':index,'edge':edge,'reason':'Memory contents diverge',
                                         'expected_memory':list(ref.memory),'actual_memory':physical})
                sim.step({**test,**ctrl,'start':0,'stall':0,'reset':0},clock=True)
                if sim.step({**test,**ctrl,'start':0,'stall':0,'reset':0},clock=False)['done']:
                    failures.append({'index':index,'reason':'DONE remained asserted after an unstalled idle clock'})
                break
        if failures:
            failures[-1].setdefault('execution_trace',list(trace))
            break
        if not complete:
            failures.append({'index':index,'reason':'Transaction did not complete within bounded cycle limit',
                             'maximum_edges':max_edges,'inputs':test,'state':sim.register_snapshot(),
                             'execution_trace':list(trace)})
            break
    if failures:
        issues.add('VERIFY.CFG_MISMATCH','ERROR','VERIFIER','equivalence',
                   'Transactional circuit differs from independent source behavior or clock protocol.',
                   cause='Source lowering, DLS gate connections, state transitions or memory logic differ.',
                   remedy='Replay the exact seed and input vector; inspect failing state and instruction indices.',
                   evidence={'seed':17071,'first_counterexample':failures[0],'failures':failures})
    else:
        issues.add('VERIFY.CFG_SAMPLED','WARNING','VERIFIER','equivalence',
                   'Transactional verification passed deterministic sampled vectors, stalls and memory checks; this is not formal equivalence.',
                   evidence={'seed':17071,'transactions':len(tests)},
                   remedy='Perform RTL simulation and sequential formal verification for production designs.')
    return VerificationReport('FAIL' if failures else 'PASS_SAMPLED',len(tests) if not failures else index+1,False,failures,17071)
