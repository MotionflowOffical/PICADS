"""Compile multiple independent bounded Python source processes as clocked DLS.

Each MCD client becomes an independently executing transactional FSM, with its
own START/READY/DONE, stall, operand snapshot, local memory and registers.
This is *parallel source-process composition*, not cross-process resource
sharing or a general concurrent scheduling optimizer. Dependencies between
processes, message passing and shared memory require other explicit hardware.
"""
from __future__ import annotations
import ast,copy
from dataclasses import dataclass
from .transactional import TransactionalCompiler
from .diagnostics import IssueCollector
from .ir import DLS


def compile_source_processes(source:str,clients:list,co:dict|None=None,
                             name='source_processes',issues:IssueCollector|None=None)->DLS:
    if not isinstance(name,str) or not name.isidentifier():
        raise ValueError('MCD.PROCESS_NAME: top-level module identifier required')
    if not isinstance(clients,list) or not 2<=len(clients)<=8:
        raise ValueError('MCD.PROCESS_CLIENTS: exactly 2..8 process instances required')
    tree=ast.parse(source)
    functions={node.name for node in tree.body if isinstance(node,ast.FunctionDef)}
    seen=set();inputs={'reset':1};outputs={};instances=[];submodules={};metadata=[]
    co=copy.deepcopy(co or {})
    co.setdefault('schedule',{})['mode']='transactional'
    for index,item in enumerate(clients):
        if not isinstance(item,dict) or set(item)!={'name','function'}:
            raise ValueError('MCD.PROCESS_DECLARATION: every client needs name and function')
        ident=item['name'];fn=item['function']
        if not isinstance(ident,str) or not ident.isidentifier() or ident in seen:
            raise ValueError(f'MCD.PROCESS_DUPLICATE: invalid or repeated name {ident!r}')
        if not isinstance(fn,str) or fn not in functions:
            raise ValueError(f'MCD.PROCESS_FUNCTION: no source function {fn!r}')
        seen.add(ident)
        if fn not in submodules:
            submodules[fn]=TransactionalCompiler(issues,co).compile_source(source,top=fn)
        child=submodules[fn]
        pins={}
        for port,width in child.inputs.items():
            if port=='reset':pins[port]=['reset[0]']
            else:
                public=f'{ident}_{port}'
                inputs[public]=width
                pins[port]=[f'{public}[{j}]' for j in range(width)]
        outs={}
        for port,bits in child.outputs.items():
            public=f'{ident}_{port}'
            outputs[public]=[f'{ident}_{port}_{j}' for j in range(len(bits))]
            outs[port]=outputs[public]
        instances.append({'name':ident,'module':fn,'at':0,'inputs':pins,'outputs':outs})
        metadata.append({'client':ident,'function':fn,'input_ports':list(pins),
             'result_width':len(child.outputs['result']),
             'instructions':child.metadata['schedule']['instruction_count'],
             'local_memory':child.metadata['schedule'].get('memory')})
    hierarchy_gates=sum(submodules[item['function']].stats()['primitive_gates']
                        for item in metadata)
    hierarchy_state=sum(submodules[item['function']].stats()['state_bits']
                        for item in metadata)
    design=DLS(name,inputs,outputs,[],{},
        {'hierarchical_primitive_gates':hierarchy_gates,
         'hierarchical_state_bits':hierarchy_state,
         'kind':'parallel_source_processes','schedule':{
             'mode':'source_processes','clients':len(clients),'source_bindings':metadata,
             'max_outstanding_per_process':1,'resource_sharing_across_processes':False,
             'execution':'Independent clocked transactional FSM for each source function',
             'memory':'Separate private register-bank for each instance',
             'limitations':['no automatic inter-process shared-operator allocation',
                'no automatic communication between processes','no cross-process atomic memory']}},
        instances,submodules)
    design.validate();return design


def check_source_processes(source:str,design:DLS,issues:IssueCollector,
                           random_vectors:int=12)->dict:
    """Independently verify child source equivalence and concurrent state isolation."""
    from .transactional_verify import verify_transactional
    from .reference import SourceInterpreter
    import random
    local={}
    for name,child in design.submodules.items():
        proof=verify_transactional(source,child,issues,random_vectors=random_vectors)
        local[name]=proof.as_dict()
        if proof.status in ('FAIL','ERROR'):
            return {'status':'FAIL','children':local,'reason':f'{name}: source mismatch'}
    sim=design.new_simulator();ports={key:0 for key in design.inputs}
    ports['reset']=1;sim.step(ports)
    ports['reset']=0
    rng=random.Random(7189)
    clients=design.metadata['schedule']['source_bindings']
    expected={};inflight=set();finished=set()
    for item in clients:
        name=item['client'];fn=item['function'];child=design.submodules[fn]
        original_inputs={k:v for k,v in child.inputs.items()
                         if k not in ('start','stall','reset') and not k.startswith('unit_ready_')}
        args={k:rng.getrandbits(width) for k,width in original_inputs.items()}
        for k,val in args.items():ports[f'{name}_{k}']=val
        ports[f'{name}_start']=1;ports[f'{name}_stall']=0
        for k in child.inputs:
            if k.startswith('unit_ready_'):ports[f'{name}_{k}']=1
        # Stateless reference comparison is meaningful for independent
        # non-memory clients. Private-memory processes are checked by their
        # isolated transactional verifier above.
        if not item['local_memory']:
            expected[name]=SourceInterpreter(source,fn).step(args)['result']
        inflight.add(name)
    for edge in range(500):
        output=sim.step(ports)
        for name in tuple(inflight):
            if output[f'{name}_done']:
                if name in expected and output[f'{name}_result']!=expected[name]:
                    return {'status':'FAIL','children':local,'reason':'parallel result mismatch',
                      'client':name,'edge':edge,'expected':expected[name],
                      'actual':output[f'{name}_result']}
                finished.add(name);inflight.remove(name)
        for item in clients:
            name=item['client'];ports[f'{name}_start']=0
            # Change inputs while work progresses to confirm each child
            # captures source inputs at transaction acceptance.
            for k in design.submodules[item['function']].inputs:
                if k not in ('start','stall','reset') and not k.startswith('unit_ready_'):
                    port=f'{name}_{k}'
                    ports[port]=rng.getrandbits(design.inputs[port])
        if not inflight:
            return {'status':'PASS','children':local,'concurrent_processes':len(clients),
                'completion_cycles':edge+1,'completed':sorted(finished),
                'source_equivalence':'sampled per child; concurrent state isolation directed'}
    return {'status':'FAIL','children':local,'reason':'Concurrent process completion timeout',
            'remaining':sorted(inflight)}
