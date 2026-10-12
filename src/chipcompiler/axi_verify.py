"""Independent directed AXI4-Lite protocol check against executable DLS.

This verifies real pin handshakes and completed tagged transactions; it is not
formal AXI compliance, not an independent RTL simulation, and not signoff.
"""
from __future__ import annotations
from .ir import DLSSimulator,DLS


def check_axi_lite_protocol(design:DLS,tagged:bool=False,timeout:int=100)->dict:
    sim=DLSSimulator(design)
    signals={k:0 for k in design.inputs}
    trace=[];checks=0
    def tick(**updates):
        nonlocal checks
        signals.update(updates)
        result=sim.step(signals)
        checks+=1
        trace.append({'cycle':sim.cycle-1,'inputs':{k:v for k,v in updates.items() if v},
                      'outputs':{k:result[k] for k in ('axi_awvalid','axi_wvalid','axi_bready',
                          'axi_arvalid','axi_rready','axi_awaddr','axi_wdata','axi_wstrb',
                          'memory_response_valid' if not tagged else 'response_valid_0') if k in result}})
        return result
    def until(pred,why):
        for _ in range(timeout):
            out=tick()
            if pred(out):return out
        raise AssertionError(f'Timed out awaiting {why}')
    def expect(x,message):
        if not x:raise AssertionError(message)
    try:
        tick(reset=1);tick(reset=0)
        def submit(write,tag,address,value):
            kw=({'request_0':1,'opcode_0':3 if write else 2,'request_tag_0':tag,
                 'a_0':address,'b_0':value,'response_ready_0':0} if tagged else
                {'memory_request_valid':1,'memory_request_write':int(write),
                 'memory_request_address':address,'memory_request_data':value,'memory_response_ready':0})
            for _ in range(timeout):
                out=tick(**kw)
                if out['request_accepted_0' if tagged else 'memory_request_accepted']:
                    tick(**{'request_0':0} if tagged else {'memory_request_valid':0})
                    return
            raise AssertionError('Request was never accepted')
        submit(True,1,2,9)
        o=until(lambda o:o['axi_awvalid'] and o['axi_wvalid'],'write AW and W')
        expect(o['axi_awaddr']==8 and o['axi_wdata']==9,'AXI write payload wrong')
        width=(len(design.outputs['response_data_0']) if tagged else len(design.outputs['memory_response_data']))
        expect(o['axi_wstrb']==(1<<((width+7)//8))-1,'AXI byte strobe wrong')
        for _ in range(3):
            z=tick()
            expect(z['axi_awvalid'] and z['axi_wvalid'] and z['axi_awaddr']==8 and z['axi_wdata']==9,
                   'write offer changed during backpressure')
        tick(axi_awready=1)
        o=tick(axi_awready=0)
        expect(not o['axi_awvalid'] and o['axi_wvalid'],'AW acceptance did not release AW independently')
        tick(axi_wready=1)
        o=tick(axi_wready=0)
        expect(o['axi_bready']==1 and not o['axi_wvalid'],'B channel not waiting after AW/W')
        tick(axi_bvalid=1,axi_bresp=2)
        o=tick(axi_bvalid=0,axi_bresp=0)
        until(lambda o:o['response_valid_0' if tagged else 'memory_response_valid'],'write response') if not o['response_valid_0' if tagged else 'memory_response_valid'] else None
        out=sim.last_outputs
        expect(out['response_fault_0' if tagged else 'memory_response_fault']==1,'AXI write error not propagated')
        expect(out['response_tag_0']==1,'Tagged write response ownership lost') if tagged else None
        for _ in range(2):
            out=tick()
            expect(out['response_valid_0' if tagged else 'memory_response_valid']==1,'response disappeared under backpressure')
        tick(**{'response_ready_0':1} if tagged else {'memory_response_ready':1})
        until(lambda o:not o['response_valid_0' if tagged else 'memory_response_valid'],'write completion pop')
        tick(**{'response_ready_0':0} if tagged else {'memory_response_ready':0})
        submit(False,2,3,0)
        o=until(lambda o:o['axi_arvalid'],'read AR')
        expect(o['axi_araddr']==12,'AXI read address not word-mapped')
        for _ in range(2):
            o=tick()
            expect(o['axi_arvalid'] and o['axi_araddr']==12,'read address changed under backpressure')
        tick(axi_arready=1)
        o=tick(axi_arready=0)
        expect(o['axi_rready']==1 and not o['axi_arvalid'],'AR acceptance did not enable R')
        tick(axi_rvalid=1,axi_rdata=0xABCD,axi_rresp=0)
        o=tick(axi_rvalid=0,axi_rdata=0)
        if not o['response_valid_0' if tagged else 'memory_response_valid']:
            o=until(lambda o:o['response_valid_0' if tagged else 'memory_response_valid'],'read response')
        width=(len(design.outputs['response_data_0']) if tagged else
               len(design.outputs['memory_response_data']))
        expect(o['response_data_0' if tagged else 'memory_response_data']==(0xABCD&((1<<width)-1)),
               'read data corrupted or wrong bit order')
        expect(o['response_fault_0' if tagged else 'memory_response_fault']==0,'spurious read error')
        if tagged:expect(o['response_tag_0']==2,'Tagged read response ownership lost')
        return {'status':'PASS','checks':checks,'scenarios':['write AW/W independent handshakes',
            'stable AXI payload under backpressure','SLVERR propagation','buffered write response',
            'read address channel','read data truncation','tag ownership' if tagged else 'memory service response'],
            'protocol':'AXI4-Lite (bounded, 32-bit, one bus transaction at a time)'}
    except (AssertionError,ValueError,KeyError) as exc:
        return {'status':'FAIL','checks':checks,'reason':str(exc),'counterexample':trace[-35:]}


def randomized_axi_lite_check(design:DLS,tagged:bool=False,seed:int=17011,
                              transactions:int=12,max_cycles:int=1800)->dict:
    """Independent finite AXI4-Lite slave with randomized ready/valid stalls.

    Checks values, errors, tag ownership, stable offers and completed handshakes.
    The reference slave stores its own data; it never reads DLS registers.
    """
    import random
    rng=random.Random(seed);sim=DLSSimulator(design)
    ports={k:0 for k in design.inputs}
    width=len(design.outputs['response_data_0' if tagged else 'memory_response_data'])
    mask=(1<<width)-1
    memory={};aw=None;w=None;b=None;r=None
    stream=[];accepted=False;finished=0;hold={};check_count=0
    operations=[]
    for i in range(transactions):
        address=rng.choice([0,1,2,3,4,5,7]);write=(i%3!=1)
        operations.append({'write':write,'address':address,'data':rng.randrange(mask+1),
                           'tag':i%max(1,1<<design.inputs.get('request_tag_0',4))})
    def faulty(addr):return addr==7
    def active_transaction():return operations[finished] if finished<transactions else None
    def advance_offer(out,prefix):
        nonlocal check_count
        valid=out.get(f'axi_{prefix}valid',0)
        if valid:
            payload=tuple(out[f'axi_{prefix}{field}'] for field in (('addr',) if prefix in ('aw','ar') else ('data','strb')))
            if prefix in hold and hold[prefix]!=payload:
                raise AssertionError(f'{prefix.upper()} payload changed while VALID held under backpressure')
            check_count+=1
            ready=ports[f'axi_{prefix}ready']
            if valid and ready:hold.pop(prefix,None)
            else:hold[prefix]=payload
        elif prefix in hold:
            raise AssertionError(f'{prefix.upper()} VALID was withdrawn before handshake')
    trace=[]
    try:
        ports['reset']=1;sim.step(ports);ports['reset']=0
        for cycle in range(max_cycles):
            txn=active_transaction()
            if txn and not accepted:
                if tagged:
                    ports.update({'request_0':1,'opcode_0':3 if txn['write'] else 2,
                        'request_tag_0':txn['tag'],'a_0':txn['address'],'b_0':txn['data']})
                else:
                    ports.update({'memory_request_valid':1,'memory_request_write':int(txn['write']),
                        'memory_request_address':txn['address'],'memory_request_data':txn['data']})
            else:ports['request_0' if tagged else 'memory_request_valid']=0
            ports['response_ready_0' if tagged else 'memory_response_ready']=int(rng.random()<.65)
            ports.update({'axi_awready':int(aw is None and rng.random()<.55),
                          'axi_wready':int(w is None and rng.random()<.65),
                          'axi_arready':int(r is None and rng.random()<.6),
                          'axi_bvalid':int(b is not None and b['delay']==0),
                          'axi_bresp':b['resp'] if b else 0,
                          'axi_rvalid':int(r is not None and r['delay']==0),
                          'axi_rresp':r['resp'] if r else 0,
                          'axi_rdata':r['data'] if r else 0})
            out=sim.step(ports)
            trace.append({'cycle':cycle,'inputs':{k:v for k,v in ports.items() if v},
                 'outputs':{k:out[k] for k in ('axi_awvalid','axi_wvalid','axi_arvalid',
                    'axi_bready','axi_rready','axi_response_pending',
                    'response_valid_0' if tagged else 'memory_response_valid')}})
            if len(trace)>40:trace.pop(0)
            for prefix in ('aw','w','ar'):advance_offer(out,prefix)
            if txn and not accepted and out['request_accepted_0' if tagged else 'memory_request_accepted']:
                accepted=True;check_count+=1
            if out['axi_awvalid'] and ports['axi_awready']:
                assert aw is None, 'AW accepted while previous address pending'
                aw=out['axi_awaddr'];check_count+=1
            if out['axi_wvalid'] and ports['axi_wready']:
                assert w is None, 'W accepted while previous data pending'
                w=(out['axi_wdata'],out['axi_wstrb']);check_count+=1
            if aw is not None and w is not None:
                addr=aw//4;value,strobe=w
                assert aw%4==0 and 0<strobe<=3,'invalid alignment/strobe'
                resp=2 if faulty(addr) else 0
                if not resp:
                    original=memory.get(addr,0)
                    for byte in range(4):
                        if (strobe>>byte)&1:
                            original=(original & ~(255<<(8*byte))) | (value & (255<<(8*byte)))
                    memory[addr]=original
                b={'delay':rng.randrange(1,6),'resp':resp};aw=None;w=None
            if out['axi_arvalid'] and ports['axi_arready']:
                addr=out['axi_araddr'];assert addr%4==0
                idx=addr//4
                r={'delay':rng.randrange(1,6),'resp':2 if faulty(idx) else 0,
                   'data':memory.get(idx,0) if not faulty(idx) else 0}
                check_count+=1
            if b is not None:
                if ports['axi_bvalid'] and out['axi_bready']:b=None
                else:b['delay']=max(0,b['delay']-1)
            if r is not None:
                if ports['axi_rvalid'] and out['axi_rready']:r=None
                else:r['delay']=max(0,r['delay']-1)
            if txn and out['response_valid_0' if tagged else 'memory_response_valid']:
                expected_fault=int(faulty(txn['address']))
                expected_data=0 if txn['write'] or expected_fault else memory.get(txn['address'],0)&mask
                actual_data=out['response_data_0' if tagged else 'memory_response_data']
                actual_fault=out['response_fault_0' if tagged else 'memory_response_fault']
                assert (actual_data,actual_fault)==(expected_data,expected_fault),(
                    f'response mismatch at {cycle}: actual {actual_data}/{actual_fault}, '
                    f'expected {expected_data}/{expected_fault}')
                if tagged:assert out['response_tag_0']==txn['tag'],'response tag mismatch'
                check_count+=1
                if ports['response_ready_0' if tagged else 'memory_response_ready']:
                    assert accepted,'response without accepted request'
                    finished+=1;accepted=False
                    if finished==transactions:
                        return {'status':'PASS','seed':seed,'transactions':finished,
                           'checks':check_count,'cycles':cycle+1,
                           'scenarios':['independent randomized AXI4-Lite slave','AW/W separate ready',
                             'random response latency','memory contents','faults','tags',
                             'stable VALID/payload under backpressure']}
        raise AssertionError(f'Timeout: only {finished}/{transactions} transactions completed')
    except (AssertionError,ValueError,KeyError) as exc:
        return {'status':'FAIL','seed':seed,'transactions':finished,'checks':check_count,
                'reason':str(exc),'counterexample':trace}
