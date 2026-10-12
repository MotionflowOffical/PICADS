"""Synthesizable, per-client multi-outstanding tagged transaction adapter.

The adapter multiplexes each physical client onto independent virtual clients
of the v0.8 resource fabric. Slots own their tags until the corresponding
response handshakes. No two outstanding requests from a client may use the
same tag. Responses may complete out of submission order; tags identify them.

This is a bounded hardware fabric rather than general HLS/concurrent-thread
synthesis. It uses only primitive DLS gates, registers, and a clocked child.
"""
from dataclasses import dataclass
from .concurrent import FabricConfig, concurrent_fabric
from .generator import LogicBuilder
from .ir import Bus,DLS

@dataclass(frozen=True)
class TaggedFabricConfig:
    clients:int=2
    slots_per_client:int=2
    width:int=4
    depth:int=4
    tag_width:int=4
    operator:str='builtin'
    memory_backend:str='builtin'

    def validate(self):
        if type(self.clients) is not int or not 2<=self.clients<=8:
            raise ValueError('CO.TAGGED_CLIENTS: clients must be 2..8')
        if type(self.slots_per_client) is not int or not 1<=self.slots_per_client<=4:
            raise ValueError('CO.TAGGED_SLOTS: slots_per_client must be 1..4')
        if self.clients*self.slots_per_client>8:
            raise ValueError('CO.TAGGED_VIRTUAL_LIMIT: clients * slots_per_client must not exceed 8')
        if type(self.tag_width) is not int or not 1<=self.tag_width<=16:
            raise ValueError('CO.TAGGED_WIDTH: tag_width must be 1..16')
        if 1<<self.tag_width<self.slots_per_client:
            raise ValueError('CO.TAGGED_TAG_SPACE: tag width must distinguish all outstanding slots')
        FabricConfig(self.clients*self.slots_per_client,self.width,self.depth,self.operator,self.memory_backend).validate()


def tagged_fabric(config:TaggedFabricConfig=TaggedFabricConfig(),name='tagged_resource_fabric')->DLS:
    config.validate()
    if not isinstance(name,str) or not name.isidentifier():
        raise ValueError('CO.TAGGED_NAME: invalid module name')
    n,s,w,t=config.clients,config.slots_per_client,config.width,config.tag_width
    child_name='shared_resource_core'
    child=concurrent_fabric(FabricConfig(n*s,w,config.depth,config.operator,config.memory_backend),child_name)
    ports={'stall':1,'reset':1}
    for i in range(n):
        ports.update({f'request_{i}':1,f'request_tag_{i}':t,f'opcode_{i}':2,
                      f'a_{i}':w,f'b_{i}':w,f'response_ready_{i}':1})
    if config.operator=='external':
        ports.update({'operator_request_ready':1,'operator_response_valid':1,
                      'operator_response_data':w})
    if config.memory_backend=='external':
        ports.update({'memory_request_ready':1,'memory_response_valid':1,
                      'memory_response_data':w,'memory_response_fault':1})
    b=LogicBuilder(name,ports)
    def bit(x):return Bus((x,))
    def io(key,width):return Bus(tuple(f'{key}[{j}]' for j in range(width)))
    def r(name,width=1):return Bus(tuple(f'${name}[{j}]' for j in range(width)))
    def gate(op,*pins):return b.gate(op,*pins)
    def neg(x):return gate('NOT',x)
    def AND(*values):
        acc='@1'
        for value in values:acc=gate('AND',acc,value)
        return acc
    def OR(*values):
        acc='@0'
        for value in values:acc=gate('OR',acc,value)
        return acc
    def mux(s,a,c):return b.mux(bit(s),a,c)
    def reg(key,width=1,init=0):
        b.registers[key]={'next':list(r(key,width).bits),'init':init}
    def update(key,value,condition):
        old=Bus(tuple(b.registers[key]['next']))
        b.registers[key]['next']=list(mux(condition,old,value).bits)
    def update_bit(key,value,condition):update(key,bit(value),condition)

    active=AND(neg('stall[0]'),neg('reset[0]'))
    inner_inputs={'stall':['stall[0]'],'reset':['reset[0]']}
    if config.operator=='external':
        for key in ('operator_request_ready','operator_response_valid','operator_response_data'):
            inner_inputs[key]=list(io(key,child.inputs[key]).bits)
    if config.memory_backend=='external':
        for key in ('memory_request_ready','memory_response_valid','memory_response_data','memory_response_fault'):
            inner_inputs[key]=list(io(key,child.inputs[key]).bits)
    outputs={}
    take_by_slot={}
    # Parent-owned occupancy and tag state must be declared before use in
    # combinational grant logic; state updates are completed after child pins.
    for i in range(n):
        for k in range(s):
            reg(f'occupied_{i}_{k}')
            reg(f'tag_{i}_{k}',t)
            reg(f'locked_{i}_{k}')
            reg(f'turn_{i}_{k}',init=int(k==0))
    for i in range(n):
        tag=io(f'request_tag_{i}',t)
        duplicate=OR(*(AND(f'$occupied_{i}_{k}[0]',
                            b.compare('EQ',r(f'tag_{i}_{k}',t),tag).bits[0]) for k in range(s)))
        available=[neg(f'$occupied_{i}_{k}[0]') for k in range(s)]
        has_room=OR(*available)
        ready=AND(active,has_room,neg(duplicate))
        take=AND(ready,f'request_{i}[0]')
        outputs[f'request_ready_{i}']=[ready]
        outputs[f'request_accepted_{i}']=[take]
        outputs[f'duplicate_tag_{i}']=[duplicate]
        outputs[f'outstanding_{i}']=[f'$occupied_{i}_{k}[0]' for k in range(s)]
        earlier='@0'
        for k in range(s):
            select=AND(take,available[k],neg(earlier))
            earlier=OR(earlier,available[k])
            take_by_slot[i,k]=select
            inner=i*s+k
            inner_inputs[f'request_{inner}']=[select]
            for port,width in [('opcode',2),('a',w),('b',w)]:
                inner_inputs[f'{port}_{inner}']=list(io(f'{port}_{i}',width).bits)
            # Response handshake is based only on locked state and external
            # ready. It MUST NOT depend combinationally on child output valid.
            inner_inputs[f'response_ready_{inner}']=[AND(f'$locked_{i}_{k}[0]',
                                                        f'response_ready_{i}[0]',active)]
            update_bit(f'occupied_{i}_{k}','@1',select)
            update(f'tag_{i}_{k}',tag,select)

    # The child instance is inserted *after* all the pre-instance input-gates.
    # Later gates can consume only its declared output wires. This produces a
    # valid topological DLS and a structural Verilog module hierarchy.
    missing=set(child.inputs)-set(inner_inputs)
    if missing:raise ValueError(f'Internal wrapper bug: unbound child inputs {missing}')
    wired={p:[f'core_{p}_{j}' for j in range(len(bits))] for p,bits in child.outputs.items()}
    b.submodules[child_name]=child
    b.instances.append({'name':'core','module':child_name,'at':len(b.nodes),
                        'inputs':inner_inputs,'outputs':wired})
    def childbit(key):return wired[key][0]
    def childbus(key):return Bus(tuple(wired[key]))

    for i in range(n):
        # Response selection uses a sticky one-hot lock. A newly completed
        # earlier-indexed transaction cannot change an already offered payload.
        locked=[f'$locked_{i}_{k}[0]' for k in range(s)]
        unowned=neg(OR(*locked))
        pending=[AND(f'$occupied_{i}_{k}[0]',childbit(f'response_valid_{i*s+k}')) for k in range(s)]
        grants=['@0']*s
        for turn in range(s):
            preceding='@0'
            for offset in range(s):
                k=(turn+offset)%s
                eligible=AND(f'$turn_{i}_{turn}[0]',pending[k],neg(preceding))
                grants[k]=OR(grants[k],eligible)
                preceding=OR(preceding,pending[k])
        response_valid=OR(*(AND(locked[k],childbit(f'response_valid_{i*s+k}')) for k in range(s)))
        consumed=AND(response_valid,f'response_ready_{i}[0]',active)
        outputs[f'response_valid_{i}']=[response_valid]
        outputs[f'response_accepted_{i}']=[consumed]
        out_data=b.const(0,w);out_tag=b.const(0,t);out_fault='@0'
        for k in range(s):
            slot=AND(locked[k],childbit(f'response_valid_{i*s+k}'))
            out_data=mux(slot,out_data,childbus(f'response_data_{i*s+k}'))
            out_tag=mux(slot,out_tag,r(f'tag_{i}_{k}',t))
            out_fault=OR(out_fault,AND(slot,childbit(f'response_fault_{i*s+k}')))
            update_bit(f'locked_{i}_{k}','@1',AND(unowned,active,grants[k]))
            released=AND(consumed,locked[k])
            update_bit(f'locked_{i}_{k}','@0',released)
            update_bit(f'occupied_{i}_{k}','@0',released)
            # After a consumed response, start search at next slot.
            update_bit(f'turn_{i}_{k}',locked[(k-1)%s],consumed)
            outputs[f'slot_response_valid_{i}_{k}']=[pending[k]]
        outputs[f'response_data_{i}']=list(out_data.bits)
        outputs[f'response_tag_{i}']=list(out_tag.bits)
        outputs[f'response_fault_{i}']=[out_fault]

    # Export the real variable latency operator interface, if configured.
    for key in ('operator_request_valid','operator_request_opcode','operator_request_a',
                'operator_request_b','operator_response_ready','operator_busy','memory_issue'):
        outputs[key]=wired[key]
    if config.operator=='external':
        for key in ('operator_reset','operator_unsolicited_response'):
            outputs[key]=wired[key]
    if config.memory_backend=='external':
        for key in ('memory_request_valid','memory_request_write','memory_request_address',
                    'memory_request_data','memory_response_ready','memory_busy',
                    'memory_reset','memory_unsolicited_response'):
            outputs[key]=wired[key]

    # Hardware reset (not merely simulator init) dominates next-state logic.
    for key,desc in b.registers.items():
        desc['next']=list(mux('reset[0]',Bus(tuple(desc['next'])),
                              b.const(desc['init'],len(desc['next']))).bits)
    meta={'kind':'tagged_concurrent_fabric','schedule':{
        'mode':'tagged_fabric','clients':n,'slots_per_client':s,
        'max_outstanding_per_client':s,'max_outstanding_total':n*s,
        'tag_width':t,'response_order':'tagged, completion order; not necessarily submission order',
        'duplicate_tag':'rejected while tag belongs to outstanding request',
        'operator':config.operator,'memory_ports':1,'memory_depth':config.depth,
        'memory_backend':config.memory_backend,
        'protocol':'One ingress and egress handshake per physical client per cycle; '
                   'independent tagged slots, sticky buffered responses, synchronous reset and stall.'},
        'verification':'Requires independent tagged transaction scoreboard; fabrication checks are external.'}
    d=DLS(name,ports,outputs,b.nodes,b.registers,meta,b.instances,b.submodules)
    d.validate()
    return d
