"""Transactional, guarded-CFG hardware compiler.

Compiles a deliberately bounded *sequential* Python hardware subset into a
one-hot FSM, shared gate-level operators, registers, and an optional register
bank memory. No behavioral arithmetic remains in DLS or Verilog.

One transaction at a time. This is not an external memory protocol or a
physically characterized variable-latency multiplier. Unit readiness is an
explicit input, and operator latency is controller reservation latency.
"""
from __future__ import annotations
import ast, hashlib, math, random
from dataclasses import dataclass, asdict
from .generator import LogicBuilder, parse_type
from .ir import Bus, DLS
from .diagnostics import IssueCollector, DiagnosticException

@dataclass(frozen=True)
class Ref:
    name: str
    width: int
    const: int | None = None

@dataclass
class Command:
    kind: str
    dst: str | None = None
    args: tuple[Ref, ...] = ()
    target: int | None = None
    alternate: int | None = None
    lineno: int = 0
    width: int = 0
    latency: int = 1

class TransactionalCompiler:
    KINDS={ast.Add:'ADD',ast.Sub:'SUB',ast.Mult:'MUL',ast.BitAnd:'AND',
           ast.BitOr:'OR',ast.BitXor:'XOR'}
    COMPARISONS={ast.Eq:'EQ',ast.NotEq:'NE',ast.Lt:'LT',ast.LtE:'LE',ast.Gt:'GT',ast.GtE:'GE'}
    def __init__(self,issues:IssueCollector|None=None,co:dict|None=None):
        self.issues=issues if issues is not None else IssueCollector()
        self.co=co or {}
        self.commands=[];self.locals={};self.typed=set();self.inputs={};self.counter=0
        self.path='<memory>'

    def fail(self,code,message,node=None,origin='SOURCE',evidence=None):
        issue=self.issues.add(code,'ERROR',origin,'transactional',message,file=self.path,
            line=getattr(node,'lineno',None),column=getattr(node,'col_offset',None),
            cause='Unsupported or inconsistent transactional hardware description.',
            remedy='Inspect the reported source/CO declaration. No partial circuit was accepted.',
            evidence=evidence or {})
        raise DiagnosticException(issue)

    def _temp(self,width):
        self.counter+=1
        name=f'_tmp_{self.counter:04d}'
        self.locals[name]=width
        return Ref(name,width)

    def _append(self,kind,dst=None,args=(),node=None,width=0):
        if len(self.commands)>=256:self.fail('CO.CFG_LIMIT','Maximum 256 CFG instructions exceeded.',node,'CO')
        c=Command(kind,dst,tuple(args),lineno=getattr(node,'lineno',0),width=width)
        self.commands.append(c)
        return len(self.commands)-1

    def _expression(self,node):
        if isinstance(node,ast.Name):
            if node.id not in self.locals and node.id not in self.inputs:
                self.fail('SOURCE.UNDEFINED_SYMBOL',f'Unbound value {node.id!r}.',node)
            return Ref(node.id,self.locals.get(node.id,self.inputs.get(node.id)))
        if isinstance(node,ast.Constant) and type(node.value) in (int,bool) and node.value>=0:
            return Ref('',max(1,int(node.value).bit_length()),int(node.value))
        if isinstance(node,ast.BinOp):
            k=next((v for t,v in self.KINDS.items() if isinstance(node.op,t)),None)
            if k is None:self.fail('CO.CFG_OPERATOR',f'Unsupported expression operator {type(node.op).__name__}.',node,'CO')
            a=self._expression(node.left);b=self._expression(node.right)
            width=max(a.width,b.width)+(1 if k=='ADD' else 0)
            if k=='MUL':width=a.width+b.width
            if width>128:self.fail('CO.CFG_WIDTH','Intermediate width exceeds 128 bits.',node,'CO')
            v=self._temp(width);self._append(k,v.name,(a,b),node,width)
            return v
        if isinstance(node,ast.Compare):
            if len(node.ops)!=1 or len(node.comparators)!=1:self.fail('CO.CFG_COMPARE','Chained comparisons are unsupported.',node,'CO')
            kind=next((v for t,v in self.COMPARISONS.items() if isinstance(node.ops[0],t)),None)
            if kind is None:self.fail('CO.CFG_COMPARE','Comparison type unsupported.',node,'CO')
            a=self._expression(node.left);b=self._expression(node.comparators[0]);v=self._temp(1)
            self._append(kind,v.name,(a,b),node,1);return v
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.Not,ast.Invert,ast.USub)):
            a=self._expression(node.operand)
            kind=('NOT' if isinstance(node.op,ast.Not) else 'INV' if isinstance(node.op,ast.Invert) else 'NEG')
            width=1 if kind=='NOT' else a.width
            v=self._temp(width);self._append(kind,v.name,(a,),node,width);return v
        if isinstance(node,ast.BoolOp):
            if len(node.values)<2:self.fail('CO.CFG_BOOL','Boolean expression needs two operands.',node,'CO')
            if any(isinstance(x,ast.Call) for value in node.values for x in ast.walk(value)):
                self.fail('CO.CFG_SHORTCIRCUIT','Function calls inside short-circuit expressions are unsupported.',node,'CO')
            op='BOOL_AND' if isinstance(node.op,ast.And) else 'BOOL_OR'
            current=self._expression(node.values[0])
            for child in node.values[1:]:
                second=self._expression(child);v=self._temp(1)
                self._append(op,v.name,(current,second),node,1)
                current=v
            return current
        if isinstance(node,ast.IfExp):
            condition=self._expression(node.test)
            branch=self._append('BRANCH',None,(condition,),node)
            self.commands[branch].target=len(self.commands)
            yes=self._expression(node.body)
            temp=self._temp(yes.width)
            yes_move=self._append('MOVE',temp.name,(yes,),node,yes.width)
            jump=self._append('JUMP',node=node)
            self.commands[branch].alternate=len(self.commands)
            no=self._expression(node.orelse)
            if no.width!=yes.width:
                self.fail('CO.CFG_TERNARY_WIDTH',f'Ternary branches have different widths: {yes.width}, {no.width}.',node,'CO')
            self._append('MOVE',temp.name,(no,),node,yes.width)
            self.commands[jump].target=len(self.commands)
            return temp
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='mem_read':
            if self.mem_depth is None:self.fail('CO.MEMORY_UNDECLARED','mem_read requires CO memory: {depth, data_width}.',node,'CO')
            if len(node.args)!=1 or node.keywords:self.fail('CO.MEMORY_ARGUMENTS','mem_read(address) expects one argument.',node,'CO')
            addr=self._expression(node.args[0]);v=self._temp(self.mem_width)
            self._append('READ',v.name,(addr,),node,self.mem_width);return v
        self.fail('CO.CFG_EXPRESSION',f'Unsupported CFG expression {type(node).__name__}.',node,'CO')

    def _statement(self,stmt):
        if isinstance(stmt,(ast.Assign,ast.AnnAssign)):
            target=stmt.target if isinstance(stmt,ast.AnnAssign) else stmt.targets[0] if len(stmt.targets)==1 else None
            if not isinstance(target,ast.Name):self.fail('CO.CFG_ASSIGN','Only one simple named assignment is supported.',stmt,'CO')
            value=self._expression(stmt.value)
            width=(parse_type(stmt.annotation,self.issues,self.path).width if isinstance(stmt,ast.AnnAssign)
                   else self.locals.get(target.id,value.width))
            if isinstance(stmt,ast.AnnAssign) and parse_type(stmt.annotation,self.issues,self.path).signed:
                self.fail('CO.CFG_SIGNED','Transactional mode supports unsigned bitvectors only.',stmt,'CO')
            if target.id in self.inputs:self.fail('CO.CFG_INPUT_ASSIGN',f'Cannot overwrite input {target.id!r}.',stmt,'CO')
            if target.id in self.locals and value.width != width and not isinstance(stmt,ast.AnnAssign) and target.id not in self.typed:
                self.fail('CO.CFG_IMPLICIT_TRUNCATION',f'Assignment to {target.id!r} changes inferred value width from {width} to {value.width}; annotate the variable explicitly.',stmt,'CO')
            if target.id in self.locals and width!=self.locals[target.id]:
                self.fail('CO.CFG_RETYPE',f'Local {target.id!r} changes width from {self.locals[target.id]} to {width}.',stmt,'CO')
            self.locals[target.id]=width
            if isinstance(stmt,ast.AnnAssign):self.typed.add(target.id)
            self._append('MOVE',target.id,(value,),stmt,width)
        elif isinstance(stmt,ast.Expr) and isinstance(stmt.value,ast.Call) and isinstance(stmt.value.func,ast.Name) and stmt.value.func.id=='mem_write':
            n=stmt.value
            if self.mem_depth is None:self.fail('CO.MEMORY_UNDECLARED','mem_write requires declared memory.',n,'CO')
            if len(n.args)!=2 or n.keywords:self.fail('CO.MEMORY_ARGUMENTS','mem_write(address, value) expects two arguments.',n,'CO')
            a=self._expression(n.args[0]);v=self._expression(n.args[1]);self._append('WRITE',None,(a,v),n)
        elif isinstance(stmt,ast.Return):
            v=self._expression(stmt.value);self._append('RETURN',None,(v,),stmt)
        elif isinstance(stmt,ast.If):
            condition=self._expression(stmt.test)
            branch=self._append('BRANCH',None,(condition,),stmt)
            yes_at=len(self.commands)
            for item in stmt.body:self._statement(item)
            jump=self._append('JUMP',node=stmt) if self.commands[-1].kind!='RETURN' else None
            no_at=len(self.commands)
            for item in stmt.orelse:self._statement(item)
            end_at=len(self.commands)
            self.commands[branch].target=yes_at
            self.commands[branch].alternate=no_at if stmt.orelse else end_at
            if jump is not None:self.commands[jump].target=end_at
        elif isinstance(stmt,ast.Pass):pass
        elif isinstance(stmt,ast.For):
            if not isinstance(stmt.target,ast.Name) or stmt.orelse:
                self.fail('CO.CFG_FOR','Only constant range() loops without else are supported.',stmt,'CO')
            call=stmt.iter
            if not (isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='range'
                    and 1<=len(call.args)<=3 and not call.keywords
                    and all(isinstance(a,ast.Constant) and type(a.value)==int for a in call.args)):
                self.fail('CO.CFG_FOR','Loop range must have constant integer bounds.',stmt,'CO')
            try:indices=list(range(*(a.value for a in call.args)))
            except ValueError:self.fail('CO.CFG_FOR','Invalid range step.',stmt,'CO')
            if len(indices)>32:self.fail('CO.CFG_FOR_LIMIT','At most 32 static loop iterations supported.',stmt,'CO')
            width=max(1,max(indices,default=0).bit_length())
            for i in indices:
                if i<0:self.fail('CO.CFG_FOR_NEGATIVE','Negative loop indices unsupported.',stmt,'CO')
                if stmt.target.id in self.locals and self.locals[stmt.target.id]!=width:
                    # Explicitly reject unstable type inference rather than subtly shifting semantics.
                    self.fail('CO.CFG_FOR_TYPE','Loop index width changes; use a source-level explicit index register.',stmt,'CO')
                self.locals[stmt.target.id]=width
                self._append('MOVE',stmt.target.id,(Ref('',width,i),),stmt,width)
                for item in stmt.body:self._statement(item)
        else:self.fail('CO.CFG_STATEMENT',f'Unsupported CFG statement {type(stmt).__name__}.',stmt,'CO')

    def compile_source(self,source,path='<memory>',top=None)->DLS:
        self.path=path
        try:tree=ast.parse(source,filename=path)
        except SyntaxError as e:self.fail('SOURCE.SYNTAX',e.msg,e)
        funcs={f.name:f for f in tree.body if isinstance(f,ast.FunctionDef)}
        name=top or next(iter(funcs),'')
        if name not in funcs:self.fail('SOURCE.NO_TOP',f'No function named {name!r}.')
        f=funcs[name]
        if f.args.kwonlyargs or f.args.vararg or f.args.kwarg or f.args.defaults:
            self.fail('CO.CFG_SIGNATURE','Only positional, non-default inputs are supported.',f,'CO')
        for a in f.args.args:
            t=parse_type(a.annotation,self.issues,path)
            if t.signed or t.width>128:self.fail('CO.CFG_SIGNED','Only unsigned input types <=128 bits.',a,'CO')
            if a.arg in ('start','stall','reset') or a.arg.startswith('unit_ready_'):
                self.fail('CO.CFG_RESERVED',f'Input name {a.arg!r} reserved by scheduler.',a,'CO')
            self.inputs[a.arg]=t.width
        t=parse_type(f.returns,self.issues,path)
        if t.signed or t.width>128:self.fail('CO.CFG_SIGNED','Only unsigned return widths <=128 bits.',f,'CO')
        self.return_width=t.width
        sched=self.co.get('schedule') or {}
        memory=self.co.get('memory') or {}
        self.mem_depth=memory.get('depth')
        self.mem_width=memory.get('data_width')
        if self.mem_depth is not None:
            if type(self.mem_depth)!=int or not 1<=self.mem_depth<=32 or type(self.mem_width)!=int or not 1<=self.mem_width<=64:
                self.fail('CO.MEMORY_SPEC','On-chip memory requires integer depth 1..32 and data_width 1..64.',f,'CO')
        latencies=sched.get('latencies') or {}
        ready_types=sched.get('ready_types') or []
        if not isinstance(latencies,dict) or any(type(v)!=int or not 1<=v<=16 for v in latencies.values()):
            self.fail('CO.CFG_LATENCY','latencies must map operations to integer reservation cycles 1..16.',f,'CO')
        valid_kinds=set(self.KINDS.values())|set(self.COMPARISONS.values())|{'NOT','INV','NEG','BOOL_AND','BOOL_OR','READ','WRITE','MOVE','RETURN'}
        if any(k not in valid_kinds for k in latencies):self.fail('CO.CFG_LATENCY','Unknown operation in latency settings.',f,'CO')
        if not isinstance(ready_types,list) or any(v not in valid_kinds or not isinstance(v,str) for v in ready_types):
            self.fail('CO.CFG_READY','ready_types must be a list of supported operation kinds.',f,'CO')
        self.latencies=latencies;self.ready_types=set(ready_types)
        for statement in f.body:self._statement(statement)
        if not self.commands:self.fail('CO.CFG_EMPTY','Function contains no operations.',f,'CO')
        # Only *reachable* successors count: structured if/else lowering can
        # contain an unreachable join JUMP after an arm that already returns.
        n=len(self.commands);reached=set();pending=[0]
        while pending:
            i=pending.pop()
            if i in reached:continue
            if i==n:self.fail('CO.CFG_FALLTHROUGH','A reachable control-flow path leaves without returning.',f,'CO')
            if i<0 or i>n:self.fail('CO.CFG_BROKEN','Invalid control-flow target.',f,'CO')
            reached.add(i);c=self.commands[i]
            if c.kind=='BRANCH':edges=(c.target,c.alternate)
            elif c.kind=='JUMP':edges=(c.target,)
            elif c.kind=='RETURN':edges=()
            else:edges=(i+1,)
            if any(x is None for x in edges):self.fail('CO.CFG_BROKEN','Unresolved control-flow target.',f,'CO')
            pending.extend(edges)
        if len(reached)<n:
            removed=[i for i in range(n) if i not in reached]
            positions={old:new for new,old in enumerate(sorted(reached))}
            self.commands=[self.commands[i] for i in sorted(reached)]
            for c in self.commands:
                if c.target is not None:c.target=positions[c.target]
                if c.alternate is not None:c.alternate=positions[c.alternate]
            needed={r.name for c in self.commands for r in c.args if r.const is None}
            needed.update(c.dst for c in self.commands if c.dst)
            self.locals={k:v for k,v in self.locals.items() if k in needed}
            self.issues.add('CO.CFG_DEAD_CODE','WARNING','CO','transactional',
                f'Removed {len(removed)} unreachable CFG instruction(s) before hardware construction.',
                file=self.path,evidence={'unreachable_instruction_indices':removed},
                remedy='Inspect source branches and returns if the unreachable code was unexpected.')
        self.reachable=list(range(len(self.commands)))
        if not any(c.kind=='RETURN' for c in self.commands):self.fail('SOURCE.MISSING_RETURN','CFG has no return instruction.',f)
        for c in self.commands:c.latency=latencies.get(c.kind,1)
        self._validate_definite_assignment(f)
        return self._lower(source,name)

    def _validate_definite_assignment(self,f):
        # Forward *must-defined* analysis, path intersection rather than union.
        n=len(self.commands);incoming=[set() for _ in range(n)];seen=[False]*n
        incoming[0]=set(self.inputs);seen[0]=True
        changed=True
        while changed:
            changed=False
            for i,c in enumerate(self.commands):
                if not seen[i]:continue
                available=incoming[i]
                for ref in c.args:
                    if ref.const is None and ref.name not in available:
                        self.fail('CO.CFG_UNINITIALIZED',f'{ref.name!r} may be uninitialized on a control path.',f,'CO',
                                  {'instruction':i,'source_line':c.lineno})
                out=available|({c.dst} if c.dst else set())
                successors=((c.target,c.alternate) if c.kind=='BRANCH' else (c.target,) if c.kind=='JUMP' else
                            () if c.kind=='RETURN' else (i+1,))
                for j in successors:
                    if not seen[j]:incoming[j]=set(out);seen[j]=True;changed=True
                    else:
                        merged=incoming[j]&out
                        if merged!=incoming[j]:incoming[j]=merged;changed=True

    def _lower(self,source,name):
        b=LogicBuilder(name,{**self.inputs,'start':1,'stall':1,'reset':1,
                             **{f'unit_ready_{k.lower()}':1 for k in sorted(self.ready_types)}})
        def r(name,width):return Bus(tuple(f'${name}[{i}]' for i in range(width)))
        def bit(pin):return Bus((pin,))
        def and_(*bits):
            z='@1'
            for x in bits:z=b.gate('AND',z,x)
            return z
        def or_(*bits):
            z='@0'
            for x in bits:z=b.gate('OR',z,x)
            return z
        def not_(x):return b.gate('NOT',x)
        def mux(sel,x,y):return b.mux(bit(sel),x,y)
        def update(name,signal,enable):
            # Accumulate multiple mutually exclusive writers instead of letting
            # a later default-hold mux overwrite an earlier writer.
            previous=Bus(tuple(b.registers[name]['next']))
            b.registers[name]['next']=list(mux(enable,previous,signal).bits)
        b.registers['idle']={'next':['@0'],'init':1}
        b.registers['done']={'next':['@0'],'init':0}
        b.registers['fault']={'next':['@0'],'init':0}
        b.registers['output']={'next':list(r('output',self.return_width).bits),'init':0}
        for inp,width in self.inputs.items():b.registers['in_'+inp]={'next':list(r('in_'+inp,width).bits),'init':0}
        for var,width in self.locals.items():b.registers['var_'+var]={'next':list(r('var_'+var,width).bits),'init':0}
        if self.mem_depth is not None:
            for i in range(self.mem_depth):b.registers[f'mem_{i}']={'next':list(r(f'mem_{i}',self.mem_width).bits),'init':0}
        for i,c in enumerate(self.commands):
            for stage in range(c.latency):b.registers[f'pc_{i}_{stage}']={'next':['@0'],'init':0}
        inputs=b.inputs
        def operand(ref):
            if ref.const is not None:return b.const(ref.const,ref.width)
            if ref.name in self.inputs:return r('in_'+ref.name,ref.width)
            return r('var_'+ref.name,ref.width)
        no_stall=not_('stall[0]');no_reset=not_('reset[0]');accept=and_('$idle[0]','start[0]',no_stall,no_reset)
        for inp,width in self.inputs.items():update('in_'+inp,Bus(tuple(f'{inp}[{j}]' for j in range(width))),accept)
        outgoing={i:[] for i in range(len(self.commands))}
        # Build one logical resource per operation kind. The schedule reserves
        # that resource for one instruction at a time; subsequent operations
        # share its bit-gate network, not duplicated arithmetic macros.
        computed={};physical_units={};uses={}
        groups={}
        for i,c in enumerate(self.commands):
            if c.kind in set(self.KINDS.values())|set(self.COMPARISONS.values())|{'NOT','INV','NEG','BOOL_AND','BOOL_OR'}:
                groups.setdefault(c.kind,[]).append((i,c))
        for kind,entries in groups.items():
            physical_units[kind]=1;uses[kind]=len(entries)
            wa=max(x.args[0].width for _,x in entries)
            wb=max((x.args[1].width for _,x in entries) if len(entries[0][1].args)>1 else [1])
            a=b.const(0,wa);v=b.const(0,wb)
            for i,c in entries:
                sel=or_(*(f'$pc_{i}_{stage}[0]' for stage in range(c.latency)))
                a=mux(sel,a,b.extend(operand(c.args[0]),wa))
                if len(c.args)>1:v=mux(sel,v,b.extend(operand(c.args[1]),wb))
            b.origin=f'{self.path}:shared_{kind}'
            if kind=='ADD':result=b.add(a,v)
            elif kind=='SUB':result=b.sub(a,v)
            elif kind=='MUL':result=b.mul(a,v)
            elif kind in ('AND','OR','XOR'):result=b.binary_gate(kind,a,v)
            elif kind=='NOT':result=bit(not_(b.is_nonzero(a)))
            elif kind=='INV':result=b.unary('NOT',a)
            elif kind=='NEG':result=b.unary('NEG',a)
            elif kind.startswith('BOOL_'):
                op='AND' if kind=='BOOL_AND' else 'OR'
                result=bit(b.gate(op,b.is_nonzero(a),b.is_nonzero(v)))
            else:result=b.compare(kind,a,v)
            for i,c in entries:computed[i]=b.extend(result,c.width)
        def memory_addr(i,c):
            addr=operand(c.args[0]);required=max(1,(self.mem_depth-1).bit_length())
            valid=b.compare('LT',addr,b.const(self.mem_depth,max(len(addr),required+1))).bits[0]
            return addr,valid
        mem_info={i:memory_addr(i,c) for i,c in enumerate(self.commands) if c.kind in ('READ','WRITE')}
        # Ready backpressure for selected operation kinds and illegal-address fault edge.
        finish={};invalid={};active={}
        for i,c in enumerate(self.commands):
            state=f'$pc_{i}_{c.latency-1}[0]'
            ready=('unit_ready_'+c.kind.lower()+'[0]' if c.kind in self.ready_types else '@1')
            valid=mem_info[i][1] if i in mem_info else '@1'
            finish[i]=and_(state,no_stall,no_reset,ready,valid)
            invalid[i]=and_(state,no_stall,no_reset,ready,not_(valid)) if i in mem_info else '@0'
            active[i]=f'$pc_{i}_0[0]'
        success_edges={i:[] for i in range(len(self.commands))}
        go_idle=[];go_fault=[];returns=[]
        for i,c in enumerate(self.commands):
            if c.kind=='RETURN':
                go_idle.append(finish[i]);returns.append(i)
            elif c.kind=='BRANCH':
                test=b.is_nonzero(operand(c.args[0]));
                success_edges[c.target].append(and_(finish[i],test))
                success_edges[c.alternate].append(and_(finish[i],not_(test)))
            elif c.kind=='JUMP':success_edges[c.target].append(finish[i])
            else:success_edges[i+1].append(finish[i])
            if invalid[i]!='@0':go_fault.append(invalid[i]);go_idle.append(invalid[i])
        stalled_done=and_('$done[0]','stall[0]')
        b.registers['done']['next']=[or_(stalled_done,*go_idle)]
        b.registers['idle']['next']=[or_(and_('$idle[0]',not_(accept)),*go_idle)]
        b.registers['fault']['next']=[or_(and_('$fault[0]',not_(accept)),*go_fault)]
        for i,c in enumerate(self.commands):
            for stage in range(c.latency):
                state=f'$pc_{i}_{stage}[0]'
                if stage==0:
                    arrival=or_(*(success_edges[i]+([accept] if i==0 else [])))
                    hold=and_(state,'stall[0]')
                    if c.latency==1 and c.kind in self.ready_types:
                        hold=or_(hold,and_(state,no_stall,not_(f'unit_ready_{c.kind.lower()}[0]')))
                else:
                    arrival=and_(f'$pc_{i}_{stage-1}[0]',no_stall)
                    if stage-1==0 and c.latency==2: pass
                    hold=and_(state,'stall[0]')
                    if stage==c.latency-1 and c.kind in self.ready_types:
                        hold=or_(hold,and_(state,no_stall,not_(f'unit_ready_{c.kind.lower()}[0]')))
                # For a held multi-cycle finishing state, stall must not advance another stage.
                if stage<c.latency-1 and c.latency>1:
                    arrival=and_(f'$pc_{i}_{stage-1}[0]',no_stall) if stage else arrival
                b.registers[f'pc_{i}_{stage}']['next']=[or_(arrival,hold)]
        for i,c in enumerate(self.commands):
            if c.dst:
                if c.kind=='MOVE':data_bus=b.extend(operand(c.args[0]),c.width)
                elif c.kind=='READ':
                    addr,_=mem_info[i]
                    data_bus=b.const(0,self.mem_width)
                    for j in reversed(range(self.mem_depth)):
                        eq=b.compare('EQ',addr,b.const(j,max(len(addr),max(1,(self.mem_depth-1).bit_length())))).bits[0]
                        data_bus=mux(eq,data_bus,r(f'mem_{j}',self.mem_width))
                else:data_bus=computed[i]
                update('var_'+c.dst,data_bus,finish[i])
            if c.kind=='WRITE':
                addr,_=mem_info[i];value=b.extend(operand(c.args[1]),self.mem_width)
                for j in range(self.mem_depth):
                    eq=b.compare('EQ',addr,b.const(j,max(len(addr),max(1,(self.mem_depth-1).bit_length())))).bits[0]
                    update(f'mem_{j}',value,and_(finish[i],eq))
            if c.kind=='RETURN':update('output',b.extend(operand(c.args[0]),self.return_width),finish[i])
        # Synchronous active-high RESET dominates every register update,
        # including stalls, controller phases, scratchpad and fault state.
        for reg_name,spec in b.registers.items():
            width=len(spec['next'])
            spec['next']=list(mux('reset[0]',Bus(tuple(spec['next'])),
                                  b.const(spec.get('init',0),width)).bits)
        outs={'result':list(r('output',self.return_width).bits),'ready':['$idle[0]'],
              'done':['$done[0]'],'fault':['$fault[0]']}
        # Observable arbitration/request state for downstream integration and
        # waveform inspection; ready is a backpressure input, not a hidden fallback.
        for kind in sorted(self.ready_types):
            states=[f'$pc_{i}_{j}[0]' for i,c in enumerate(self.commands) if c.kind==kind for j in range(c.latency)]
            outs['unit_active_'+kind.lower()]=[or_(*states)]
        meta={'top':name,'source':self.path,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
              'return_width':self.return_width,'return_signed':False,'strategies':b.strategies,
              'schedule':{'mode':'transactional','instructions':[{**asdict(c),'args':[asdict(x) for x in c.args]} for c in self.commands],
                          'instruction_count':len(self.commands),'reachable_instructions':self.reachable,'resource_bindings':
                          [{'instruction':i,'kind':c.kind,'unit':c.kind,'source_line':c.lineno,'latency':c.latency}
                           for i,c in enumerate(self.commands) if c.kind in physical_units],
                          'physical_units':physical_units,'operator_uses':uses,
                          'memory':{'depth':self.mem_depth,'data_width':self.mem_width} if self.mem_depth is not None else None,
                          'ready_types':sorted(self.ready_types),
                          'protocol':'Synchronous active-high RESET initializes controller and memory. START accepted when READY=1 and STALL=0 and RESET=0. DONE is a clocked pulse, held on STALL. FAULT marks invalid memory address. Physical operator timing NOT characterized.',
                          'latency_semantics':'Reservation cycles; actual logic remains combinational inside shared units.',
                          'overlapping_transactions':False},'compiler':'chipcompiler transactional v0.7'}
        design=DLS(name,b.inputs,outs,b.nodes,b.registers,meta)
        design.validate()
        return design
