"""Experimental but executable single-transaction, time-multiplexed arithmetic.

This is deliberately narrower than general-purpose HLS: straight-line unsigned
bit-vector functions, no helper calls or branches, with integer + - * & | ^.
Static schedule binds multiple operations onto the same gate network at
separate cycles. A one-hot controller, sampled inputs, intermediate registers,
READY/START/DONE handshake, and structural RTL are all generated from DLS.
Unsupported behavior is rejected, never reinterpreted as combinational RTL.
"""
from __future__ import annotations
import ast,hashlib,random
from dataclasses import dataclass,asdict
from .generator import LogicBuilder,parse_type
from .diagnostics import IssueCollector,DiagnosticException
from .ir import Bus,DLS

@dataclass(frozen=True)
class Value:
    source:str
    width:int
    kind:str='signal' # signal, op, const
    constant:int=0

@dataclass
class Operation:
    id:str
    kind:str
    left:Value
    right:Value
    width:int
    lineno:int
    cycle:int=0
    lane:int=0

class ScheduleError(ValueError):pass

class TimeShareCompiler:
    def __init__(self,issues:IssueCollector|None=None,co:dict|None=None):
        self.issues=issues if issues is not None else IssueCollector()
        self.co=co or {}

    def _fail(self,code,why,node=None):
        i=self.issues.add(code,'ERROR','CO' if code.startswith('CO.') else 'SOURCE','schedule',why,
                          line=getattr(node,'lineno',None),cause='Feature is unsupported by the time-sharing scheduler.',
                          remedy='Use straight-line unsigned typed source or disable schedule.mode: time_share.')
        raise DiagnosticException(i)

    def compile_source(self,source:str,path:str='<memory>',top:str|None=None)->DLS:
        try:tree=ast.parse(source,filename=path)
        except SyntaxError as ex:self._fail('SOURCE.SYNTAX',str(ex))
        functions={f.name:f for f in tree.body if isinstance(f,ast.FunctionDef)}
        name=top or next(iter(functions),'')
        if name not in functions:self._fail('SOURCE.NO_TOP',f'No source function {name!r}')
        f=functions[name]
        design_name=f.name
        env={};inputs={}
        for a in f.args.args:
            ty=parse_type(a.annotation,self.issues,path)
            if ty.signed or ty.width>64:self._fail('CO.TIME_SHARE_TYPE','Only unsigned inputs of width 1..64 are supported.',a)
            inputs[a.arg]=ty.width;env[a.arg]=Value(a.arg,ty.width)
        ops=[]
        selections={}
        operator_map={ast.Add:'ADD',ast.Sub:'SUB',ast.Mult:'MUL',ast.BitAnd:'AND',ast.BitOr:'OR',ast.BitXor:'XOR'}
        def expression(node):
            if isinstance(node,ast.Name):
                if node.id not in env:self._fail('SOURCE.UNDEFINED_SYMBOL',f'Unknown symbol {node.id!r}',node)
                return env[node.id]
            if isinstance(node,ast.Constant) and type(node.value)==int and node.value>=0:
                return Value('',max(1,node.value.bit_length()),'const',node.value)
            if isinstance(node,ast.IfExp):
                return selection(expression(node.test), expression(node.body), expression(node.orelse), node)
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):
                return negate(expression(node.operand),node)
            if isinstance(node,ast.Compare):
                if len(node.ops)!=1 or len(node.comparators)!=1:
                    self._fail('CO.TIME_SHARE_CONDITION','Chained comparisons are not supported.',node)
                comparators={ast.Eq:'EQ',ast.NotEq:'NE',ast.Lt:'LT',ast.LtE:'LE',ast.Gt:'GT',ast.GtE:'GE'}
                label=next((v for k,v in comparators.items() if isinstance(node.ops[0],k)),None)
                if label is None:self._fail('CO.TIME_SHARE_CONDITION','Unsupported comparison.',node)
                left=expression(node.left);right=expression(node.comparators[0]);key=f'cmp_{len(selections):04d}'
                selections[key]={'kind':'compare','op':label,'left':left,'right':right,'line':node.lineno}
                return Value(key,1,'select')
            if isinstance(node,ast.BinOp):
                kind=next((label for typ,label in operator_map.items() if isinstance(node.op,typ)),None)
                if not kind:self._fail('CO.TIME_SHARE_OP',f'Unsupported scheduled operator: {type(node.op).__name__}',node)
                left=expression(node.left);right=expression(node.right)
                if kind=='ADD':width=max(left.width,right.width)+1
                elif kind=='MUL':width=left.width+right.width
                else:width=max(left.width,right.width)
                if width>128:self._fail('CO.TIME_SHARE_WIDTH','Scheduled intermediate exceeds supported 128 bits.',node)
                key=f'op_{len(ops):04d}'
                ops.append(Operation(key,kind,left,right,width,node.lineno))
                return Value(key,width,'op')
            self._fail('CO.TIME_SHARE_EXPRESSION',f'Unsupported scheduled expression: {type(node).__name__}',node)
        def selection(condition,positive,negative,node):
            key=f'sel_{len(selections):04d}'
            selections[key]={'kind':'mux','condition':condition,'yes':positive,'no':negative,
                             'line':getattr(node,'lineno',None)}
            return Value(key,max(positive.width,negative.width),'select')
        def negate(value,node):
            key=f'sel_{len(selections):04d}'
            selections[key]={'kind':'not','value':value,'line':node.lineno}
            return Value(key,1,'select')
        def assignment(statement):
            if isinstance(statement,ast.Assign) and len(statement.targets)==1 and isinstance(statement.targets[0],ast.Name):
                env[statement.targets[0].id]=expression(statement.value)
                return True
            if isinstance(statement,ast.AnnAssign) and isinstance(statement.target,ast.Name):
                ty=parse_type(statement.annotation,self.issues,path)
                if ty.signed:self._fail('CO.TIME_SHARE_TYPE','Signed local values unsupported.',statement)
                val=expression(statement.value)
                if ty.width>128:self._fail('CO.TIME_SHARE_WIDTH','Local value width exceeds 128.',statement)
                env[statement.target.id]=Value(val.source,ty.width,val.kind,val.constant)
                return True
            return False
        expansions=[0]
        def unroll(statement,depth=0):
            if depth>8:
                self._fail('CO.TIME_SHARE_LOOP_DEPTH','Maximum statically unrolled loop depth exceeded.',statement)
            if not isinstance(statement.target,ast.Name) or statement.orelse:
                self._fail('CO.TIME_SHARE_LOOP','Only simple for-index loops without else are supported.',statement)
            call=statement.iter
            if not (isinstance(call,ast.Call) and isinstance(call.func,ast.Name)
                and call.func.id=='range' and not call.keywords and
                1<=len(call.args)<=3 and all(type(a.value)==int for a in call.args if isinstance(a,ast.Constant))
                and all(isinstance(a,ast.Constant) for a in call.args)):
                self._fail('CO.TIME_SHARE_LOOP','Loop must be for i in range(<constant integers>).',statement)
            try:indices=range(*(a.value for a in call.args))
            except ValueError:self._fail('CO.TIME_SHARE_LOOP','range step cannot be zero.',statement)
            if len(indices)>32 or expansions[0]+len(indices)>64:
                self._fail('CO.TIME_SHARE_LOOP_LIMIT','Loop expansion limit is 32 iterations per loop and 64 total.',statement)
            expansions[0]+=len(indices)
            for i in indices:
                if i<0:self._fail('CO.TIME_SHARE_LOOP','Negative loop indices are not yet supported.',statement)
                env[statement.target.id]=Value('',max(1,i.bit_length()),'const',i)
                for inner in statement.body:
                    if isinstance(inner,ast.For):unroll(inner,depth+1)
                    elif isinstance(inner,ast.Pass):continue
                    elif not assignment(inner):
                        self._fail('CO.TIME_SHARE_LOOP_BODY',
                            'Only pure assignments and nested bounded loops are permitted inside a scheduled loop.',inner)
        output=None
        for index,statement in enumerate(f.body):
            if assignment(statement):continue
            elif isinstance(statement,ast.For):
                unroll(statement)
            elif isinstance(statement,ast.Return):
                output=expression(statement.value)
                if index<len(f.body)-1:
                    self._fail('CO.TIME_SHARE_UNREACHABLE','Statements after return are not supported.',f.body[index+1])
                break
            elif isinstance(statement,ast.If):
                # Pure terminal branches are evaluated speculatively in separate
                # scheduled datapaths and selected using the captured predicate.
                # This never speculates side effects: only a single Return is allowed.
                trailing=f.body[index+1:]
                alternate=statement.orelse or trailing
                if (len(statement.body)!=1 or not isinstance(statement.body[0],ast.Return)
                    or len(alternate)!=1 or not isinstance(alternate[0],ast.Return)
                    or (statement.orelse and trailing)):
                    self._fail('CO.TIME_SHARE_BRANCH',
                        'Only terminal if/else returns, or if-return followed by return, are supported.',statement)
                output=selection(expression(statement.test), expression(statement.body[0].value),
                                 expression(alternate[0].value),statement)
                break
            else:self._fail('CO.TIME_SHARE_STATEMENT',f'Unsupported scheduled statement: {type(statement).__name__}',statement)
        if output is None:self._fail('SOURCE.MISSING_RETURN','Scheduled function must return a value.',f)
        out_ty=parse_type(f.returns,self.issues,path)
        if out_ty.signed or out_ty.width>128:self._fail('CO.TIME_SHARE_TYPE','Unsigned return width <=128 required.',f)
        if not ops:self._fail('CO.TIME_SHARE_NO_OPERATIONS','No operations to schedule; use normal compilation.',f)
        limits=(self.co.get('allocation') or {}).get('max_instances',{}) or {}
        unit_counts={k:int(limits.get(k,1)) for k in set(o.kind for o in ops)}
        if any(c<1 for c in unit_counts.values()):self._fail('CO.RESOURCE_LIMIT','Units per type must be positive.')
        used={}
        slots={}
        def dependencies(value):
            if value.kind=='op':return {value.source}
            if value.kind!='select':return set()
            item=selections[value.source]
            names={'mux':('condition','yes','no'),'not':('value',),'compare':('left','right')}[item['kind']]
            return set().union(*(dependencies(item[k]) for k in names))
        for op in ops:
            required=dependencies(op.left)|dependencies(op.right)
            earliest=max((used[x]+1 for x in required),default=0)
            while True:
                occupancy=slots.setdefault((earliest,op.kind),set())
                if len(occupancy)<unit_counts[op.kind]:
                    op.cycle=earliest;op.lane=next(i for i in range(unit_counts[op.kind]) if i not in occupancy)
                    occupancy.add(op.lane);used[op.id]=earliest;break
                earliest+=1
                if earliest>=32:self._fail('CO.TIME_SHARE_LATENCY','Schedule exceeds 32 cycles.',f)
        cycles=max(o.cycle for o in ops)+1
        if cycles>32:self._fail('CO.TIME_SHARE_LATENCY','Schedule exceeds 32 cycles.',f)
        if 'start' in inputs:self._fail('CO.TIME_SHARE_PORT','Source input start conflicts with generated handshake.',f)
        builder=LogicBuilder(name,{**inputs,'start':1})
        b=builder
        b.registers['idle']={'next':['@0'],'init':1}
        for i in range(cycles):b.registers[f'step_{i}']={'next':['@0'],'init':0}
        b.registers['commit']={'next':['@0'],'init':0}
        b.registers['done']={'next':['@0'],'init':0}
        for inp,width in inputs.items():b.registers[f'in_{inp}']={'next':['@0']*width,'init':0}
        for op in ops:b.registers[op.id]={'next':['@0']*op.width,'init':0}
        b.registers['output']={'next':['@0']*out_ty.width,'init':0}
        def reg(name,width,signed=False):return Bus(tuple(f'${name}[{i}]' for i in range(width)),signed)
        idle=reg('idle',1);start=Bus(('start[0]',))
        accept=b.gate('AND',idle.bits[0],start.bits[0]);not_start=b.gate('NOT',start.bits[0])
        b.registers['idle']['next']=[b.gate('OR',b.gate('AND',idle.bits[0],not_start),'$commit[0]')]
        b.registers['step_0']['next']=[accept]
        for i in range(1,cycles):b.registers[f'step_{i}']['next']=[f'$step_{i-1}[0]']
        b.registers['commit']['next']=[f'$step_{cycles-1}[0]']
        b.registers['done']['next']=['$commit[0]']
        for name,width in inputs.items():
            old=reg('in_'+name,width);new=Bus(tuple(f'{name}[{i}]' for i in range(width)))
            b.registers['in_'+name]['next']=list(b.mux(Bus((accept,)),old,new).bits)
        def operand(v):
            if v.kind=='const':return b.const(v.constant,v.width)
            if v.kind=='select':
                sel=selections[v.source]
                if sel['kind']=='mux':
                    result=b.mux(operand(sel['condition']),operand(sel['no']),operand(sel['yes']))
                elif sel['kind']=='not':
                    result=Bus((b.gate('NOT',b.is_nonzero(operand(sel['value']))),))
                elif sel['kind']=='compare':
                    result=b.compare(sel['op'],operand(sel['left']),operand(sel['right']))
                else:raise AssertionError(sel['kind'])
                return b.extend(result,v.width)
            if v.kind=='signal':
                if v.source not in inputs:self._fail('CO.TIME_SHARE_SYMBOL',f'Unresolved scheduled symbol {v.source!r}',f)
                base=reg('in_'+v.source,inputs[v.source])
                return b.extend(base,v.width)
            if v.kind=='op':
                # Assigned intermediate signals can be narrower than the op register.
                base=reg(v.source,next(o.width for o in ops if o.id==v.source))
                return b.extend(base,v.width)
            raise AssertionError(v.kind)
        grouped={}
        for op in ops:grouped.setdefault((op.kind,op.lane),[]).append(op)
        bindings=[]
        for (kind,lane),users in sorted(grouped.items()):
            wa=max(x.left.width for x in users);wb=max(x.right.width for x in users)
            sel_a=b.const(0,wa);sel_b=b.const(0,wb)
            for op in users:
                sel=Bus((f'$step_{op.cycle}[0]',))
                sel_a=b.mux(sel,sel_a,b.extend(operand(op.left),wa))
                sel_b=b.mux(sel,sel_b,b.extend(operand(op.right),wb))
            b.origin=f'{path}:shared_{kind}_{lane}'
            if kind=='ADD':result=b.add(sel_a,sel_b)
            elif kind=='SUB':result=b.sub(sel_a,sel_b)
            elif kind=='MUL':result=b.mul(sel_a,sel_b)
            else:result=b.binary_gate(kind,sel_a,sel_b)
            for op in users:
                old=reg(op.id,op.width)
                sample=b.extend(result,op.width)
                b.registers[op.id]['next']=list(b.mux(Bus((f'$step_{op.cycle}[0]',)),old,sample).bits)
                bindings.append({'operation':op.id,'kind':kind,'cycle':op.cycle,'unit':f'{kind}_{lane}',
                                 'source_line':op.lineno,'width':op.width})
        last=b.extend(operand(output),out_ty.width)
        b.registers['output']['next']=list(b.mux(Bus(('$commit[0]',)),reg('output',out_ty.width),last).bits)
        out={'result':list(reg('output',out_ty.width).bits),'done':['$done[0]'],'ready':['$idle[0]']}
        dls=DLS(design_name,b.inputs,out,b.nodes,b.registers,
                {'top':design_name,'source':path,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                 'return_width':out_ty.width,'return_signed':False,
                 'schedule':{'mode':'time_share','execution_cycles':cycles,
                     'latency_edges_from_start':cycles+2,
                     'initiation_interval_cycles':cycles+2,
                     'protocol':'start sampled on READY edge; DONE pulses after final COMMIT edge',
                     'bindings':bindings,'physical_units':{k:len(set(x.lane for x in ops if x.kind==k)) for k in unit_counts},
                     'warning':'Single transaction in flight; does not pipeline overlapping transactions'},
                 'strategies':b.strategies,'operators':[asdict(x) for x in ops],
                 'predicates':{k:{'kind':v['kind'],'source_line':v['line']} for k,v in selections.items()},
                 'unrolled_iterations':expansions[0],
                 'compiler':'chipcompiler 0.5 time-sharing'})
        dls.validate()
        return dls


def verify_time_share(source,design,issues,random_vectors=128):
    """Drive serial source transactions; change inputs while busy to detect accidental dependencies."""
    from .reference import SourceInterpreter
    from .verification import VerificationReport
    from .diagnostics import IssueCollector
    width={k:v for k,v in design.inputs.items() if k!='start'}
    try:sim=design.new_simulator();ref=SourceInterpreter(source,design.name)
    except Exception as exc:
        issues.add('VERIFY.SCHEDULE_SETUP','ERROR','VERIFIER','equivalence',str(exc))
        return VerificationReport('ERROR',0,False,[])
    rng=random.Random(1729)
    vectors=[{k:0 for k in width},{k:(1<<w)-1 for k,w in width.items()}]
    vectors += [{k:rng.getrandbits(w) for k,w in width.items()} for _ in range(random_vectors)]
    cycles=design.metadata['schedule']['execution_cycles']
    errors=[]
    for n,inp in enumerate(vectors):
        start={**inp,'start':1}
        if sim.step(start,clock=False)['ready']!=1:
            errors.append({'index':n,'reason':'Not ready at transaction start'});break
        expected=ref.step(inp)['result']
        sim.step(start)
        for cycle in range(cycles):
            changed={k:rng.getrandbits(w) for k,w in width.items()}
            output=sim.step({**changed,'start':1},clock=True)
            post=sim.step({**changed,'start':0},clock=False)
            if post['done']:
                errors.append({'index':n,'cycle':cycle,'reason':'Early DONE pulse','actual':post});break
        if errors:break
        changed={k:rng.getrandbits(w) for k,w in width.items()}
        sim.step({**changed,'start':0})
        actual=sim.step({**changed,'start':0},clock=False)
        if actual['done']!=1 or actual['result']!=expected or actual['ready']!=1:
            errors.append({'index':n,'inputs':inp,'expected':expected,'actual':actual,
                           'reason':'Incorrect scheduled result/handshake','cycle':sim.cycle})
            if len(errors)>=8:break
        # DONE is a one-cycle pulse. Next idle clock clears it.
        sim.step({**changed,'start':0})
        if sim.step({**changed,'start':0},clock=False)['done']:
            errors.append({'index':n,'reason':'DONE is stuck high'});break
    if errors:
        issues.add('VERIFY.SCHEDULE_MISMATCH','ERROR','VERIFIER','equivalence',
                   'Time-shared generated DLS failed a cycle-level source/protocol comparison.',
                   cause='Incorrect operator schedule, register/control wiring or simulation.',
                   remedy='Replay input vector and inspect schedule.bindings and internal state.',
                   evidence={'first_counterexample':errors[0],'failures':errors})
    else:
        issues.add('VERIFY.SCHEDULE_SAMPLED','WARNING','VERIFIER','equivalence',
                   'Time-shared design passed deterministic transaction samples; formal proof not performed.',
                   evidence={'seed':1729,'transactions':len(vectors)},
                   remedy='Use sequential formal equivalence for exhaustive proof.')
    return VerificationReport('FAIL' if errors else 'PASS_SAMPLED',len(vectors),False,errors)
