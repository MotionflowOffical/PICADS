"""Conservative MCD source-to-service binding for shared arithmetic hardware.

Stateless fixed-width functions using ADD/MUL are checked structurally. A
simple conditional operation selector is also supported; it becomes a typed
per-client port in the generated DLS and selects a shared ALU operation for
each accepted transaction. Arbitrary source processes are not supported.
"""
from __future__ import annotations
import ast,re
from .tagged import TaggedFabricConfig,tagged_fabric
from .ir import DLS,Node

_TYPE=re.compile(r'u([1-9][0-9]*)\Z')


def infer_bindings(source:str,clients:list,config:TaggedFabricConfig)->list[dict]:
    config.validate()
    if not isinstance(clients,list) or len(clients)!=config.clients:
        raise ValueError(f'MCD.BINDING_COUNT: concurrent_clients must have {config.clients} entries')
    root=ast.parse(source)
    functions={node.name:node for node in root.body if isinstance(node,ast.FunctionDef)}
    bindings=[];names=set()
    for i,item in enumerate(clients):
        if not isinstance(item,dict) or set(item)!={'name','function'}:
            raise ValueError(f'MCD.BINDING_FORMAT: entry {i} must have name and function')
        name=item['name'];fn=item['function']
        if not isinstance(name,str) or not name.isidentifier() or name in names:
            raise ValueError(f'MCD.BINDING_NAME: invalid or duplicated name {name!r}')
        names.add(name)
        if not isinstance(fn,str) or fn not in functions:
            raise ValueError(f'MCD.BINDING_FUNCTION: unknown function {fn!r}')
        node=functions[fn]
        args=node.args
        if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults or len(args.args) not in (2,3):
            raise ValueError(f'MCD.BINDING_SIGNATURE: {fn} requires two unsigned data inputs and optional Boolean selector')
        def width(annotation):
            token=annotation.id if isinstance(annotation,ast.Name) else ''
            m=_TYPE.fullmatch(token)
            return int(m.group(1)) if m else None
        if any(width(a.annotation)!=config.width for a in args.args[:2]) or width(node.returns)!=config.width:
            raise ValueError(f'MCD.BINDING_WIDTH: {fn} requires unsigned u{config.width} data inputs and output')
        has_selector=len(args.args)==3
        selector=args.args[2].arg if has_selector else None
        if has_selector and (not isinstance(args.args[2].annotation,ast.Name) or args.args[2].annotation.id!='bool'):
            raise ValueError(f'MCD.BINDING_WIDTH: selector of {fn} must be bool')
        statements=[stmt for stmt in node.body if not (isinstance(stmt,ast.Expr) and
                    isinstance(stmt.value,ast.Constant) and isinstance(stmt.value.value,str))]
        a,b=(arg.arg for arg in args.args[:2])
        def operation(expr):
            if (not isinstance(expr,ast.BinOp) or type(expr.op) not in (ast.Add,ast.Mult) or
                not isinstance(expr.left,ast.Name) or not isinstance(expr.right,ast.Name) or
                {expr.left.id,expr.right.id}!={a,b}):
                raise ValueError(f'MCD.BINDING_OPERATOR: {fn} must select a + b or a * b')
            return 0 if isinstance(expr.op,ast.Add) else 1
        if not has_selector:
            if len(statements)!=1 or not isinstance(statements[0],ast.Return):
                raise ValueError(f'MCD.BINDING_BODY: {fn} must contain exactly one arithmetic return')
            opcode=operation(statements[0].value)
            bindings.append({'client':i,'name':name,'function':fn,'opcode':opcode,
                             'operation':'ADD' if opcode==0 else 'MUL','width':config.width,
                             'source_line':node.lineno})
            continue
        # Exactly one Boolean selector, controlling a pure pair of operators.
        if len(statements)==1 and isinstance(statements[0],ast.Return) and isinstance(statements[0].value,ast.IfExp):
            expr=statements[0].value
            test=expr.test;when_true=expr.body;when_false=expr.orelse
        elif (len(statements)==2 and isinstance(statements[0],ast.If) and
              len(statements[0].body)==1 and isinstance(statements[0].body[0],ast.Return) and
              not statements[0].orelse and isinstance(statements[1],ast.Return)):
            test=statements[0].test;when_true=statements[0].body[0].value;when_false=statements[1].value
        elif (len(statements)==1 and isinstance(statements[0],ast.If) and
              len(statements[0].body)==1 and len(statements[0].orelse)==1 and
              isinstance(statements[0].body[0],ast.Return) and isinstance(statements[0].orelse[0],ast.Return)):
            test=statements[0].test;when_true=statements[0].body[0].value;when_false=statements[0].orelse[0].value
        else:
            raise ValueError(f'MCD.BINDING_BODY: {fn} must use return a OP b if selector else a OP b, or equivalent terminal if/else')
        if not isinstance(test,ast.Name) or test.id!=selector:
            raise ValueError(f'MCD.BINDING_SELECTOR: {fn} selector must be the Boolean input {selector!r}')
        true_op=operation(when_true);false_op=operation(when_false)
        bindings.append({'client':i,'name':name,'function':fn,'opcode':None,
                         'operation':'SELECT','width':config.width,'source_line':node.lineno,
                         'selector':selector,'true_opcode':true_op,'false_opcode':false_op})
    return bindings


def bound_source_fabric(source:str,clients:list,config:TaggedFabricConfig,
                        name='bound_resource_fabric')->DLS:
    bindings=infer_bindings(source,clients,config)
    core=tagged_fabric(config,'tagged_backend')
    # The wrapper exports typed transaction interfaces. Constant opcodes are
    # tied down; conditional opcodes are driven by a declared SELECT port.
    top_inputs={};input_map={};nodes=[]
    for key,width in core.inputs.items():
        if key.startswith('opcode_'):
            i=int(key.split('_')[-1]);binding=bindings[i]
            if binding['operation']=='SELECT':
                select=f'select_{i}';top_inputs[select]=1
                true=binding['true_opcode'];false=binding['false_opcode']
                if true==false:opcode='@1' if true else '@0'
                elif true==1:opcode=f'{select}[0]'
                else:
                    opcode=f'inverted_select_{i}'
                    nodes.append(Node(opcode,'NOT',[f'{select}[0]']))
                input_map[key]=[opcode,'@0']
            else:
                opcode=binding['opcode']
                input_map[key]=['@1' if opcode & (1<<bit) else '@0' for bit in range(width)]
        else:
            top_inputs[key]=width
            input_map[key]=[f'{key}[{j}]' for j in range(width)]
    top=DLS(name,top_inputs,
            {k:[f'fabric_{k}_{j}' for j in range(len(bits))] for k,bits in core.outputs.items()},
            nodes,{}, {'kind':'bound_source_fabric','bindings':bindings,
                    'schedule':{**core.metadata['schedule'],'mode':'bound_fabric'},
                    'verification':'Restricted AST arithmetic/conditional binding; transactional protocol requires scoreboard.'},
            [{'name':'fabric','module':'tagged_backend','at':len(nodes),'inputs':input_map,
              'outputs':{k:[f'fabric_{k}_{j}' for j in range(len(bits))] for k,bits in core.outputs.items()}}],
            {'tagged_backend':core})
    top.validate()
    return top
