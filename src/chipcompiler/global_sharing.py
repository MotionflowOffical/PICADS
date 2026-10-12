"""Opt-in shared integer and Boolean datapaths across concurrent source FSMs.

This compiler *flattens* the child controllers to connect state-driven requests
and returned arithmetic results without a combinational hierarchy loop. One
physical arithmetic, bitwise, or comparison datapath is arbitrated round-robin across
all source processes, with one transaction per process. This is a bounded
concurrent lowering, NOT general HLS or a cache-coherent memory system.
"""
from __future__ import annotations
import ast, copy, heapq, random
from .shared_operators import SHARED_BINARY_OPS, resolve_shared_types
from dataclasses import asdict
from .transactional import TransactionalCompiler
from .generator import LogicBuilder
from .diagnostics import IssueCollector
from .ir import Bus, DLS, Node


def _ordered_nodes(nodes, input_widths, registers):
    """Topological gate order across cross-process operator handshakes."""
    sources={'@0','@1'}
    for port,width in input_widths.items():
        sources.update(f'{port}[{j}]' for j in range(width))
    for reg,desc in registers.items():
        sources.update(f'${reg}[{j}]' for j in range(len(desc['next'])))
    by_name={node.name:node for node in nodes}
    if len(by_name)!=len(nodes):raise ValueError('CO.GLOBAL_DUPLICATE_NET: internal node collision')
    dependent={name:[] for name in by_name}; indegree={name:0 for name in by_name}
    for node in nodes:
        for pin in node.inputs:
            if pin in by_name:
                indegree[node.name]+=1;dependent[pin].append(node.name)
            elif pin not in sources:
                raise ValueError(f'CO.GLOBAL_UNCONNECTED: {node.name} requires {pin}')
    queue=[name for name,degree in indegree.items() if degree==0];heapq.heapify(queue)
    ordered=[]
    while queue:
        name=heapq.heappop(queue);ordered.append(by_name[name])
        for follower in dependent[name]:
            indegree[follower]-=1
            if indegree[follower]==0:heapq.heappush(queue,follower)
    if len(ordered)!=len(nodes):
        raise ValueError('CO.GLOBAL_COMBINATIONAL_CYCLE: global wiring introduces a combinational loop')
    return ordered


def compile_global_source_processes(source:str, clients:list, co:dict|None=None,
                                    name='global_source_processes',issues:IssueCollector|None=None)->DLS:
    if not isinstance(name,str) or not name.isidentifier():
        raise ValueError('MCD.PROCESS_NAME: invalid top module name')
    if not isinstance(clients,list) or not 2<=len(clients)<=8:
        raise ValueError('MCD.PROCESS_CLIENTS: require 2..8 named clients')
    config=copy.deepcopy(co or {})
    schedule=config.setdefault('schedule',{})
    shared_memory=schedule.get('global_shared_memory',False)
    if type(shared_memory)!=bool:
        raise ValueError('CO.GLOBAL_MEMORY_SETTING: global_shared_memory must be Boolean')
    if shared_memory and not (config.get('memory') or {}).get('depth'):
        raise ValueError('CO.GLOBAL_MEMORY_SPEC: shared memory needs depth/data_width')
    selection=schedule.get('global_shared_types',[])
    types=(resolve_shared_types(source, clients, selection) if selection else [])
    if not (types or shared_memory):
        raise ValueError('CO.GLOBAL_SHARE_TYPES: no shared operator or memory requested')
    schedule['global_shared_types']=types
    schedule['mode']='transactional'
    tree=ast.parse(source)
    funcs={f.name for f in tree.body if isinstance(f,ast.FunctionDef)}
    seen=set(); children=[]; shared_used=set(); shared_specs={kind:[] for kind in types};memory_specs=[]
    external={'reset':1}; outs={};regs={}; nodes=[];metadata=[]
    # Assemble child netlists with unresolved shared-unit feedback pins. The
    # dependency graph is sorted only after inserting the parent datapath.
    for index,item in enumerate(clients):
        if not isinstance(item,dict) or set(item)!={'name','function'}:
            raise ValueError('MCD.PROCESS_DECLARATION: expected name and function')
        ident,fn=item['name'],item['function']
        if not isinstance(ident,str) or not ident.isidentifier() or ident in seen:
            raise ValueError(f'MCD.PROCESS_DUPLICATE: {ident!r}')
        if not isinstance(fn,str) or fn not in funcs:
            raise ValueError(f'MCD.PROCESS_FUNCTION: unknown {fn!r}')
        seen.add(ident)
        child=TransactionalCompiler(issues,config).compile_source(source,top=fn)
        if child.instances:raise ValueError('CO.GLOBAL_NESTED: nested transactional modules unsupported')
        bindings={}; prefix=f'p_{ident}__'
        def translated(pin):
            if pin in ('@0','@1'):return pin
            if pin.startswith('$'):
                return '$'+prefix+pin[1:]
            if pin in bindings:return bindings[pin]
            if pin.startswith('g') and pin[1:].isdigit():return prefix+pin
            raise ValueError(f'CO.GLOBAL_PIN: {ident} unknown net {pin}')
        for port,width in child.inputs.items():
            if port=='reset':values=['reset[0]']
            elif shared_memory and port=='unit_result_read':
                values=[f'shared_mem_{ident}_result_{j}' for j in range(width)]
            elif port.startswith('unit_result_'):
                kind=port[len('unit_result_'):].upper()
                values=[f'shared_{kind.lower()}_{ident}_result_{j}' for j in range(width)]
            elif shared_memory and port in ('unit_ready_read','unit_ready_write'):
                values=[f'shared_mem_{ident}_grant']
            elif port.startswith('unit_ready_') and port[len('unit_ready_'):].upper() in types:
                kind=port[len('unit_ready_'):].upper()
                values=[f'shared_{kind.lower()}_{ident}_grant']
            else:
                public=ident+'_'+port
                external[public]=width
                values=[f'{public}[{j}]' for j in range(width)]
            for j,pin in enumerate(values):bindings[f'{port}[{j}]']=pin
        for reg,desc in child.registers.items():
            regs[prefix+reg]={'next':[],'init':desc.get('init',0)}
        for n in child.nodes:
            bindings[n.name]=prefix+n.name
        for n in child.nodes:
            nodes.append(Node(prefix+n.name,n.op,[translated(x) for x in n.inputs],n.origin))
        for reg,desc in child.registers.items():
            regs[prefix+reg]['next']=[translated(x) for x in desc['next']]
        for port,pins in child.outputs.items():
            if port.startswith(('unit_request_','unit_a_','unit_b_','unit_mem_')):
                continue
            outs[f'{ident}_{port}']=[translated(pin) for pin in pins]
        for kind in types:
            lower=kind.lower()
            if f'unit_request_{lower}' not in child.outputs:continue
            shared_used.add(kind)
            shared_specs[kind].append({
                'client':ident,
                'request':translated(child.outputs[f'unit_request_{lower}'][0]),
                'a':Bus(tuple(translated(p) for p in child.outputs[f'unit_a_{lower}'])),
                'b':Bus(tuple(translated(p) for p in child.outputs[f'unit_b_{lower}'])),
                'result_width':child.inputs[f'unit_result_{lower}']})
        if shared_memory:
            memory_specs.append({
                'client':ident,'request':translated(child.outputs['unit_request_mem'][0]),
                'write':translated(child.outputs['unit_mem_write'][0]),
                'addr':Bus(tuple(translated(p) for p in child.outputs['unit_mem_addr'])),
                'data':Bus(tuple(translated(p) for p in child.outputs['unit_mem_data']))})
        metadata.append({'client':ident,'function':fn,'instructions':child.metadata['schedule']['instruction_count'],
                         'local_memory':child.metadata['schedule']['memory'],
                         'source_inputs':list({k:v for k,v in child.inputs.items()
                          if k not in ('reset','start','stall') and not k.startswith('unit_')}),
                         'global_shared_types':child.metadata['schedule']['global_shared_types']})
        children.append(child)
    # A declared but unused shared unit is an error rather than a silent no-op.
    if shared_used!=set(types):
        raise ValueError(f'CO.GLOBAL_UNUSED_OPERATOR: no source operation for {sorted(set(types)-shared_used)}')
    if shared_memory and not any(any(c['kind'] in ('READ','WRITE') for c in child.metadata['schedule']['instructions']) for child in children):
        raise ValueError('CO.GLOBAL_UNUSED_MEMORY: no source client reads or writes shared memory')
    b=LogicBuilder(name,external)
    for kind in types:
        entries=shared_specs[kind];n=len(entries)
        wa=max(len(e['a']) for e in entries);wb=max(len(e['b']) for e in entries)
        # One-hot round-robin priority pointer; advances only on a service grant.
        for i in range(n):b.registers[f'rr_{kind.lower()}_{i}']={'next':[],'init':int(i==0)}
        selects=['@0']*n
        for turn in range(n):
            previous='@0'
            for distance in range(n):
                j=(turn+distance)%n
                selected=b.gate('AND',f'$rr_{kind.lower()}_{turn}[0]',
                     b.gate('AND',entries[j]['request'],b.gate('NOT',previous)))
                selects[j]=b.gate('OR',selects[j],selected)
                previous=b.gate('OR',previous,entries[j]['request'])
        grants=[b.gate('AND',x,b.gate('NOT','reset[0]')) for x in selects]
        granted='@0'
        for x in grants:granted=b.gate('OR',granted,x)
        for i in range(n):
            original=f'$rr_{kind.lower()}_{i}[0]'
            new=grants[(i-1)%n]
            nxt=b.gate('MUX',granted,original,new)
            b.registers[f'rr_{kind.lower()}_{i}']['next']=[b.gate('MUX','reset[0]',nxt,'@1' if i==0 else '@0')]
        a=b.const(0,wa);v=b.const(0,wb)
        for e,g in zip(entries,grants):
            a=b.mux(Bus((g,)),a,b.extend(e['a'],wa))
            v=b.mux(Bus((g,)),v,b.extend(e['b'],wb))
        if kind=='ADD':arithmetic=b.add(a,v)
        elif kind=='SUB':arithmetic=b.sub(a,v)
        elif kind=='MUL':arithmetic=b.mul(a,v)
        elif kind in ('AND','OR','XOR'):arithmetic=b.binary_gate(kind,a,v)
        elif kind in ('EQ','NE','LT','LE','GT','GE'):arithmetic=b.compare(kind,a,v)
        else:raise ValueError(f'CO.GLOBAL_SHARE_TYPES: unsupported operator {kind}')
        for e,g in zip(entries,grants):
            outs[f'arb_request_{kind.lower()}_{e["client"]}']=[e['request']]
            outs[f'arb_grant_{kind.lower()}_{e["client"]}']=[g]
            nodes.append(Node(f'shared_{kind.lower()}_{e["client"]}_grant','BUF',[g],'global arbitration'))
            for j,pin in enumerate(b.extend(arithmetic,e['result_width']).bits):
                nodes.append(Node(f'shared_{kind.lower()}_{e["client"]}_result_{j}','BUF',[pin],'global arithmetic result'))
    if shared_memory:
        # One globally shared register bank; round-robin requests from every
        # source FSM. Synchronous reset dominates memory updates and pointer.
        depth=config['memory']['depth'];dw=config['memory']['data_width']
        n=len(memory_specs)
        for i in range(n):b.registers[f'rr_mem_{i}']={'next':[],'init':int(i==0)}
        for j in range(depth):
            b.registers[f'shared_mem_{j}']={'next':[f'$shared_mem_{j}[{k}]' for k in range(dw)],'init':0}
        selects=['@0']*n
        for turn in range(n):
            previous='@0'
            for distance in range(n):
                j=(turn+distance)%n
                choice=b.gate('AND',f'$rr_mem_{turn}[0]',
                      b.gate('AND',memory_specs[j]['request'],b.gate('NOT',previous)))
                selects[j]=b.gate('OR',selects[j],choice)
                previous=b.gate('OR',previous,memory_specs[j]['request'])
        grants=[b.gate('AND',x,b.gate('NOT','reset[0]')) for x in selects]
        serviced='@0'
        for grant in grants:serviced=b.gate('OR',serviced,grant)
        for i in range(n):
            before=f'$rr_mem_{i}[0]'
            rotated=grants[(i-1)%n]
            nxt=b.gate('MUX',serviced,before,rotated)
            b.registers[f'rr_mem_{i}']['next']=[b.gate('MUX','reset[0]',nxt,'@1' if i==0 else '@0')]
        aw=max(len(e['addr']) for e in memory_specs)
        address=b.const(0,aw);write='@0';data=b.const(0,dw)
        for e,grant in zip(memory_specs,grants):
            address=b.mux(Bus((grant,)),address,b.extend(e['addr'],aw))
            write=b.gate('OR',write,b.gate('AND',grant,e['write']))
            data=b.mux(Bus((grant,)),data,b.extend(e['data'],dw))
        valid=b.compare('LT',address,b.const(depth,max(aw,depth.bit_length()))).bits[0]
        read_data=b.const(0,dw)
        for index in reversed(range(depth)):
            same=b.compare('EQ',address,b.const(index,aw)).bits[0]
            read_data=b.mux(Bus((same,)),read_data,
                     Bus(tuple(f'$shared_mem_{index}[{k}]' for k in range(dw))))
            update=b.gate('AND',write,b.gate('AND',valid,same))
            update=b.gate('AND',update,b.gate('NOT','reset[0]'))
            previous=Bus(tuple(f'$shared_mem_{index}[{k}]' for k in range(dw)))
            next_data=b.mux(Bus((update,)),previous,data)
            b.registers[f'shared_mem_{index}']['next']=list(b.mux(Bus(('reset[0]',)),
                 next_data,b.const(0,dw)).bits)
        for e,grant in zip(memory_specs,grants):
            ident=e['client']
            outs[f'arb_request_mem_{ident}']=[e['request']]
            outs[f'arb_grant_mem_{ident}']=[grant]
            outs[f'arb_mem_write_{ident}']=[e['write']]
            outs[f'arb_mem_addr_{ident}']=list(e['addr'].bits)
            outs[f'arb_mem_wdata_{ident}']=list(e['data'].bits)
            outs[f'arb_mem_rdata_{ident}']=list(read_data.bits)
            nodes.append(Node(f'shared_mem_{ident}_grant','BUF',[grant],'global memory arbitration'))
            for j,pin in enumerate(read_data.bits):
                nodes.append(Node(f'shared_mem_{ident}_result_{j}','BUF',[pin],'global memory read result'))
    regs.update(b.registers)
    nodes.extend(b.nodes)
    ordered=_ordered_nodes(nodes,external,regs)
    # Count primitive gates in independently compiled reference modules.
    # Operator sharing need not save *total gates*: control and operand muxing
    # may exceed the saved ALU area for very small words or client counts.
    local_cfg=copy.deepcopy(config)
    local_cfg['schedule'].pop('global_shared_types',None)
    local_cfg['schedule'].pop('global_shared_memory',None)
    unshared_gates=sum(TransactionalCompiler(co=local_cfg).compile_source(source,top=item['function']).stats()['primitive_gates']
                       for item in clients)
    comparison={'shared_primitive_gates':len(ordered),
                'independent_primitive_gates':unshared_gates,
                'delta_shared_minus_independent':len(ordered)-unshared_gates,
                'caution':'Primitive count is not standard-cell area, timing, dynamic power or manufacturing cost.'}
    if len(ordered)>unshared_gates and issues is not None:
        issues.add('CO.GLOBAL_GATE_OVERHEAD','WARNING','CO','scheduling',
            'Shared operators reduce duplicated ALUs, but the current arbitration/muxing uses more primitive gates than isolated processes.',
            evidence=comparison,remedy='Consider larger word widths, more client reuse, or disabling global_shared_types for small designs.')
    d=DLS(name,external,outs,ordered,regs,
       {'kind':'global_source_processes','gate_cost_comparison':comparison,
        'schedule':{'mode':'global_source_processes','clients':len(clients),
         'source_bindings':metadata,'global_shared_types':list(types),
         'operator_selection':('auto' if (co or {}).get('schedule',{}).get('global_shared_types')=='auto' else 'explicit'),
         'shared_physical_units':{**{kind:1 for kind in types},**({'MEMORY':1} if shared_memory else {})},
         'global_shared_memory':shared_memory,
         'shared_memory_depth':config.get('memory',{}).get('depth') if shared_memory else None,
         'shared_memory_data_width':config.get('memory',{}).get('data_width') if shared_memory else None,
         'served_clients':{kind:[e['client'] for e in shared_specs[kind]] for kind in types},
         'arbitration':'per-operation round robin, one completion per unit per clock',
         'max_outstanding_per_client':1,'local_memories':('one shared register bank' if shared_memory else 'independent per process'),
         'assurance':'gate-level functional simulation, not timing or physical verification',
         'limitations':['no AXI arbitration for shared register bank','no multi-outstanding per source FSM',
                        'no variable-latency shared units','only supported binary integer/comparison operators','flattened process hierarchy']}})
    d.validate();return d


def check_global_source_processes(source,design,issues:IssueCollector,rounds=8,seed=91281):
    """Independent AST-reference scoreboard with changing source inputs and stalls."""
    if design.metadata.get('schedule',{}).get('global_shared_memory'):
        from .global_memory_verify import verify_shared_memory
        return verify_shared_memory(source,design,issues,rounds=rounds,seed=seed)
    from .transactional_verify import Reference,MemoryFault
    rng=random.Random(seed)
    clients=design.metadata['schedule']['source_bindings']
    refs={entry['client']:Reference(source,entry['function'],
          (entry['local_memory'] or {}).get('depth',0),
          (entry['local_memory'] or {}).get('data_width',0)) for entry in clients}
    sim=design.new_simulator()
    values={k:0 for k in design.inputs}; values['reset']=1
    sim.step(values); values['reset']=0
    checked=0;traces=[]
    for round_idx in range(rounds):
        expectations={};completed=set();inputs_saved={}
        for entry in clients:
            ident=entry['client'];fn=entry['function']
            args={k:rng.getrandbits(design.inputs[f'{ident}_{k}']) for k in entry['source_inputs']}
            # Keep memory addresses in bounds where a reference process
            # performs reads/writes; faults get their own directed tests.
            for k,val in args.items():values[f'{ident}_{k}']=val
            inputs_saved[ident]=args
            try:expected=refs[ident].step(args)['result'];fault=0
            except MemoryFault:expected=None;fault=1
            except Exception as exc:
                return {'status':'FAIL','reason':f'reference {ident}: {exc}','round':round_idx}
            expectations[ident]=(expected,fault)
            values[f'{ident}_start']=1;values[f'{ident}_stall']=0
            for port in design.inputs:
                if port.startswith(f'{ident}_unit_ready_'):values[port]=1
        # Every client must accept its start in the same clock edge.
        probe=sim.step(values,clock=False)
        if any(probe[f'{e["client"]}_ready']!=1 for e in clients):
            return {'status':'FAIL','reason':'source process not idle on new batch','round':round_idx}
        sim.step(values)
        for entry in clients:values[entry['client']+'_start']=0
        max_edges=600
        for edge in range(max_edges):
            stall=(edge>0 and edge%17==0)
            values.update({entry['client']+'_stall':int(stall) for entry in clients})
            for entry in clients:
                ident=entry['client']
                for key in entry['source_inputs']:
                    values[f'{ident}_{key}']=rng.getrandbits(design.inputs[f'{ident}_{key}'])
            previous=sim.register_snapshot() if stall else None
            sim.step(values)
            if stall and sim.register_snapshot()!=previous:
                return {'status':'FAIL','reason':'registers changed on stall','round':round_idx,'edge':edge}
            post=sim.step(values,clock=False)
            for kind,names in design.metadata['schedule']['served_clients'].items():
                grants=sum(post[f'arb_grant_{kind.lower()}_{name}'] for name in names)
                if grants>1:
                    return {'status':'FAIL','reason':'multiple grants to one physical unit',
                            'round':round_idx,'edge':edge,'unit':kind}
            for entry in clients:
                ident=entry['client']
                if ident in completed or not post[ident+'_done']:continue
                expected,fault=expectations[ident]
                if post[ident+'_fault']!=fault or (not fault and post[ident+'_result']!=expected):
                    return {'status':'FAIL','reason':'source result mismatch','round':round_idx,
                        'edge':edge,'client':ident,'inputs':inputs_saved[ident],
                        'expected':{'result':expected,'fault':fault},
                        'actual':{'result':post[ident+'_result'],'fault':post[ident+'_fault']}}
                completed.add(ident);checked+=1
            if len(completed)==len(clients):break
        else:
            return {'status':'FAIL','reason':'bounded completion exceeded','round':round_idx,
                    'completed':sorted(completed),'snapshot':sim.register_snapshot()}
        # Clear DONE before sending a fresh batch.
        for entry in clients:values[entry['client']+'_stall']=0
        sim.step(values)
        traces.append({'round':round_idx,'cycles':edge+1})
    issues.add('VERIFY.GLOBAL_SAMPLED','WARNING','VERIFIER','equivalence',
               'Global source processes passed independent sampled AST-reference checks; not formal equivalence.',
               evidence={'seed':seed,'transactions':checked})
    return {'status':'PASS','seed':seed,'rounds':rounds,'completed_transactions':checked,
            'shared_physical_units':design.metadata['schedule']['shared_physical_units'],
            'verification':'sampled AST reference; stalls, concurrent contention and input snapshots',
            'round_cycles':traces}
