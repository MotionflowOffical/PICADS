"""Restricted C/C++-compatible behavioral frontend.

Uses pycparser's actual C AST, never textual regex to infer operators. Only an
explicit value-only fixed-width subset is accepted. C++ syntax is supported
only where it is C-compatible; classes/templates/references are errors.

The normalized Python is a transparent intermediate, NOT ISO C integer-promotion
semantics. In particular arithmetic grows according to the ChipCompiler bitvector
rules, which are documented as hardware-language semantics.
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass
from pycparser import c_parser, c_ast
from pycparser.c_parser import ParseError

PRELUDE = '''typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
typedef signed char int8_t;
typedef short int16_t;
typedef int int32_t;
typedef long long int64_t;
typedef _Bool bool;
'''

class CFrontendError(ValueError):
    def __init__(self, code: str, message: str, line: int | None=None):
        self.code=code;self.line=line
        super().__init__(message)

@dataclass
class CTranslation:
    source: str
    functions: list[str]
    subset: str='fixed-width, value-only C/C++ subset; ChipCompiler bitvector arithmetic'
    line_map:dict[int,int]|None=None

class CTranslator:
    BIN={'+' :ast.Add, '-':ast.Sub,'*':ast.Mult, '&':ast.BitAnd,'|':ast.BitOr,'^':ast.BitXor,
         '<<':ast.LShift,'>>':ast.RShift,'==':ast.Eq,'!=':ast.NotEq,'<':ast.Lt,'<=':ast.LtE,
         '>':ast.Gt,'>=':ast.GtE,'&&':ast.And,'||':ast.Or}
    TYPES={'uint8_t':'u8','uint16_t':'u16','uint32_t':'u32','uint64_t':'u64',
           'int8_t':'s8','int16_t':'s16','int32_t':'s32','int64_t':'s64','bool':'bool',
           '_Bool':'bool','unsigned char':'u8','signed char':'s8','unsigned short':'u16',
           'short':'s16','short int':'s16','unsigned int':'u32','unsigned':'u32',
           'int':'s32','signed int':'s32','long long':'s64','long long int':'s64',
           'unsigned long long':'u64','unsigned long long int':'u64'}
    def fail(self,node,code,message):
        coord=getattr(node,'coord',None)
        line=getattr(coord,'line',None)
        raise CFrontendError(code,message,max(1,line-self._prefix) if line else None)
    def tagged(self,new,node):
        coord=getattr(node,'coord',None)
        line=getattr(coord,'line',None)
        new._c_original_line=max(1,line-self._prefix) if line else None
        return new
    def type(self,decl):
        if isinstance(decl,c_ast.TypeDecl):return self.type(decl.type)
        if isinstance(decl,c_ast.IdentifierType):
            name=' '.join(decl.names)
            if name in self.TYPES:return self.TYPES[name]
        self.fail(decl,'C.UNSUPPORTED_TYPE','Unsupported C type; use fixed-width scalar integers or bool; no pointers, arrays, structs, classes or references')
    def name(self,s):return ast.Name(id=s,ctx=ast.Load())
    def expr(self,n):
        if isinstance(n,c_ast.ID):return self.name(n.name)
        if isinstance(n,c_ast.Constant):
            if n.type not in ('int','unsigned int','long int','unsigned long int','long long int','unsigned long long int'):
                self.fail(n,'C.CONSTANT','Only integer constants are supported')
            raw=re.sub(r'[uUlL]+$','',n.value)
            if re.fullmatch(r'0[0-7]+',raw):value=int(raw,8)
            else:value=int(raw,0)
            return ast.Constant(value=value)
        if isinstance(n,c_ast.BinaryOp):
            cls=self.BIN.get(n.op)
            if cls is None:self.fail(n,'C.BINARY_OP',f'Unsupported binary operator {n.op!r}')
            if cls in (ast.And,ast.Or):return ast.BoolOp(op=cls(),values=[self.expr(n.left),self.expr(n.right)])
            if cls in (ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE):
                return ast.Compare(left=self.expr(n.left),ops=[cls()],comparators=[self.expr(n.right)])
            return ast.BinOp(left=self.expr(n.left),op=cls(),right=self.expr(n.right))
        if isinstance(n,c_ast.UnaryOp):
            op={'!':ast.Not,'~':ast.Invert,'-':ast.USub,'+':ast.UAdd}.get(n.op)
            if op is None:self.fail(n,'C.UNARY_OP',f'Unsupported unary operator {n.op!r}')
            if n.op=='+':return self.expr(n.expr)
            return ast.UnaryOp(op=op(),operand=self.expr(n.expr))
        if isinstance(n,c_ast.TernaryOp):return ast.IfExp(test=self.expr(n.cond),body=self.expr(n.iftrue),orelse=self.expr(n.iffalse))
        if isinstance(n,c_ast.FuncCall):
            if not isinstance(n.name,c_ast.ID):self.fail(n,'C.CALL','Only direct helper function calls supported')
            args=n.args.exprs if n.args else []
            return ast.Call(func=self.name(n.name.name),args=[self.expr(a) for a in args],keywords=[])
        if isinstance(n,c_ast.Cast):
            self.fail(n,'C.CAST','Explicit C casts are not yet supported; use an annotated local variable to control result width')
        self.fail(n,'C.EXPRESSION',f'Unsupported C expression: {type(n).__name__}')
    def statements(self,n):
        if n is None:return []
        if isinstance(n,c_ast.Compound):
            return [s for item in (n.block_items or []) for s in self.statements(item)]
        if isinstance(n,c_ast.Return):return [self.tagged(ast.Return(value=self.expr(n.expr)),n)]
        if isinstance(n,c_ast.Decl):
            if n.init is None:self.fail(n,'C.UNINITIALIZED','A local declaration must be initialized before use')
            return [self.tagged(ast.AnnAssign(target=ast.Name(id=n.name,ctx=ast.Store()),annotation=self.name(self.type(n.type)),value=self.expr(n.init),simple=1),n)]
        if isinstance(n,c_ast.Assignment):
            if n.op!='=' or not isinstance(n.lvalue,c_ast.ID):self.fail(n,'C.ASSIGN','Only simple variable assignments are supported')
            return [self.tagged(ast.Assign(targets=[ast.Name(id=n.lvalue.name,ctx=ast.Store())],value=self.expr(n.rvalue)),n)]
        if isinstance(n,c_ast.If):
            return [self.tagged(ast.If(test=self.expr(n.cond),body=self.statements(n.iftrue) or [ast.Pass()],orelse=self.statements(n.iffalse)),n)]
        if isinstance(n,c_ast.EmptyStatement):return [self.tagged(ast.Pass(),n)]
        if isinstance(n,c_ast.For):
            return [self.for_loop(n)]
        self.fail(n,'C.STATEMENT',f'Unsupported C statement: {type(n).__name__}')
    def literal(self,n):
        expr=self.expr(n)
        if isinstance(expr,ast.Constant) and type(expr.value)==int:return expr.value
        self.fail(n,'C.NONCONSTANT_LOOP','For-loop bounds must be integer literals')
    def for_loop(self,n):
        # for (int i = a; i < b; ++i) => for i in range(a,b)
        init=n.init
        if isinstance(init,c_ast.DeclList) and len(init.decls)==1:
            dec=init.decls[0];var=dec.name;start=self.literal(dec.init)
        elif isinstance(init,c_ast.Assignment) and init.op=='=' and isinstance(init.lvalue,c_ast.ID):
            var=init.lvalue.name;start=self.literal(init.rvalue)
        else:self.fail(n,'C.FOR_INIT','For-loop must initialize one induction variable')
        cond=n.cond
        if not isinstance(cond,c_ast.BinaryOp) or not isinstance(cond.left,c_ast.ID) or cond.left.name!=var or cond.op not in ('<','<=','>','>='):
            self.fail(n,'C.FOR_COND','For-loop condition must directly compare the induction variable with a literal')
        bound=self.literal(cond.right); nxt=n.next
        if isinstance(nxt,c_ast.UnaryOp) and isinstance(nxt.expr,c_ast.ID) and nxt.expr.name==var and nxt.op in ('p++','++','p--','--'):
            step=1 if '++' in nxt.op else -1
        elif isinstance(nxt,c_ast.Assignment) and isinstance(nxt.lvalue,c_ast.ID) and nxt.lvalue.name==var and nxt.op in ('+=','-='):
            step=self.literal(nxt.rvalue)*(1 if nxt.op=='+=' else -1)
        else:self.fail(n,'C.FOR_STEP','For-loop step must use ++, --, +=literal or -=literal')
        if not step or (step>0 and cond.op not in ('<','<=')) or (step<0 and cond.op not in ('>','>=')):
            self.fail(n,'C.FOR_DIRECTION','For-loop step and comparison direction disagree')
        stop=bound+(1 if cond.op=='<=' else -1 if cond.op=='>=' else 0)
        return self.tagged(ast.For(target=ast.Name(id=var,ctx=ast.Store()),iter=ast.Call(func=self.name('range'),args=[ast.Constant(start),ast.Constant(stop),ast.Constant(step)],keywords=[]),body=self.statements(n.stmt) or [ast.Pass()],orelse=[]),n)
    def translate(self,text:str,suffix:str='.c')->CTranslation:
        # Permit only standard integer/bool includes. Unsupported preprocessing is
        # rejected rather than pretending it was applied.
        lines=[]
        for i,line in enumerate(text.splitlines(),1):
            stripped=line.strip()
            if stripped.startswith('#'):
                if re.fullmatch(r'#\s*include\s*[<"](?:stdint|stdbool)\.h[>"]',stripped):lines.append('')
                else:raise CFrontendError('C.PREPROCESSOR',f'Unsupported preprocessor directive: {stripped}',i)
            else:lines.append(line)
        src='\n'.join(lines)
        if suffix.lower() in ('.cpp','.cc','.cxx'):
            # Only the C-compatible subset is accepted. A whole-file extern C
            # wrapper is allowed; C++-specific constructs otherwise fail parse.
            src=re.sub(r'^\s*extern\s+"C"\s*\{\s*','',src)
            src=re.sub(r'\}\s*$', '', src) if re.search(r'^\s*extern\s+"C"\s*\{',text) else src
        src=re.sub(r'/\*[\s\S]*?\*/',lambda m:'\n'*m.group().count('\n'),src)
        src=re.sub(r'//[^\n]*','',src)
        prefix=PRELUDE.count('\n')
        self._prefix=prefix
        try:tree=c_parser.CParser().parse(PRELUDE+src,filename='source')
        except ParseError as e:
            m=re.search(r':(\d+):(\d+):',str(e))
            line=max(1,int(m.group(1))-prefix) if m else None
            raise CFrontendError('C.PARSE',str(e),line) from e
        out=[]; names=[]
        for item in tree.ext:
            if isinstance(item,c_ast.Typedef):continue
            if not isinstance(item,c_ast.FuncDef):self.fail(item,'C.TOP_LEVEL','Only pure function definitions are supported (no globals or prototypes)')
            fn=item.decl;name=fn.name
            if not isinstance(fn.type,c_ast.FuncDecl):self.fail(fn,'C.FUNCTION','Expected a scalar function definition')
            args=[]
            for param in (fn.type.args.params if fn.type.args else []):
                if (isinstance(param,c_ast.Typename) and isinstance(param.type,c_ast.TypeDecl)
                        and isinstance(param.type.type,c_ast.IdentifierType)
                        and param.type.type.names==['void']):
                    continue  # C f(void) has no inputs
                if not isinstance(param,c_ast.Decl) or not param.name:self.fail(param,'C.PARAM','Each input requires a name and fixed-width scalar type')
                args.append(ast.arg(arg=param.name,annotation=self.name(self.type(param.type))))
            stmts=self.statements(item.body)
            out.append(self.tagged(ast.FunctionDef(name=name,args=ast.arguments(posonlyargs=[],args=args,vararg=None,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[]),body=stmts or [ast.Pass()],decorator_list=[],returns=self.name(self.type(fn.type.type)),type_comment=None),item))
            names.append(name)
        if not out:raise CFrontendError('C.NO_FUNCTIONS','Source has no hardware functions')
        result=ast.fix_missing_locations(ast.Module(body=out,type_ignores=[]))
        normalized=ast.unparse(result)+'\n'
        parsed=ast.parse(normalized)
        tagged=[n for n in ast.walk(result) if isinstance(n,ast.stmt)]
        statements=[n for n in ast.walk(parsed) if isinstance(n,ast.stmt)]
        line_map={}
        for old,new in zip(tagged,statements):
            line=getattr(old,'_c_original_line',None)
            if line is not None:line_map[new.lineno]=line
        return CTranslation(normalized,names,line_map=line_map)

def translate_c(text:str,suffix:str='.c')->CTranslation:
    return CTranslator().translate(text,suffix)
