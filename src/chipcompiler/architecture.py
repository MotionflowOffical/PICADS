"""Transparent functional-module allocation and dependency analysis.

Source functions form genuinely separately compilable module candidates. The
physical top is still flattened by the current DLS lowering and the report
explicitly marks this distinction, rather than implying a hierarchical RTL.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass,field,asdict

@dataclass
class ArchitectureGraph:
    top:str
    functions:list[str]
    edges:list[dict]
    requested:list[dict]
    reachable:list[str]
    unused:list[str]
    semantics:str='FUNCTIONAL_MODULES_TOP_FLATTENED'
    def as_dict(self):return asdict(self)

def analyze(source:str,top:str,mcd:dict):
    tree=ast.parse(source)
    functions={x.name:x for x in tree.body if isinstance(x,ast.FunctionDef)}
    if top not in functions:raise ValueError(f'Missing top {top!r}')
    edges=[]
    for name,node in functions.items():
        for item in ast.walk(node):
            if isinstance(item,ast.Call) and isinstance(item.func,ast.Name) and item.func.id in functions:
                edges.append({'caller':name,'callee':item.func.id,'line':item.lineno})
    edges.sort(key=lambda x:(x['caller'],x['line'],x['callee']))
    reachable=[]
    def visit(name):
        if name in reachable:return
        reachable.append(name)
        for edge in edges:
            if edge['caller']==name:visit(edge['callee'])
    visit(top)
    requested=[]
    for module in mcd.get('modules',[]):
        if not isinstance(module,dict):continue
        name=module.get('name','')
        function=module.get('function',name if name in functions else None)
        requested.append({'name':name,'function':function,'declared':True,
                          'status':'candidate' if function in functions else 'descriptive-only',
                          'purpose':module.get('purpose','')})
    return ArchitectureGraph(top,sorted(functions),edges,requested,reachable,
                             sorted(set(functions)-set(reachable)))


def check_requirements(graph: ArchitectureGraph, mcd: dict) -> list[dict]:
    """Resolve mandatory MCD functional capabilities against the actual call graph.

    `requires` is a list of module/function names or objects with `function`
    (or `module`) and `min_instances`. Counts are statically expanded callsites,
    not physical cell counts or resource-sharing guarantees. Recursive call
    graphs have no valid finite hardware expansion and are rejected.
    """
    known=set(graph.functions)
    module_names={r['name']:r['function'] for r in graph.requested}
    by_caller={f:[] for f in known}
    for edge in graph.edges:by_caller[edge['caller']].append(edge['callee'])
    counts={f:0 for f in known}
    def walk(fn,ancestry=()):
        if fn in ancestry:raise ValueError('Recursive module dependency: '+' -> '.join((*ancestry,fn)))
        counts[fn]+=1
        for child in by_caller[fn]:walk(child,(*ancestry,fn))
    walk(graph.top)
    assessments=[]
    for entry in mcd.get('requires',[]):
        requested=entry if isinstance(entry,str) else entry.get('function',entry.get('module'))
        required=1 if isinstance(entry,str) else entry.get('min_instances',1)
        function=module_names.get(requested, requested)
        status=('UNKNOWN' if function not in known else
                'UNREACHABLE' if counts[function]==0 else
                'INSUFFICIENT' if counts[function]<required else 'SATISFIED')
        assessments.append({'requirement':requested,'function':function,
                            'min_instances':required,'expanded_calls':counts.get(function,0),
                            'status':status})
    return assessments


def apply_mcd_names(design, mcd:dict):
    """Bind logical MCD module names to actual hierarchical DLS definitions.

    Opt-in because older projects use function names as Verilog identifiers.
    The source top keeps its callable identifier for source equivalence, while
    children are renamed recursively with all references updated.
    """
    from .ir import DLS
    import re
    mapping={}
    for module in mcd.get('modules',[]):
        if not isinstance(module,dict) or not module.get('function'):continue
        function=module['function'];label=module.get('name')
        if function==design.name:
            design.metadata['mcd_top_label']=label
            continue
        if not isinstance(label,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',label):
            raise ValueError(f'MCD module {function!r} has invalid hardware identifier {label!r}')
        if function in mapping and mapping[function]!=label:
            raise ValueError(f'MCD function {function!r} has conflicting module names {mapping[function]!r}, {label!r}')
        mapping[function]=label
    reachable={design.name}
    def collect(item):
        for fn,child in item.submodules.items():
            reachable.add(fn)
            collect(child)
    collect(design)
    resolved={fn:mapping.get(fn,fn) for fn in reachable}
    if len(set(resolved.values()))!=len(resolved):
        raise ValueError(f'MCD bindings produce duplicate hardware module identifiers: {resolved}')
    def bind(item):
        new={}
        for fn,child in item.submodules.items():
            bind(child)
            renamed=resolved[fn]
            child.name=renamed
            new[renamed]=child
        item.submodules=new
        for inst in item.instances:
            inst['source_function']=inst['module']
            inst['module']=resolved[inst['module']]
    bind(design)
    design.metadata['mcd_module_mapping']={k:v for k,v in resolved.items() if k!=v}
    design.validate()
    return design


def count_instantiated_operators(design):
    """Count source-level operator implementations across concrete hierarchy.

    Each instance is counted, not each unique submodule definition. This is a
    source-operator inventory, not a standard-cell or transistor count.
    """
    counts={}
    locations={}
    def visit(d,path,stack=()):
        if d.name in stack:raise ValueError('Recursive DLS hierarchy cannot be counted')
        for kind,count in d.metadata.get('operator_counts',{}).items():
            counts[kind]=counts.get(kind,0)+count
            locations.setdefault(kind,[]).append({'instance':path,'operators':count})
        for inst in d.instances:
            visit(d.submodules[inst['module']],path+'/'+inst['name'],(*stack,d.name))
    visit(design,design.name)
    return counts,locations
