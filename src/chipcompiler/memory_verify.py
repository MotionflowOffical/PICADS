"""Independent external-memory BFM and directed protocol tests.

Tests a decoupled one-port memory request/response device with arbitrary
acceptance delay and response latency. No simulation storage is shared with
DLS; the external model independently implements read/write semantics.
"""
from __future__ import annotations
from .ir import DLS


def check_external_memory(design:DLS,tagged:bool=True)->dict:
    sim=design.new_simulator()
    v={p:0 for p in design.inputs}
    v['memory_request_ready']=0
    address_width=design.inputs['a_0'];data_mask=(1<<address_width)-1
    depth=design.metadata['schedule']['memory_depth']
    address0=0;address1=1 if depth>1 else 0
    can_fault=depth<(1<<address_width)
    ram={};inflight=None
    tick=0;checks=0;accepted=0;responded=0;backpressured=0
    history=[]
    def sample():return sim.step(v,clock=False)
    def expect(ok,message):
        nonlocal checks
        checks+=1
        if not ok:raise AssertionError(message)
    def cycle():
        nonlocal tick,inflight,accepted,responded,backpressured
        # An external memory device independently chooses when to accept and
        # when to complete. Test long VALID backpressure and delayed responses.
        v['memory_request_ready']=int(tick%7 not in (2,3,4))
        v['memory_response_valid']=int(inflight is not None and tick>=inflight[0])
        v['memory_response_data']=(inflight[1] if v['memory_response_valid'] else 0)
        v['memory_response_fault']=(inflight[2] if v['memory_response_valid'] else 0)
        out=sample()
        if out['memory_request_valid'] and not v['memory_request_ready']:backpressured+=1
        if v['memory_response_valid'] and out['memory_response_ready']:
            responded+=1;inflight=None
        if out['memory_request_valid'] and v['memory_request_ready']:
            expect(inflight is None,'External interface accepted a second request with one transaction active')
            wr=out['memory_request_write'];addr=out['memory_request_address'];data=out['memory_request_data']
            fault=int(addr>=depth)
            result=0 if wr or fault else ram.get(addr,0)
            if wr and not fault:ram[addr]=data
            inflight=(tick+4,result,fault)
            accepted+=1
        history.append({'tick':tick,'issue':out['memory_request_valid'],
                        'memory_busy':out['memory_busy'],'response_ready':out['memory_response_ready']})
        sim.step(v,clock=True);tick+=1
        return sample()
    def send(i,tag,op,addr,data):
        v.update({f'request_{i}':1,f'opcode_{i}':op,f'a_{i}':addr,f'b_{i}':data})
        if tagged:v[f'request_tag_{i}']=tag
        expect(sample()[f'request_ready_{i}']==1,'Client request slot unavailable')
        cycle();v[f'request_{i}']=0
    def wait(i,tag,value,fault=0):
        for _ in range(100):
            out=sample()
            if out[f'response_valid_{i}']:
                if tagged:expect(out[f'response_tag_{i}']==tag,'Incorrect returned transaction tag')
                expect(out[f'response_data_{i}']==value,'External memory result incorrectly routed')
                expect(out[f'response_fault_{i}']==fault,'External memory fault incorrectly routed')
                hold=(out[f'response_data_{i}'],out[f'response_fault_{i}'])
                for _ in range(2):
                    cycle();seen=sample()
                    expect(seen[f'response_valid_{i}']==1,'Response not buffered until client accepts')
                    expect((seen[f'response_data_{i}'],seen[f'response_fault_{i}'])==hold,
                           'Response payload changed during client backpressure')
                v[f'response_ready_{i}']=1;cycle();v[f'response_ready_{i}']=0
                return
            cycle()
        raise AssertionError(f'External memory timeout for client {i} tag {tag}')
    try:
        # Reset both the fabric and independent test memory model.
        v['reset']=1;cycle();v['reset']=0
        tagmask=(1<<design.inputs['request_tag_0'])-1 if tagged else 0
        def tag(x):return (x & tagmask) if tagged else x
        send(0,tag(1),3,address0,7 & data_mask)
        send(1,tag(2),3,address1,9 & data_mask)
        wait(0,tag(1),0);wait(1,tag(2),0)
        send(0,tag(3),2,address0,0)
        wait(0,tag(3),(9 if address0==address1 else 7)&data_mask)
        send(1,tag(4),2,address1,0)
        wait(1,tag(4),9 & data_mask)
        if can_fault:
            send(0,tag(5),2,depth,0)
            wait(0,tag(5),0,1)
        expect(backpressured>0,'Did not test memory-request backpressure')
        expect(accepted==responded,'Memory request/response count mismatch')
        return {'status':'PASS','checks':checks,'memory_requests':accepted,
                'memory_completions':responded,'backpressured_cycles':backpressured,
                'scenarios':['two competing writers','external ready backpressure',
                             'variable response latency','independent reads',
                             *(['memory fault propagation'] if can_fault else []),
                             'held client responses']}
    except Exception as exc:
        return {'status':'FAIL','checks':checks,'error':f'{type(exc).__name__}: {exc}',
                'edge':tick,'memory_requests':accepted,'memory_completions':responded,
                'replay_last_24':history[-24:]}
