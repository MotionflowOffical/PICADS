"""Independent numeric source interpreter for equivalence tests.
Does not inspect generated DLS, gates, or generator logic.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
from .generator import HWType, TYPES

@dataclass(frozen=True)
class V:
    num:int
    width:int
    signed:bool=False
    def __post_init__(self):
        object.__setattr__(self,'num',self.num & ((1<<self.width)-1))
    def integer(self):
        return self.num-(1<<self.width) if self.signed and (self.num>>(self.width-1))&1 else self.num
    def cast(self,width:int,signed=None):
        return V(self.integer() if self.signed else self.num,width,self.signed if signed is None else signed)
    def truth(self):return bool(self.num)

def annotation_type(a):
    if not isinstance(a,ast.Name):raise ValueError('invalid annotation')
    if a.id=='bool':return HWType(1)
    m=TYPES.fullmatch(a.id)
    if not m:raise ValueError('invalid annotation')
    return HWType(int(m.group(2)),m.group(1)=='s')

class SourceInterpreter:
    def __init__(self,source:str, top:str):
        tree=ast.parse(source)
        self.funcs={f.name:f for f in tree.body if isinstance(f,ast.FunctionDef)}
        self.top=top;self.registers={};self.next_regs={};self.depth=0;self.scope=[]

    def step(self,inputs:dict[str,int], clock=True):
        self.next_regs={}
        self.scope=[]
        out=self._call(self.top,[V(v,annotation_type(a.annotation).width,annotation_type(a.annotation).signed)
                                  for a in self.funcs[self.top].args.args for v in [inputs[a.arg]]], site=self.top)
        if clock:self.registers.update(self.next_regs)
        return {'result':out.num}

    def _call(self,name:str,args:list[V],site:str|None=None):
        if name not in self.funcs:raise ValueError(f'Unknown function {name}')
        if self.depth>25:raise ValueError('Recursive source functions unsupported')
        f=self.funcs[name]
        if len(args)!=len(f.args.args):raise ValueError('wrong argument count')
        env={a.arg:val.cast(annotation_type(a.annotation).width,annotation_type(a.annotation).signed)
             for a,val in zip(f.args.args,args)}
        self.depth+=1
        self.scope.append(site or name)
        try:
            result=self._block(f.body,env)
            if result is None:raise ValueError('missing return')
            t=annotation_type(f.returns)
            return result.cast(t.width,t.signed)
        finally:
            self.scope.pop()
            self.depth-=1

    def _block(self,statements,env):
        for i,s in enumerate(statements):
            if isinstance(s,ast.Return):return self._expr(s.value,env)
            if isinstance(s,(ast.Assign,ast.AnnAssign)):
                targets=s.targets if isinstance(s,ast.Assign) else [s.target]
                val=self._expr(s.value,env)
                if isinstance(s,ast.AnnAssign):
                    t=annotation_type(s.annotation);val=val.cast(t.width,t.signed)
                for t in targets:env[t.id]=val
            elif isinstance(s,ast.If):
                branch=s.body if self._expr(s.test,env).truth() else s.orelse
                return self._block(branch+statements[i+1:],env.copy())
            elif isinstance(s,ast.For):
                args=[v.value for v in s.iter.args]
                for j in range(*args):
                    env[s.target.id]=V(j,max(1,j.bit_length()+int(j<0)),j<0)
                    result=self._block(s.body,env)
                    if result is not None:return result
            elif isinstance(s,ast.Pass): pass
            else:raise ValueError(f'unsupported statement {type(s).__name__}')
        return None

    def _expr(self,n,env):
        if isinstance(n,ast.Name):return env[n.id]
        if isinstance(n,ast.Constant):
            if isinstance(n.value,bool):return V(int(n.value),1)
            if isinstance(n.value,int):return V(n.value,max(1,n.value.bit_length()+int(n.value<0)),n.value<0)
            raise ValueError('unsupported constant')
        if isinstance(n,ast.UnaryOp):
            a=self._expr(n.operand,env)
            if isinstance(n.op,ast.Invert):return V(~a.num,a.width,a.signed)
            if isinstance(n.op,ast.USub):return V(-a.num,a.width,a.signed)
            if isinstance(n.op,ast.Not):return V(not a.truth(),1)
        if isinstance(n,ast.BinOp):
            a=self._expr(n.left,env);b=self._expr(n.right,env); w=max(a.width,b.width)
            both=a.signed and b.signed
            if isinstance(n.op,ast.Add):return V(a.integer()+b.integer(),w+1,both)
            if isinstance(n.op,ast.Sub):return V(a.integer()-b.integer(),w,both)
            if isinstance(n.op,ast.Mult):return V(a.integer()*b.integer(),a.width+b.width,a.signed or b.signed)
            ax=a.cast(w,both).num; bx=b.cast(w,both).num
            if isinstance(n.op,ast.BitAnd):return V(ax & bx,w,both)
            if isinstance(n.op,ast.BitOr):return V(ax | bx,w,both)
            if isinstance(n.op,ast.BitXor):return V(ax ^ bx,w,both)
            if isinstance(n.op,ast.LShift):return V(a.num<<b.num,a.width+b.num,a.signed)
            if isinstance(n.op,ast.RShift):return V(a.integer()>>b.num if a.signed else a.num>>b.num,a.width,a.signed)
        if isinstance(n,ast.Compare):
            a=self._expr(n.left,env);b=self._expr(n.comparators[0],env)
            w=max(a.width,b.width);both=a.signed and b.signed
            av=a.cast(w,both).integer() if both else a.cast(w,False).num
            bv=b.cast(w,both).integer() if both else b.cast(w,False).num
            ops={ast.Eq:av==bv,ast.NotEq:av!=bv,ast.Lt:av<bv,ast.LtE:av<=bv,ast.Gt:av>bv,ast.GtE:av>=bv}
            return V(int(next(result for typ,result in ops.items() if isinstance(n.ops[0],typ))),1)
        if isinstance(n,ast.IfExp):
            return self._expr(n.body if self._expr(n.test,env).truth() else n.orelse,env)
        if isinstance(n,ast.BoolOp):
            vals=[self._expr(v,env).truth() for v in n.values]
            return V(int(all(vals) if isinstance(n.op,ast.And) else any(vals)),1)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name):
            if n.func.id=='reg':
                name=n.args[0].value; value=self._expr(n.args[1],env)
                options={kw.arg:kw.value for kw in n.keywords}
                init=options['init'].value if 'init' in options else 0
                key=tuple(self.scope)+(name,)
                old=self.registers.get(key,V(init,value.width,value.signed))
                enabled=self._expr(options['enable'],env).truth() if 'enable' in options else True
                reset=self._expr(options['reset'],env).truth() if 'reset' in options else False
                self.next_regs[key]=(V(init,value.width,value.signed) if reset else value if enabled else old)
                return old
            return self._call(n.func.id,[self._expr(arg,env) for arg in n.args],
                              site=f'{n.func.id}@{n.lineno}:{n.col_offset}')
        raise ValueError(f'unsupported expression {type(n).__name__}')
