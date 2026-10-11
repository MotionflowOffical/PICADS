"""Reusable round-robin shared-resource arbitration in executable DLS.

A generic *logical* arbitration component: clients assert request_i and a
payload; the selected client remains stable while resource_ready=0 only if
requesters hold their requests/payloads (valid/ready contract). grant_i is
an accepted transaction pulse. One winner maximum on any edge. This module
is not automatically inserted across unrelated hierarchical MCD instances.
"""
from __future__ import annotations
from .generator import LogicBuilder
from .ir import Bus,DLS

def round_robin_arbiter(clients:int,payload_width:int=8,name:str='round_robin') -> DLS:
    if type(clients)!=int or not 2<=clients<=8:
        raise ValueError('clients must be integer 2..8')
    if type(payload_width)!=int or not 1<=payload_width<=128:
        raise ValueError('payload_width must be integer 1..128')
    if not name.isidentifier():raise ValueError('Invalid module name')
    ports={'resource_ready':1,'stall':1,'reset':1}
    for i in range(clients):ports[f'request_{i}']=1;ports[f'payload_{i}']=payload_width
    b=LogicBuilder(name,ports)
    def gate(kind,*p):return b.gate(kind,*p)
    def and_(a,c):return gate('AND',a,c)
    def or_(a,c):return gate('OR',a,c)
    def not_(x):return gate('NOT',x)
    for i in range(clients):
        b.registers[f'turn_{i}']={'next':[f'$turn_{i}[0]'],'init':int(i==0)}
    # Each priority rotation chooses the first asserted request in circular order.
    selections=['@0']*clients
    for turn in range(clients):
        preceding='@0'
        for offset in range(clients):
            idx=(turn+offset)%clients
            candidate=and_(f'$turn_{turn}[0]',and_(f'request_{idx}[0]',not_(preceding)))
            selections[idx]=or_(selections[idx],candidate)
            preceding=or_(preceding,f'request_{idx}[0]')
    valid='@0'
    for sel in selections:valid=or_(valid,sel)
    allowed=and_('resource_ready[0]',and_(not_('stall[0]'),not_('reset[0]')))
    grants=[and_(selected,allowed) for selected in selections]
    next_turn=[]
    accepted='@0'
    for gr in grants:accepted=or_(accepted,gr)
    for i in range(clients):
        old=f'$turn_{i}[0]'
        new=grants[(i-1)%clients]
        b.registers[f'turn_{i}']['next']=[gate('MUX',accepted,old,new)]
    for i in range(clients):
        current=b.registers[f'turn_{i}']['next'][0]
        b.registers[f'turn_{i}']['next']=[gate('MUX','reset[0]',current,'@1' if i==0 else '@0')]
    data=b.const(0,payload_width)
    for i,selected in enumerate(selections):
        payload=Bus(tuple(f'payload_{i}[{j}]' for j in range(payload_width)))
        data=b.mux(Bus((selected,)),data,payload)
    index_width=max(1,(clients-1).bit_length())
    idx=b.const(0,index_width)
    for i,sel in enumerate(selections):idx=b.mux(Bus((sel,)),idx,b.const(i,index_width))
    out={'resource_valid':[and_(valid,and_(not_('stall[0]'),not_('reset[0]')))],
         'selected_payload':list(data.bits),'selected_client':list(idx.bits)}
    out.update({f'grant_{i}':[g] for i,g in enumerate(grants)})
    dls=DLS(name,ports,out,b.nodes,b.registers,
        {'kind':'round_robin_arbiter','clients':clients,'payload_width':payload_width,
         'protocol':'Synchronous active-high RESET; clients hold request and payload while resource_ready=0; grants fire on ready & !stall & !reset; pointer advances after grant; no queue or transfer buffering.',
         'auto_network_insertion':False,'strategies':{}})
    dls.validate()
    return dls
