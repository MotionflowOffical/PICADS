"""Procedural bit-vector to gate-network compiler. No adder/multiplier macro required.

Supported Python is a *static hardware subset*, never executed as arbitrary Python.
Unsupported constructs are errors. Arithmetic is generated as connected primitive gates.
"""
from __future__ import annotations
import ast, re, hashlib
from dataclasses import dataclass
from typing import Any
from pathlib import Path
from .ir import Bus, Node, DLS
from .diagnostics import IssueCollector, DiagnosticException

TYPES=re.compile(r'^([us])(\d+)$')

@dataclass(frozen=True)
class HWType:
    width: int
    signed: bool=False

def parse_type(annotation: ast.expr | None, issues: IssueCollector, source: str) -> HWType:
    name=annotation.id if isinstance(annotation, ast.Name) else None
    if name=='bool': return HWType(1)
    match=TYPES.fullmatch(name or '')
    if match:
        width=int(match.group(2))
        if 1 <= width <= 4096: return HWType(width,match.group(1)=='s')
    issue=issues.add('SOURCE.INVALID_TYPE','ERROR','SOURCE','parse',f'Unsupported bit-vector type: {name!r}',
        file=source,line=getattr(annotation,'lineno',None),
        remedy='Use bool, u1..u4096 or s1..s4096 annotations.')
    raise DiagnosticException(issue)

class LogicBuilder:
    def __init__(self, name: str, inputs:dict[str,int], arch:dict[str,Any]|None=None):
        self.name=name; self.inputs=inputs; self.arch=arch or {}
        self.nodes:list[Node]=[]; self.cache:dict[tuple,str]={}; self.next_id=0
        self.registers:dict[str,dict]={}; self.origin=''
        self.strategies:dict[str,int]={}; self.generator_notes=[]
        self.source_ops=[]
        self.instances=[];self.submodules={}


    def gate(self, op:str,*pins:str) -> str:
        if op in ('AND','OR','XOR'):
            if pins[0]==pins[1]: return '@0' if op=='XOR' else pins[0]
            a,b=pins
            if op=='AND':
                if '@0' in pins:return '@0'
                if a=='@1':return b
                if b=='@1':return a
            if op=='OR':
                if '@1' in pins:return '@1'
                if a=='@0':return b
                if b=='@0':return a
            if op=='XOR':
                if a=='@0':return b
                if b=='@0':return a
            pins=tuple(sorted(pins))
        if op=='NOT':
            if pins[0]=='@0':return '@1'
            if pins[0]=='@1':return '@0'
        if op=='MUX':
            s,a,b=pins
            if a==b:return a
            if s=='@0':return a
            if s=='@1':return b
        key=(op,*pins)
        if key in self.cache:return self.cache[key]
        self.next_id+=1
        name=f'g{self.next_id:06d}'
        self.nodes.append(Node(name,op,list(pins),self.origin))
        self.cache[key]=name
        return name

    def const(self, v:int, width:int, signed=False) -> Bus:
        mask=(1<<width)-1
        value=v&mask
        return Bus(tuple('@1' if (value>>i)&1 else '@0' for i in range(width)),signed)

    def extend(self,a:Bus,n:int, signed:bool|None=None)->Bus:
        signed=a.signed if signed is None else signed
        if len(a)>=n:return Bus(a.bits[:n],signed)
        pad=a.bits[-1] if a.signed and signed else '@0'
        return Bus(a.bits+(pad,)*(n-len(a)),signed)

    def unary(self,op:str,a:Bus)->Bus:
        if op=='NOT':return Bus(tuple(self.gate('NOT',x) for x in a.bits),a.signed)
        if op=='NEG':
            inverted=self.unary('NOT',a)
            return self.add(inverted,self.const(1,len(a)),forced_width=len(a))
        raise ValueError(op)

    def binary_gate(self,op:str,a:Bus,b:Bus)->Bus:
        n=max(len(a),len(b)); a=self.extend(a,n);b=self.extend(b,n)
        return Bus(tuple(self.gate(op,x,y) for x,y in zip(a.bits,b.bits)),a.signed and b.signed)

    def add(self,a:Bus,b:Bus,forced_width:int|None=None)->Bus:
        n=forced_width if forced_width is not None else max(len(a),len(b))+1
        signed=a.signed and b.signed
        aa=self.extend(a,n,signed); bb=self.extend(b,n,signed)
        strategy=self.arch.get('adder','auto')
        if strategy not in ('auto','ripple','prefix'):raise ValueError('Unknown CO adder strategy')
        if strategy=='auto': strategy='prefix' if n>=12 else 'ripple'
        self.strategies['adder.'+strategy]=self.strategies.get('adder.'+strategy,0)+1
        if strategy=='ripple':
            carry='@0';result=[]
            for ai,bi in zip(aa.bits,bb.bits):
                p=self.gate('XOR',ai,bi)
                result.append(self.gate('XOR',p,carry))
                carry=self.gate('OR',self.gate('AND',ai,bi),self.gate('AND',p,carry))
            return Bus(tuple(result),signed)
        # Parallel prefix carry computation using generate/propagate intervals.
        p=[self.gate('XOR',x,y) for x,y in zip(aa.bits,bb.bits)]
        g=[self.gate('AND',x,y) for x,y in zip(aa.bits,bb.bits)]
        levels=0
        while 1<<levels<n:
            dist=1<<levels; oldp=p[:];oldg=g[:]
            for i in range(dist,n):
                g[i]=self.gate('OR',oldg[i],self.gate('AND',oldp[i],oldg[i-dist]))
                p[i]=self.gate('AND',oldp[i],oldp[i-dist])
            levels+=1
        carry=['@0']+g[:-1]
        bits=[self.gate('XOR',self.gate('XOR',ai,bi),c) for ai,bi,c in zip(aa.bits,bb.bits,carry)]
        return Bus(tuple(bits),signed)

    def sub(self,a:Bus,b:Bus)->Bus:
        n=max(len(a),len(b))
        return self.add(self.extend(a,n),self.unary('NEG',self.extend(b,n)),forced_width=n)

    def mul(self,a:Bus,b:Bus)->Bus:
        # Full precision unsigned multiplication; signed values encoded in two's complement.
        n=len(a)+len(b); result=self.const(0,n)
        signed=a.signed or b.signed
        aa=self.extend(a,n,signed=a.signed); bb=self.extend(b,n,signed=b.signed)
        rows=[]
        for i in range(len(b)):
            row=['@0']*n
            for j in range(n-i): row[i+j]=self.gate('AND',aa.bits[j],b.bits[i])
            rows.append(Bus(tuple(row)))
        if b.signed:
            # negative highest-weight multiplier bit contributes subtraction.
            positive=rows[:-1]
            neg=rows[-1]
            while len(positive)>1:
                positive=[self.add(positive[j],positive[j+1],forced_width=n) if j+1<len(positive) else positive[j]
                          for j in range(0,len(positive),2)]
            result=positive[0] if positive else self.const(0,n)
            result=self.sub(result,neg)
        else:
            while len(rows)>1:
                rows=[self.add(rows[j],rows[j+1],forced_width=n) if j+1<len(rows) else rows[j]
                      for j in range(0,len(rows),2)]
            result=rows[0] if rows else result
        self.strategies['multiplier.partial_products']=self.strategies.get('multiplier.partial_products',0)+1
        return Bus(result.bits,signed)

    def shift(self,a:Bus, count:int, right=False)->Bus:
        if count < 0 or count > 4096: raise ValueError('Shift count outside supported range')
        if right:
            padding=a.bits[-1] if a.signed else '@0'
            return Bus(tuple(a.bits[i+count] if i+count<len(a) else padding for i in range(len(a))),a.signed)
        return Bus(('@0',)*count+a.bits,a.signed)

    def is_nonzero(self, a:Bus)->str:
        v='@0'
        for b in a.bits:v=self.gate('OR',v,b)
        return v

    def compare(self,op:str,a:Bus,b:Bus)->Bus:
        n=max(len(a),len(b)); signed=a.signed and b.signed
        aa=self.extend(a,n,signed);bb=self.extend(b,n,signed)
        if op in ('EQ','NE'):
            equal='@1'
            for x,y in zip(aa.bits,bb.bits):equal=self.gate('AND',equal,self.gate('NOT',self.gate('XOR',x,y)))
            return Bus((equal if op=='EQ' else self.gate('NOT',equal),))
        lt='@0'; eq='@1'
        for x,y in zip(reversed(aa.bits),reversed(bb.bits)):
            less_here=self.gate('AND',self.gate('NOT',x),y)
            lt=self.gate('OR',lt,self.gate('AND',eq,less_here))
            eq=self.gate('AND',eq,self.gate('NOT',self.gate('XOR',x,y)))
        if signed:
            ax=aa.bits[-1]; bx=bb.bits[-1]
            different=self.gate('XOR',ax,bx)
            lt=self.gate('MUX',different,lt,ax)
        if op in ('GT','GE'):
            reverse=self.compare('LT',b,a).bits[0]
            return Bus((reverse if op=='GT' else self.gate('NOT',lt),))
        return Bus((lt if op=='LT' else self.gate('OR',lt,eq),))

    def mux(self,sel:Bus,a:Bus,b:Bus)->Bus:
        n=max(len(a),len(b)); a=self.extend(a,n);b=self.extend(b,n)
        s=self.is_nonzero(sel)
        return Bus(tuple(self.gate('MUX',s,x,y) for x,y in zip(a.bits,b.bits)),a.signed and b.signed)

    def reg(self,name:str,nxt:Bus,init:int=0,enable:Bus|None=None,reset:Bus|None=None)->Bus:
        if name in self.registers:
            raise ValueError(f'Duplicate register definition {name}')
        old=Bus(tuple(f'${name}[{i}]' for i in range(len(nxt))),nxt.signed)
        target=nxt
        if enable is not None:
            target=self.mux(enable,old,target)
        if reset is not None:
            target=self.mux(reset,target,self.const(init,len(nxt),nxt.signed))
        self.registers[name]={'next':list(target.bits),'init':int(init),
                              'mode':'sync_reset_enable' if reset is not None and enable is not None
                                     else 'sync_reset' if reset is not None
                                     else 'enable' if enable is not None else 'always'}
        return old

class HardwareCompiler:
    def __init__(self, issues:IssueCollector | None=None, co:dict|None=None, ancestry:tuple[str,...]=()):
        self.ancestry=tuple(ancestry)
        self.issues=issues if issues is not None else IssueCollector()
        self.co=co or {}; self.functions={};self.path='';self.stack=[];self.builder=None

    def fail(self, code:str, text:str, node:ast.AST|None=None, remedy='', cause=''):
        issue=self.issues.add(code,'ERROR','SOURCE','generate',text,file=self.path,
            line=getattr(node,'lineno',None), column=getattr(node,'col_offset',None),
            cause=cause,remedy=remedy)
        raise DiagnosticException(issue)

    def compile_source(self, text:str, path:str='<memory>', top:str|None=None)->DLS:
        self.path=path;self.source_text=text
        try:tree=ast.parse(text,filename=path)
        except SyntaxError as e:
            self.fail('SOURCE.SYNTAX',e.msg,remedy='Fix syntax in the reported line.')
        self.functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        unsupported=[n for n in tree.body if not isinstance(n,(ast.FunctionDef,ast.Expr)) or
                     (isinstance(n,ast.Expr) and not (isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)))]
        if unsupported:self.fail('SOURCE.TOP_LEVEL','Only function definitions and docstrings are supported',unsupported[0])
        if not self.functions:self.fail('SOURCE.NO_FUNCTION','Source contains no function definitions')
        name=top or next(iter(self.functions))
        if name not in self.functions:self.fail('SOURCE.NO_TOP',f'Top function {name!r} not found',remedy='Set top to an existing function in .mcd')
        if name in self.ancestry:
            self.fail('SOURCE.RECURSION',f'Recursive hardware hierarchy: {" -> ".join((*self.ancestry,name))}',
                      self.functions[name],remedy='Remove recursive helper calls or use a bounded explicit iterative circuit.')
        if len(self.ancestry)>=25:
            self.fail('SOURCE.HIERARCHY_DEPTH','Maximum hierarchical helper depth (25) exceeded.',self.functions[name])
        f=self.functions[name];inputs={};env={}
        for a in f.args.args:
            ty=parse_type(a.annotation,self.issues,path)
            if a.arg in inputs:self.fail('SOURCE.DUPLICATE_INPUT',f'Duplicate input {a.arg}',a)
            inputs[a.arg]=ty.width
            env[a.arg]=Bus(tuple(f'{a.arg}[{i}]' for i in range(ty.width)),ty.signed)
        output_type=parse_type(f.returns,self.issues,path)
        try:
            arch=self.co.get('architecture',{})
            self.builder=LogicBuilder(name,inputs,arch)
            result=self._block(f.body,env)
            if result is None:self.fail('SOURCE.MISSING_RETURN',f'Function {name} has no return on some path',f)
            result=self.builder.extend(result,output_type.width,output_type.signed)
            allocation=self.co.get('allocation',{}) or {}
            counts={}
            for op in self.builder.source_ops:
                counts[op['kind']]=counts.get(op['kind'],0)+1
            for kind,limit in allocation.get('max_instances',{}).items():
                if counts.get(kind,0)>limit:
                    issue=self.issues.add('CO.RESOURCE_LIMIT','ERROR','CO','allocate',
                        f'{kind} needs {counts[kind]} separate combinational operators but maximum is {limit}.',
                        file=self.path,cause='The required operations could not be safely merged by the implemented sharing rules.',
                        remedy='Increase allocation.max_instances, revise independent operations, or allow compatible branch sharing.',
                        evidence={'kind':kind,'count':counts[kind],'limit':limit,'operations':self.builder.source_ops})
                    raise DiagnosticException(issue)
            dls=DLS(name,inputs,{'result':list(result.bits)},self.builder.nodes,
                    self.builder.registers,{'source':path,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
                    'top':name,'return_width':output_type.width,'return_signed':output_type.signed,
                    'strategies':self.builder.strategies,'operators':self.builder.source_ops,'operator_counts':counts,'co':self.co,'compiler':'chipcompiler 0.5'},
                    instances=self.builder.instances,submodules=self.builder.submodules)
            if dls.requires_clock() and 'clk' in inputs:
                self.fail('MCD.CLOCK_PORT_COLLISION',
                          "clk conflicts with the implicit clock required by the sequential hierarchy.", f,
                          remedy="Rename the data input; the hierarchy's rising-edge clock is supplied separately.",
                          cause='An instantiated helper contains state, so the parent must expose an implicit clock.')
            dls.validate()
            return dls
        except DiagnosticException:raise
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as e:
            self.fail('SOURCE.UNSUPPORTED',str(e),f,remedy='Use documented hardware subset; inspect source line and types.')

    def _has_stateful_call(self, node: ast.AST, seen: frozenset[str] = frozenset()) -> bool:
        """Reject implicitly clocked state that executes under a branch.

        Speculatively materializing both conditional branches is correct for
        combinational logic but is NOT equivalent for registers in a branch.
        A transitive helper call containing reg() is stateful even when the
        immediate helper's body has no register of its own.
        """
        for item in ast.walk(node):
            if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Name):
                continue
            name = item.func.id
            if name == 'reg':
                return True
            if name in self.functions and name not in seen:
                if self._has_stateful_call(self.functions[name], seen | {name}):
                    return True
        return False

    def _reject_conditional_state(self, ast_node: ast.AST, branches: list[ast.AST]):
        if any(self._has_stateful_call(branch) for branch in branches):
            self.fail('SOURCE.CONDITIONAL_STATE',
                      'A register or stateful helper appears under a conditional execution path.', ast_node,
                      cause='Both combinational branches are constructed and evaluated; conditional register updates cannot be inferred from the current frontend.',
                      remedy='Move the register outside the branch and select its next value explicitly, or implement the behavior with a supported sequential scheduler.')

    def _block(self, statements:list[ast.stmt], env:dict[str,Bus])->Bus|None:
        for index,s in enumerate(statements):
            self.builder.origin=f'{self.path}:{s.lineno}'
            if isinstance(s,ast.Return):return self._expr(s.value,env)
            if isinstance(s,(ast.Assign,ast.AnnAssign)):
                targets=s.targets if isinstance(s,ast.Assign) else [s.target]
                value=self._expr(s.value,env)
                if isinstance(s,ast.AnnAssign):
                    ty=parse_type(s.annotation,self.issues,self.path)
                    value=self.builder.extend(value,ty.width,ty.signed)
                for target in targets:
                    if not isinstance(target,ast.Name):self.fail('SOURCE.ASSIGN_TARGET','Only simple signal names can be assigned.',target)
                    env[target.id]=value
                continue
            if isinstance(s,ast.If):
                self._reject_conditional_state(s, [*s.body, *s.orelse])
                alternative=s.orelse if s.orelse else statements[index+1:]
                if len(s.body)==1 and isinstance(s.body[0],ast.Return) and len(alternative)==1 and isinstance(alternative[0],ast.Return):
                    selected=self._share_binary(s.test,s.body[0].value,alternative[0].value,env,s)
                    if selected is not None:return selected
                sel=self._expr(s.test,env)
                yes=self._block(s.body+statements[index+1:],env.copy())
                no=self._block(s.orelse+statements[index+1:],env.copy())
                if yes is None or no is None:
                    self.fail('SOURCE.PATH_RETURN','Every conditional path must return a value.',s)
                return self.builder.mux(sel,no,yes)
            if isinstance(s,ast.For):
                if not isinstance(s.target,ast.Name) or not isinstance(s.iter,ast.Call) or not isinstance(s.iter.func,ast.Name) or s.iter.func.id!='range':
                    self.fail('SOURCE.UNBOUNDED_LOOP','Only statically bounded for ... in range(...) loops are supported',s)
                args=[]
                for a in s.iter.args:
                    if not isinstance(a,ast.Constant) or not isinstance(a.value,int):self.fail('SOURCE.NONCONSTANT_RANGE','range arguments must be integer literals',a)
                    args.append(a.value)
                if len(args) not in (1,2,3):self.fail('SOURCE.RANGE_ARITY','range expects 1-3 literals',s)
                values=list(range(*args))
                if len(values)>1024:self.fail('SOURCE.LOOP_LIMIT','Loop unroll limit is 1024 iterations',s)
                for v in values:
                    env[s.target.id]=self.builder.const(v,max(1,v.bit_length()+int(v<0)),v<0)
                    result=self._block(s.body,env)
                    if result is not None:return result
                continue
            if isinstance(s,ast.Pass):continue
            self.fail('SOURCE.STATEMENT',f'Unsupported statement: {type(s).__name__}',s)
        return None

    @staticmethod
    def _operator_kind(op):
        return next((value for cls,value in ((ast.Add,'ADD'),(ast.Sub,'SUB'),(ast.Mult,'MUL'),
                        (ast.BitAnd,'AND'),(ast.BitOr,'OR'),(ast.BitXor,'XOR')) if isinstance(op,cls)),None)

    def _share_binary(self, condition, yes, no, env, node):
        """Real combinational resource-sharing rewrite: MUX operands before one operator.

        Only safe when *both* branches contain the same binary operation with
        exactly compatible operand types. In particular no helper/reg calls are
        moved across the guard. There is no speculative sequential scheduling.
        """
        policy=(self.co.get('allocation',{}) or {}).get('sharing','auto')
        if policy=='off' or not isinstance(yes,ast.BinOp) or not isinstance(no,ast.BinOp):return None
        kind=self._operator_kind(yes.op)
        if kind is None or kind!=self._operator_kind(no.op):return None
        safe=(ast.Name,ast.Constant)
        if not all(isinstance(x,safe) for x in (yes.left,yes.right,no.left,no.right)):return None
        xa=self._expr(yes.left,env);xb=self._expr(yes.right,env)
        ya=self._expr(no.left,env);yb=self._expr(no.right,env)
        if (len(xa),xa.signed,len(xb),xb.signed)!=(len(ya),ya.signed,len(yb),yb.signed):return None
        if policy=='auto' and kind in ('ADD','SUB') and max(len(xa),len(xb))<8:return None
        s=self._expr(condition,env)
        a=self.builder.mux(s,ya,xa)
        b=self.builder.mux(s,yb,xb)
        op={'ADD':self.builder.add,'SUB':self.builder.sub,'MUL':self.builder.mul,
            'AND':lambda a,b:self.builder.binary_gate('AND',a,b),
            'OR':lambda a,b:self.builder.binary_gate('OR',a,b),
            'XOR':lambda a,b:self.builder.binary_gate('XOR',a,b)}[kind]
        self.builder.source_ops.append({'kind':kind,'line':getattr(node,'lineno',None),
             'width_a':len(a),'width_b':len(b),'binding':'shared-conditional',
             'selection':ast.unparse(condition)})
        self.builder.strategies['shared.'+kind]=self.builder.strategies.get('shared.'+kind,0)+1
        return op(a,b)

    def _module_instance(self,fn:str,n:ast.Call,env:dict[str,Bus])->Bus:
        """Allocate an independent hierarchical submodule instance.

        Sequential children share the implicit parent clock. Each instance has
        independent state and is checked against the source-reference model.
        """
        if fn in self.stack or len(self.stack)>=25:
            self.fail('SOURCE.RECURSION',f'Recursive helper call to {fn}',n)
        f=self.functions[fn]
        if len(n.args)!=len(f.args.args):
            self.fail('SOURCE.FUNCTION_ARITY',f'{fn} expects {len(f.args.args)} arguments, got {len(n.args)}',n)
        bound={}
        for arg,value_ast in zip(f.args.args,n.args):
            ty=parse_type(arg.annotation,self.issues,self.path)
            bound[arg.arg]=self.builder.extend(self._expr(value_ast,env),ty.width,ty.signed)
        if fn not in self.builder.submodules:
            # Preserve nested hierarchy, but prevent cross-function cycles.
            child=HardwareCompiler(self.issues,self.co,
                ancestry=(*self.ancestry,self.builder.name)).compile_source(
                self.source_text,self.path,fn)
            self.builder.submodules[fn]=child
        child=self.builder.submodules[fn]
        if set(bound)!=set(child.inputs):
            self.fail('MCD.INTERFACE',f'Helper {fn} input ports differ from their compiled signature',n)
        inst_name=f'u_{len(self.builder.instances):06d}'
        output_width=len(child.outputs['result'])
        names=[f'{inst_name}_result_{i}' for i in range(output_width)]
        self.builder.instances.append({
            'name':inst_name,'module':fn,'at':len(self.builder.nodes),
            'inputs':{key:list(b.bits) for key,b in bound.items()},'outputs':{'result':names},
            'source_location':f'{self.path}:{n.lineno}'})
        return Bus(tuple(names),bool(child.metadata.get('return_signed',False)))

    def _expr(self,n:ast.expr,env:dict[str,Bus])->Bus:
        b=self.builder
        b.origin=f'{self.path}:{getattr(n,"lineno",0)}'
        if isinstance(n,ast.Name):
            if n.id not in env:self.fail('SOURCE.UNDEFINED_SYMBOL',f'Unknown variable {n.id!r}',n,remedy='Declare as input or assign before use.')
            return env[n.id]
        if isinstance(n,ast.Constant):
            if isinstance(n.value,bool):return b.const(int(n.value),1)
            if isinstance(n.value,int):return b.const(n.value,max(1,n.value.bit_length()+int(n.value<0)),n.value<0)
            self.fail('SOURCE.CONSTANT','Only integer and Boolean constants are supported',n)
        if isinstance(n,ast.UnaryOp):
            x=self._expr(n.operand,env)
            if isinstance(n.op,ast.Invert):return b.unary('NOT',x)
            if isinstance(n.op,ast.USub):return b.unary('NEG',x)
            if isinstance(n.op,ast.Not):return Bus((b.gate('NOT',b.is_nonzero(x)),))
            self.fail('SOURCE.UNARY_OP','Unsupported unary operation',n)
        if isinstance(n,ast.BinOp):
            x=self._expr(n.left,env); y=self._expr(n.right,env)
            op=n.op
            kind=self._operator_kind(op)
            if kind:
                b.source_ops.append({'kind':kind,'line':getattr(n,'lineno',None),
                                     'width_a':len(x),'width_b':len(y),'binding':'generated'})
            if isinstance(op,ast.Add):return b.add(x,y)
            if isinstance(op,ast.Sub):return b.sub(x,y)
            if isinstance(op,ast.Mult):return b.mul(x,y)
            if isinstance(op,ast.BitAnd):return b.binary_gate('AND',x,y)
            if isinstance(op,ast.BitOr):return b.binary_gate('OR',x,y)
            if isinstance(op,ast.BitXor):return b.binary_gate('XOR',x,y)
            if isinstance(op,(ast.LShift,ast.RShift)):
                if not isinstance(n.right,ast.Constant) or not isinstance(n.right.value,int):
                    self.fail('SOURCE.VARIABLE_SHIFT','Only constant shifts are supported by this frontend',n)
                return b.shift(x,n.right.value,isinstance(op,ast.RShift))
            self.fail('SOURCE.BINARY_OP',f'Unsupported binary operator: {type(op).__name__}',n)
        if isinstance(n,ast.Compare):
            if len(n.ops)!=1:self.fail('SOURCE.CHAIN_COMPARISON','Chained comparison not supported',n)
            opmap={ast.Eq:'EQ',ast.NotEq:'NE',ast.Lt:'LT',ast.LtE:'LE',ast.Gt:'GT',ast.GtE:'GE'}
            op=next((text for typ,text in opmap.items() if isinstance(n.ops[0],typ)),None)
            if op is None:self.fail('SOURCE.COMPARE_OP','Unsupported comparison',n)
            return b.compare(op,self._expr(n.left,env),self._expr(n.comparators[0],env))
        if isinstance(n,ast.IfExp):
            self._reject_conditional_state(n, [n.body, n.orelse])
            shared=self._share_binary(n.test,n.body,n.orelse,env,n)
            if shared is not None:return shared
            return b.mux(self._expr(n.test,env),self._expr(n.orelse,env),self._expr(n.body,env))
        if isinstance(n,ast.BoolOp):
            if any(self._has_stateful_call(term) for term in n.values[1:]):
                self.fail('SOURCE.SHORTCIRCUIT_STATE',
                          'Stateful hardware call in a short-circuit Boolean operand is not safely supported.', n,
                          cause='Gate-level Boolean lowering evaluates all operands, unlike Python short-circuit control flow.',
                          remedy='Compute a pure Boolean selection first and drive the next register value explicitly.')
            op='AND' if isinstance(n.op,ast.And) else 'OR'
            xs=[b.is_nonzero(self._expr(v,env)) for v in n.values]
            acc=xs[0]
            for v in xs[1:]:acc=b.gate(op,acc,v)
            return Bus((acc,))
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name):
            fn=n.func.id
            if fn=='reg':
                if len(n.args)!=2 or not isinstance(n.args[0],ast.Constant) or not isinstance(n.args[0].value,str):
                    self.fail('SOURCE.REG_SIGNATURE','reg("name", next_value, init=0) requires literal name and signal',n)
                init=0; options={}
                for kw in n.keywords:
                    if kw.arg=='init':
                        if not isinstance(kw.value,ast.Constant) or type(kw.value.value)!=int:
                            self.fail('SOURCE.REG_INIT','reg init must be an integer literal',kw.value)
                        init=kw.value.value
                    elif kw.arg in ('enable','reset'):
                        options[kw.arg]=self._expr(kw.value,env)
                    else:
                        self.fail('SOURCE.REG_KEYWORD',
                                  f'Unknown reg keyword {kw.arg!r}; supported: init, enable, reset.',n)
                reg_name=n.args[0].value
                if not isinstance(reg_name,str) or not reg_name.isidentifier():
                    self.fail('SOURCE.REG_NAME','Register name must be a legal identifier.',n,
                              remedy='Use a string such as "counter" or "accumulator".')
                if reg_name in b.registers:
                    self.fail('SOURCE.REG_DUPLICATE',f'Register {reg_name!r} has multiple definitions.',n,
                              cause='Two hardware register declarations use the same name within one module.',
                              remedy='Assign each register a unique name, or reuse its existing output.')
                return b.reg(reg_name,self._expr(n.args[1],env),init,**options)
            if fn in self.functions:
                if n.keywords:self.fail('SOURCE.FUNCTION_KEYWORDS','Hardware helper functions do not accept keyword arguments.',n)
                if (self.co.get('modules') or {}).get('hierarchy','flatten')=='preserve':
                    return self._module_instance(fn,n,env)
                if fn in self.stack or len(self.stack)>=25:
                    self.fail('SOURCE.RECURSION',f'Recursive or overly deep helper call to {fn}',n)
                f=self.functions[fn]
                if len(n.args)!=len(f.args.args):
                    self.fail('SOURCE.FUNCTION_ARITY',f'{fn} expects {len(f.args.args)} arguments, got {len(n.args)}',n)
                inputs=[self._expr(arg,env) for arg in n.args]
                child={}
                for arg,value in zip(f.args.args,inputs):
                    ty=parse_type(arg.annotation,self.issues,self.path)
                    child[arg.arg]=b.extend(value,ty.width,ty.signed)
                self.stack.append(fn)
                try:output=self._block(f.body,child)
                finally:self.stack.pop()
                if output is None:self.fail('SOURCE.HELPER_RETURN',f'Helper {fn} has no return',f)
                ty=parse_type(f.returns,self.issues,self.path)
                return b.extend(output,ty.width,ty.signed)
            self.fail('SOURCE.CALL_UNSUPPORTED',f'Call {fn!r} not supported in hardware functions',n,
                      remedy='Inline pure fixed-width expressions; arbitrary Python calls cannot be synthesized.')
        self.fail('SOURCE.EXPRESSION',f'Unsupported expression {type(n).__name__}',n)
