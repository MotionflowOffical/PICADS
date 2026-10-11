"""Clocked, gate-level, bounded multi-client resource fabric.

This is an independently composable concurrent *resource scheduler*, not a
compiler for arbitrary concurrently executing C/Python threads. Every client
has one request slot, one response slot and an in-flight ownership bit. ALU
and memory each have an independent arbitration domain; ALU may use a real
external ready/valid operator or built-in combinational Boolean logic.

All state, arbitration, storage and datapath muxes are ordinary DLS gate
nodes/flip-flops, so DLS and exported structural Verilog have the same circuit.
"""
from __future__ import annotations
from dataclasses import dataclass
from .generator import LogicBuilder
from .ir import Bus,DLS


@dataclass(frozen=True)
class FabricConfig:
    clients:int=3
    width:int=8
    depth:int=8
    operator:str='builtin'  # builtin or external

    def validate(self):
        if type(self.clients)!=int or not 2<=self.clients<=8:
            raise ValueError('CO.FABRIC_CLIENTS: clients must be integer 2..8')
        if type(self.width)!=int or not 1<=self.width<=16:
            raise ValueError('CO.FABRIC_WIDTH: width must be integer 1..16')
        if type(self.depth)!=int or not 1<=self.depth<=32:
            raise ValueError('CO.FABRIC_DEPTH: depth must be integer 1..32')
        if self.operator not in ('builtin','external'):
            raise ValueError('CO.FABRIC_OPERATOR: operator must be builtin or external')


def concurrent_fabric(config:FabricConfig=FabricConfig(),name:str='concurrent_fabric')->DLS:
    config.validate()
    if not name.isidentifier():raise ValueError('CO.FABRIC_NAME: invalid top-level module name')
    n,w,depth=config.clients,config.width,config.depth
    # opcode: 0=ADD, 1=MUL (truncated to width), 2=READ, 3=WRITE.
    ports={'stall':1,'reset':1}
    for i in range(n):
        ports.update({f'request_{i}':1,f'opcode_{i}':2,f'a_{i}':w,f'b_{i}':w,
                      f'response_ready_{i}':1})
    if config.operator=='external':
        ports.update({'operator_request_ready':1,'operator_response_valid':1,
                      'operator_response_data':w})
    b=LogicBuilder(name,ports)
    def bit(p):return Bus((p,))
    def data(p,sz):return Bus(tuple(f'{p}[{j}]' for j in range(sz)))
    def rb(p,sz):return Bus(tuple(f'${p}[{j}]' for j in range(sz)))
    def g(op,*x):return b.gate(op,*x)
    def inv(x):return g('NOT',x)
    def AND(*xs):
        r='@1'
        for x in xs:r=g('AND',r,x)
        return r
    def OR(*xs):
        r='@0'
        for x in xs:r=g('OR',r,x)
        return r
    def sel(s,a,c):return b.mux(bit(s),a,c)
    def reg(name,width=1,init=0):
        b.registers[name]={'next':list(rb(name,width).bits),'init':init}
        return rb(name,width)
    def set_reg(name,value,enable):
        old=rb(name,len(b.registers[name]['next']))
        b.registers[name]['next']=list(sel(enable,Bus(tuple(b.registers[name]['next'])),value).bits)
    def set_bit(name,value,enable):set_reg(name,bit(value),enable)
    def set_reset():
        # The common synchronous reset dominates every other transition.
        for reg_name,desc in b.registers.items():
            desc['next']=list(sel('reset[0]',Bus(tuple(desc['next'])),
                                  b.const(desc['init'],len(desc['next']))).bits)
    def equal(a,c):return b.compare('EQ',a,c).bits[0]

    # Each client may have at most one outstanding request. Requests accepted
    # while the operator is busy are buffered, not silently dropped.
    for i in range(n):
        for k,sz in [('pending',1),('active',1),('response_valid',1),('response_fault',1),
                     ('opcode',2),('operand_a',w),('operand_b',w),('response_data',w)]:
            reg(f'{k}_{i}',sz)
    reg('alu_busy')
    for i in range(n):reg(f'alu_owner_{i}')
    # Latched offer ensures the outgoing valid/payload never switches to a
    # newly arrived higher-priority client during external backpressure.
    for i in range(n):reg(f'alu_offer_{i}')
    for i in range(n):reg(f'alu_turn_{i}',init=int(i==0));reg(f'mem_turn_{i}',init=int(i==0))
    for j in range(depth):reg(f'memory_{j}',w)
    if config.operator=='builtin':reg('builtin_valid');reg('builtin_result',w)

    unstalled=AND(inv('stall[0]'),inv('reset[0]'))
    outputs={}
    accepted=[];consume=[]
    for i in range(n):
        vacant=AND(inv(f'$pending_{i}[0]'),inv(f'$active_{i}[0]'),inv(f'$response_valid_{i}[0]'))
        ready=AND(vacant,unstalled)
        take=AND(ready,f'request_{i}[0]')
        accepted.append(take)
        consume.append(AND(f'$response_valid_{i}[0]',f'response_ready_{i}[0]',unstalled))
        outputs[f'request_ready_{i}']=[ready]
        outputs[f'request_accepted_{i}']=[take]
        outputs[f'response_accepted_{i}']=[consume[i]]
        outputs[f'response_valid_{i}']=[f'$response_valid_{i}[0]']
        outputs[f'response_data_{i}']=list(rb(f'response_data_{i}',w).bits)
        outputs[f'response_fault_{i}']=[f'$response_fault_{i}[0]']
        # Capture request exactly once. Cannot accept until response is drained.
        set_reg(f'opcode_{i}',data(f'opcode_{i}',2),take)
        set_reg(f'operand_a_{i}',data(f'a_{i}',w),take)
        set_reg(f'operand_b_{i}',data(f'b_{i}',w),take)

    # Two independent service ports share no mutable resource other than
    # client ownership flags. A pending client belongs to exactly one port.
    pending_alu=[];pending_mem=[]
    for i in range(n):
        opcode=rb(f'opcode_{i}',2)
        hi=opcode.bits[1]
        pending_alu.append(AND(f'$pending_{i}[0]',inv(hi)))
        pending_mem.append(AND(f'$pending_{i}[0]',hi))

    def choose_rr(reqs,turnprefix):
        winner=['@0']*n
        for turn in range(n):
            earlier='@0'
            for offset in range(n):
                i=(turn+offset)%n
                valid=AND(f'${turnprefix}_{turn}[0]',reqs[i],inv(earlier))
                winner[i]=OR(winner[i],valid)
                earlier=OR(earlier,reqs[i])
        return winner

    def advance_rr(prefix,grants):
        any_grant=OR(*grants)
        for i in range(n):
            # Next client after the last accepted grant.
            set_bit(f'{prefix}_{i}',grants[(i-1)%n],any_grant)

    # ALU arbitration. Selection is locked into offer bits before presenting
    # an external VALID. This is a ready/valid protocol, not a timer pretending
    # to be variable-latency hardware.
    alu_select=choose_rr(pending_alu,'alu_turn')
    has_offer=OR(*(f'$alu_offer_{i}[0]' for i in range(n)))
    offer_new=AND(inv('$alu_busy[0]'),inv(has_offer),unstalled)
    for i in range(n):set_bit(f'alu_offer_{i}','@1',AND(offer_new,alu_select[i]))
    operator_valid=AND(has_offer,inv('$alu_busy[0]'),unstalled)
    if config.operator=='external':accept_ready='operator_request_ready[0]'
    else:accept_ready='@1'
    issue=AND(operator_valid,accept_ready)
    alu_accept=[AND(issue,f'$alu_offer_{i}[0]') for i in range(n)]
    for i in range(n):
        outputs[f'operator_grant_{i}']=[alu_accept[i]]
        set_bit(f'alu_offer_{i}','@0',alu_accept[i])
    advance_rr('alu_turn',alu_accept)
    sel_opcode=b.const(0,2);sel_a=b.const(0,w);sel_b=b.const(0,w)
    for i in range(n):
        offered=f'$alu_offer_{i}[0]'
        sel_opcode=sel(offered,sel_opcode,rb(f'opcode_{i}',2))
        sel_a=sel(offered,sel_a,rb(f'operand_a_{i}',w))
        sel_b=sel(offered,sel_b,rb(f'operand_b_{i}',w))
    outputs['operator_request_valid']=[operator_valid]
    outputs['operator_request_opcode']=list(sel_opcode.bits)
    outputs['operator_request_a']=list(sel_a.bits)
    outputs['operator_request_b']=list(sel_b.bits)
    if config.operator=='builtin':
        is_mul=sel_opcode.bits[0]
        result=sel(is_mul,b.add(sel_a,sel_b,forced_width=w),b.extend(b.mul(sel_a,sel_b),w))
        set_reg('builtin_result',result,issue)
        # Backend receives a registered request and completes on a later edge.
        set_bit('builtin_valid','@1',issue)
        # Responses stay asserted through stalls until consumed.
        operator_response_valid='$builtin_valid[0]'
        operator_response_data=rb('builtin_result',w)
    else:
        operator_response_valid='operator_response_valid[0]'
        operator_response_data=data('operator_response_data',w)
    op_response_ready=AND('$alu_busy[0]',unstalled)
    alu_complete=AND(op_response_ready,operator_response_valid)
    outputs['operator_response_ready']=[op_response_ready]
    if config.operator=='external':
        outputs['operator_reset']=['reset[0]']
        # Debug signal: external unit violates protocol by sending a response
        # when there is no outstanding request (no slot to accept it).
        outputs['operator_unsolicited_response']=[AND('operator_response_valid[0]',inv('$alu_busy[0]'),inv('reset[0]'))]
    set_bit('alu_busy','@1',issue)
    set_bit('alu_busy','@0',alu_complete)
    if config.operator=='builtin':set_bit('builtin_valid','@0',alu_complete)
    for i in range(n):
        set_bit(f'alu_owner_{i}','@1',alu_accept[i])
        set_bit(f'alu_owner_{i}','@0',alu_complete)

    # A single fair memory port, one read or write at most per clock.
    mem_select=choose_rr(pending_mem,'mem_turn')
    mem_grants=[AND(mem_select[i],unstalled) for i in range(n)]
    advance_rr('mem_turn',mem_grants)
    for i in range(n):outputs[f'memory_grant_{i}']=[mem_grants[i]]
    memory_value=[];memory_fault=[]
    for i in range(n):
        addr=rb(f'operand_a_{i}',w)
        valid=b.compare('LT',b.extend(addr,max(w,depth.bit_length()+1)),
                        b.const(depth,max(w,depth.bit_length()+1))).bits[0]
        memory_fault.append(inv(valid))
        result=b.const(0,w)
        for j in reversed(range(depth)):
            at=equal(addr,b.const(j,w))
            result=sel(at,result,rb(f'memory_{j}',w))
        memory_value.append(result)
        writing=rb(f'opcode_{i}',2).bits[0]
        for j in range(depth):
            on_address=equal(addr,b.const(j,w))
            write=AND(mem_grants[i],writing,valid,on_address)
            set_reg(f'memory_{j}',rb(f'operand_b_{i}',w),write)

    for i in range(n):
        memory_done=mem_grants[i]
        alu_done=AND(alu_complete,f'$alu_owner_{i}[0]')
        dispatch=OR(mem_grants[i],alu_accept[i])
        # Independent transactions are in-flight across different clients.
        # A client cannot be both an ALU and memory dispatch in the same edge.
        set_bit(f'pending_{i}','@1',accepted[i])
        set_bit(f'pending_{i}','@0',dispatch)
        set_bit(f'active_{i}','@1',alu_accept[i])
        set_bit(f'active_{i}','@0',alu_done)
        finish=OR(memory_done,alu_done)
        set_bit(f'response_valid_{i}','@1',finish)
        set_bit(f'response_valid_{i}','@0',consume[i])
        set_bit(f'response_fault_{i}',memory_fault[i],memory_done)
        set_bit(f'response_fault_{i}','@0',alu_done)
        write=rb(f'opcode_{i}',2).bits[0]
        mv=sel(write,memory_value[i],b.const(0,w))
        set_reg(f'response_data_{i}',mv,memory_done)
        set_reg(f'response_data_{i}',operator_response_data,alu_done)
        outputs[f'pending_{i}']=[f'$pending_{i}[0]']
        outputs[f'active_{i}']=[f'$active_{i}[0]']
    outputs['memory_issue']=[OR(*mem_grants)]
    outputs['operator_busy']=['$alu_busy[0]']
    set_reset()
    meta={'kind':'concurrent_resource_fabric',
          'schedule':{'mode':'concurrent_fabric','clients':n,'operator':config.operator,
                      'separate_parallel_ports':['operator','memory'],
                      'pending_capacity_per_client':1,'response_capacity_per_client':1,
                      'memory_ports':1,'memory_depth':depth,'width':w,
                      'variable_latency':'external ready/valid response' if config.operator=='external' else 'builtin single-stage result register',
                      'protocol':'Synchronous reset, one outstanding per client; input accepted on request && request_ready, response held until response_ready; independent fair operator and memory ports; stall freezes all state and suppresses external handshakes. External unit must honor operator_reset.'},
          'strategies':b.strategies,'verification':'Requires protocol/transaction-level testing; source-equivalence not applicable to a service fabric.'}
    dls=DLS(name,ports,outputs,b.nodes,b.registers,meta)
    dls.validate()
    return dls
