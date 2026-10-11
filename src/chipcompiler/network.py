"""Typed hierarchical MCD network construction.

An optional ``network`` block is an IMPLEMENTATION of the source's top function,
not a second reference model. The source is verified independently against the
constructed DLS. No implicit truncation, bit extension, muxing, or guessed
multi-driver resolution is permitted.

The instance graph is sorted topologically, with independent preflight errors
collected before a dependent build stage is marked blocked.
"""
from __future__ import annotations
import ast
import copy
import re
from dataclasses import dataclass
from .diagnostics import DiagnosticException, IssueCollector
from .generator import HardwareCompiler
from .ir import DLS

_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z_0-9]*$')
_REF = re.compile(r'^(?:(?P<owner>[a-zA-Z_][a-zA-Z_0-9]*)\.)?(?P<port>[a-zA-Z_][a-zA-Z_0-9]*)(?:\[(?P<hi>\d+)(?::(?P<lo>\d+))?\])?$')

@dataclass
class NetworkBuild:
    design: DLS
    connections: list[dict]


def compile_network(source: str, path: str, top: str, mcd: dict,
                    co: dict | None = None, issues: IssueCollector | None = None) -> NetworkBuild:
    issues = issues if issues is not None else IssueCollector()
    network = mcd.get('network')
    if not isinstance(network,dict):
        issue=issues.add('MCD.NETWORK.FORMAT','ERROR','MCD','network',
                         'MCD network must be a mapping with instances and outputs.',file=path)
        raise DiagnosticException(issue)
    errors=[]
    def problem(code,msg,**evidence):
        item=issues.add('MCD.NETWORK.'+code,'ERROR','MCD','network',msg,file=path,
                        cause='An explicit inter-module connection or declaration is invalid.',
                        remedy='Correct the named connection in MCD.network; downstream stages remain blocked.',
                        evidence=evidence)
        errors.append(item)
    try:
        functions={n.name for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    except SyntaxError as exc:
        problem('SOURCE',f'Source cannot be parsed: {exc}')
        raise DiagnosticException(errors[0])
    if top not in functions:
        problem('TOP',f'Reference top function {top!r} is missing.')
        raise DiagnosticException(errors[0])
    for field in network:
        if field not in ('instances','outputs','auto_connect'):
            problem('UNKNOWN_FIELD',f'Unknown MCD.network field {field!r}; it has no implementation.',field=field)
    auto_connect=network.get('auto_connect','top_only')
    if auto_connect not in ('top_only','unique_width'):
        problem('AUTO_CONNECT_POLICY',f'Unknown auto_connect policy {auto_connect!r}.',value=auto_connect)
    specs=network.get('instances',[])
    if not isinstance(specs,list) or not specs:
        problem('INSTANCES','network.instances must be a nonempty list.')
        raise DiagnosticException(errors[0])
    if len(specs)>128:
        problem('INSTANCE_LIMIT','Network exceeds 128 logical instances.')
        raise DiagnosticException(errors[0])
    raw={}
    for index,item in enumerate(specs):
        if not isinstance(item,dict):
            problem('INSTANCE_FORMAT',f'Instance {index} must be a mapping.',index=index);continue
        name=item.get('name');fn=item.get('function')
        primitive=item.get('primitive')
        if not isinstance(name,str) or not _IDENTIFIER.fullmatch(name):
            problem('INSTANCE_NAME',f'Instance {index} has invalid name {name!r}.',index=index);continue
        if name in raw:
            problem('DUPLICATE_INSTANCE',f'Duplicate instance {name!r}.',instance=name);continue
        if primitive is not None:
            if primitive!='round_robin_arbiter' or fn is not None:
                problem('PRIMITIVE',f'Instance {name!r} has unsupported primitive or contradictory function binding.',instance=name,primitive=primitive)
                continue
            n=item.get('clients');width=item.get('payload_width')
            if type(n)!=int or not 2<=n<=8 or type(width)!=int or not 1<=width<=128:
                problem('ARBITER_CONFIG',f'{name}: round_robin_arbiter requires clients=2..8 and payload_width=1..128.',instance=name)
                continue
        else:
            if not isinstance(fn,str) or fn not in functions:
                problem('UNKNOWN_FUNCTION',f'Instance {name!r} references nonexistent function {fn!r}.',instance=name,function=fn)
                continue
            if fn==top:
                problem('RECURSIVE_TOP',f'Network instance {name!r} cannot instantiate behavioral top {top!r}.',instance=name)
                continue
        for field in item:
            if field not in ('name','function','inputs','primitive','clients','payload_width'):
                problem('UNKNOWN_INSTANCE_FIELD',f'Instance {name!r} has unrecognized field {field!r}.',
                        instance=name,field=field)
        if not isinstance(item.get('inputs',{}),dict):
            problem('INPUT_MAP',f'{name}.inputs must be a mapping.',instance=name)
            continue
        raw[name]=item
    if errors:raise DiagnosticException(errors[0])
    child_co=copy.deepcopy(co or {})
    child_co.setdefault('modules',{})['hierarchy']='preserve'
    child_co['modules']['naming']='function'
    children={};instance_definitions={}
    for name,item in raw.items():
        if item.get('primitive')=='round_robin_arbiter':
            from .arbitration import round_robin_arbiter
            definition=f'rr_arbiter_{item["clients"]}_{item["payload_width"]}'
            if definition not in children:
                children[definition]=round_robin_arbiter(item['clients'],item['payload_width'],definition)
        else:
            definition=item['function']
            if definition not in children:
                try:children[definition]=HardwareCompiler(issues,child_co).compile_source(source,path,definition)
                except DiagnosticException as exc:
                    problem('CHILD_COMPILE',f'Cannot compile child {definition!r}; see referenced source error.',
                            function=definition,upstream_issue=exc.issue.issue_id)
        instance_definitions[name]=definition
    if errors:raise DiagnosticException(errors[0])
    # Top is only a reference specification: its gates are not inserted.
    try:reference=HardwareCompiler(issues,{'modules':{'hierarchy':'preserve'}}).compile_source(source,path,top)
    except DiagnosticException as exc:
        problem('REFERENCE',f'Cannot compile behavioral reference {top!r}.',upstream_issue=exc.issue.issue_id)
        raise DiagnosticException(errors[0])
    top_inputs=reference.inputs
    top_outputs={k:len(v) for k,v in reference.outputs.items()}
    all_output_names={name:{p:len(bits) for p,bits in children[instance_definitions[name]].outputs.items()}
                      for name,item in raw.items()}
    # Auto-binding is intentionally narrow: matching an *external* top input
    # name is safe. Internal outputs must be named explicitly to avoid hidden
    # decisions when new modules are introduced.
    inbound={};dependencies={name:set() for name in raw}
    references=[]
    def classify(expr,who):
        if isinstance(expr,dict):
            if set(expr)!={'const','width'} or type(expr['const'])!=int or type(expr['width'])!=int or not (1<=expr['width']<=4096) or expr['const']<0 or expr['const']>=(1<<expr['width']):
                problem('BAD_CONSTANT',f'Invalid constant for {who}: {expr!r}.',destination=who)
                return None
            return ('constant',expr['const'],expr['width'])
        if not isinstance(expr,str):
            problem('BAD_REFERENCE',f'{who}: expected named bus or explicit constant, found {expr!r}.',destination=who)
            return None
        match=_REF.fullmatch(expr)
        if match is None:
            problem('BAD_REFERENCE',f'{who}: malformed bus reference {expr!r}.',destination=who)
            return None
        owner=match['owner'];port=match['port']
        if owner in (None,'top'):
            if port not in top_inputs:
                problem('UNKNOWN_INPUT',f'{who}: external input {port!r} does not exist.',destination=who,reference=expr)
                return None
            kind='input';width=top_inputs[port];owner='top'
        else:
            if owner not in raw:
                problem('UNKNOWN_INSTANCE',f'{who}: referenced instance {owner!r} does not exist.',destination=who,reference=expr)
                return None
            if port not in all_output_names[owner]:
                problem('UNKNOWN_OUTPUT',f'{who}: instance {owner!r} has no output {port!r}.',destination=who,reference=expr)
                return None
            kind='output';width=all_output_names[owner][port]
        hi,lo=match['hi'],match['lo']
        if hi is not None:
            hi=int(hi);lo=hi if lo is None else int(lo)
            if hi<lo or hi>=width:
                problem('SLICE',f'{who}: invalid slice {expr!r} for {width}-bit bus.',destination=who,reference=expr)
                return None
        else:hi=width-1;lo=0
        return (kind,owner,port,hi,lo)
    def width_of(descr):
        if descr is None:return None
        return descr[2] if descr[0]=='constant' else descr[3]-descr[4]+1
    for name,item in raw.items():
        child=children[instance_definitions[name]]
        mapping=item.get('inputs',{})
        for key in mapping:
            if key not in child.inputs:
                problem('UNKNOWN_PORT',f'{name}: connection targets unknown input port {key!r}.',instance=name,port=key)
        inbound[name]={}
        for port,expected in child.inputs.items():
            dest=f'{name}.{port}'
            expr=mapping.get(port,port if port in top_inputs else None)
            inferred_width=False
            if expr is None and auto_connect=='unique_width':
                candidates=[(other,p) for other,ports in all_output_names.items() if other!=name
                            for p,width in ports.items() if width==expected]
                exact=[(owner,p) for owner,p in candidates if p==port]
                if len(exact)==1:candidates=exact
                if len(candidates)==1:
                    expr=f'{candidates[0][0]}.{candidates[0][1]}'
                    inferred_width=True
                elif len(candidates)>1:
                    problem('AMBIGUOUS_AUTO',
                            f'{dest} has {len(candidates)} possible producer ports; refusing to guess.',
                            instance=name,port=port,candidates=[f'{owner}.{p}' for owner,p in candidates])
                    continue
            if expr is None:
                problem('UNCONNECTED',f'{dest} is not connected and cannot safely be inferred.',instance=name,port=port)
                continue
            desc=classify(expr,dest)
            if desc is None:continue
            actual=width_of(desc)
            if actual!=expected:
                problem('WIDTH',f'{dest} expects {expected} bits, but {expr!r} provides {actual}.',
                        instance=name,port=port,expected=expected,actual=actual)
                continue
            if desc[0]=='output':dependencies[name].add(desc[1])
            inbound[name][port]=desc
            references.append({'destination':dest,'source':expr,'width':expected,
                               'mode':'auto-unique-width' if inferred_width else 'auto-top' if port not in mapping else 'explicit'})
    outmap=network.get('outputs')
    if not isinstance(outmap,dict):
        problem('OUTPUT_MAP','network.outputs must map all reference-top outputs to signal references.')
        outmap={}
    if set(outmap)!=set(top_outputs):
        problem('OUTPUT_INTERFACE',f'Network outputs {sorted(outmap)} do not match reference ports {sorted(top_outputs)}.',
                actual=sorted(outmap),expected=sorted(top_outputs))
    resolved_outputs={}
    for port,width in top_outputs.items():
        if port not in outmap:continue
        expr=outmap[port];desc=classify(expr,'top.'+port)
        if desc is not None:
            if width_of(desc)!=width:
                problem('OUTPUT_WIDTH',f'top.{port} expects {width} bits, but {expr!r} provides {width_of(desc)}.',port=port)
            else:
                resolved_outputs[port]=desc
                references.append({'destination':'top.'+port,'source':expr,'width':width,'mode':'explicit'})
    # Kahn sort catches combinational wiring cycles and ensures each instance's
    # output is driven before a downstream consumer at DLS evaluation time.
    topo=[];left={k:set(v) for k,v in dependencies.items()}
    while left:
        ready=sorted(k for k,v in left.items() if not v)
        if not ready:
            problem('CYCLE','Combinational network contains an instance dependency cycle.',remaining={k:sorted(v) for k,v in left.items()})
            break
        for item in ready:topo.append(item);del left[item]
        for targets in left.values():targets.difference_update(ready)
    if errors:raise DiagnosticException(errors[0])
    inferred=[r for r in references if r['mode']=='auto-unique-width']
    if inferred:
        issues.add('MCD.NETWORK.WIDTH_INFERRED','WARNING','MCD','network',
                   f'{len(inferred)} producer connections inferred by unique bit width; semantic meaning is not guaranteed.',
                   cause='No explicit binding or matching external input was available; only one producer had the required width.',
                   remedy='Review network_connections.json and source equivalence; specify inputs explicitly for critical designs.',
                   evidence={'connections':inferred})
    nets={('input','top',name):tuple(f'{name}[{j}]' for j in range(width))
          for name,width in top_inputs.items()}
    instances=[]
    def wire(desc):
        if desc[0]=='constant':return tuple('@1' if desc[1]>>i&1 else '@0' for i in range(desc[2]))
        bits=nets[(desc[0],desc[1],desc[2])]
        return tuple(bits[desc[4]:desc[3]+1])
    for name in topo:
        child=children[instance_definitions[name]]
        output={}
        for port,bits in child.outputs.items():
            pins=[f'net_{name}_{port}_{j}' for j in range(len(bits))]
            nets[('output',name,port)]=tuple(pins)
            output[port]=pins
        instances.append({'name':name,'module':child.name,'at':0,
                          'inputs':{port:list(wire(desc)) for port,desc in inbound[name].items()},
                          'outputs':output})
    design=DLS(top,top_inputs,{name:list(wire(desc)) for name,desc in resolved_outputs.items()},[],{},
               {'top':top,'source':path,'strategies':{},'network':{'kind':'mcd_explicit',
                   'topological_order':topo,'connections':references,
                   'generated_primitives':{name:instance_definitions[name] for name,item in raw.items() if item.get('primitive')},
                   'routing':'named typed buses; optional unique-width inference explicitly reported',
                   'auto_connect':auto_connect},
                'compiler':'chipcompiler network v0.6'},
               instances,{fn:child for fn,child in children.items()})
    try:design.validate()
    except ValueError as exc:
        issue=issues.add('MCD.NETWORK.INVALID_DLS','ERROR','MCD','network',str(exc),file=path,
                         cause='Network composition created an invalid gate-level hierarchical graph.',
                         remedy='Review network connections and attach the diagnostic bundle.')
        raise DiagnosticException(issue)
    return NetworkBuild(design,references)
