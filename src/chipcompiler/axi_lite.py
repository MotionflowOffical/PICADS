"""AXI4-Lite 32-bit *master* for the PICADS external memory request channel.

One transaction at a time at the bus boundary, registered request payload,
independent AW/W handshakes, delayed B/R completions, and buffered memory
response. Written entirely in gate-level DLS so it is exportable as RTL.

Addressing is word-indexed at the PICADS interface and byte-addressed on AXI.
The bridge maps word n to AXI byte address 4*n. Subword WSTRB covers the
least-significant ceil(width/8) bytes and read data is truncated to width.
No bursts, IDs, unaligned accesses, out-of-order AXI responses, or CDC.
"""
from __future__ import annotations
from dataclasses import dataclass
from .generator import LogicBuilder
from .ir import Bus,DLS
from .tagged import TaggedFabricConfig,tagged_fabric

AXI_INPUTS={'axi_awready':1,'axi_wready':1,'axi_bvalid':1,'axi_bresp':2,
            'axi_arready':1,'axi_rvalid':1,'axi_rdata':32,'axi_rresp':2}

@dataclass(frozen=True)
class AXILiteConfig:
    width:int=4
    address_width:int=4
    def validate(self):
        if type(self.width)!=int or not 1<=self.width<=16:
            raise ValueError('AXI.DATA_WIDTH: PICADS word width must be 1..16 bits')
        if type(self.address_width)!=int or not 1<=self.address_width<=16:
            raise ValueError('AXI.ADDRESS_WIDTH: word address width must be 1..16 bits')


def _interface(config:AXILiteConfig):
    return {'memory_request_valid':1,'memory_request_write':1,
            'memory_request_address':config.address_width,'memory_request_data':config.width,
            'memory_response_ready':1,'reset':1,**AXI_INPUTS}

class _Bridge:
    def __init__(self,b:LogicBuilder,cfg:AXILiteConfig):
        self.b=b;self.cfg=cfg
    def bus(self,p,n):return Bus(tuple(f'{p}[{j}]' for j in range(n)))
    def rb(self,p,n):return Bus(tuple(f'${p}[{j}]' for j in range(n)))
    def AND(self,*v):
        x='@1'
        for y in v:x=self.b.gate('AND',x,y)
        return x
    def OR(self,*v):
        x='@0'
        for y in v:x=self.b.gate('OR',x,y)
        return x
    def NOT(self,x):return self.b.gate('NOT',x)
    def mux(self,s,a,c):return self.b.mux(Bus((s,)),a,c)
    def bit(self,x):return Bus((x,))
    def reg(self,p,n=1,initial=0):
        self.b.registers[p]={'next':list(self.rb(p,n).bits),'init':initial}
    def update(self,p,value,when):
        bits=self.b.registers[p]['next']
        self.b.registers[p]['next']=list(self.mux(when,Bus(tuple(bits)),value).bits)
    def setbit(self,p,value,when):self.update(p,self.bit(value),when)
    def reset_all(self,reset):
        for p,desc in self.b.registers.items():
            desc['next']=list(self.mux(reset,Bus(tuple(desc['next'])),
                              self.b.const(desc['init'],len(desc['next']))).bits)

    def initial(self,reset):
        for p,n in (('busy',1),('write',1),('address',self.cfg.address_width),
                    ('data',self.cfg.width),('aw_done',1),('w_done',1),('ar_done',1),
                    ('response_valid',1),('response_data',self.cfg.width),
                    ('response_fault',1),('last_axi_resp',2)):
            self.reg(p,n)
        can_accept=self.AND(self.NOT('$busy[0]'),self.NOT('$response_valid[0]'),self.NOT(reset))
        return {'memory_request_ready':[can_accept],
                'memory_response_valid':['$response_valid[0]'],
                'memory_response_data':list(self.rb('response_data',self.cfg.width).bits),
                'memory_response_fault':['$response_fault[0]']}

    def finish(self,req:dict[str,list[str]],response_ready:str,reset:str):
        out={}
        bit=lambda name:req[name][0]
        live=self.NOT(reset)
        take=self.AND(bit('memory_request_valid'),self.ready,live)
        self.setbit('busy','@1',take)
        self.update('write',self.bit(bit('memory_request_write')),take)
        self.update('address',Bus(tuple(req['memory_request_address'])),take)
        self.update('data',Bus(tuple(req['memory_request_data'])),take)
        for key in ('aw_done','w_done','ar_done'):
            self.setbit(key,'@0',take)
        self.setbit('response_fault','@0',take)
        self.update('last_axi_resp',self.b.const(0,2),take)
        self.update('response_data',self.b.const(0,self.cfg.width),take)

        iswrite=self.AND('$busy[0]','$write[0]',live)
        isread=self.AND('$busy[0]',self.NOT('$write[0]'),live)
        awvalid=self.AND(iswrite,self.NOT('$aw_done[0]'))
        wvalid=self.AND(iswrite,self.NOT('$w_done[0]'))
        arvalid=self.AND(isread,self.NOT('$ar_done[0]'))
        aw_take=self.AND(awvalid,'axi_awready[0]')
        w_take=self.AND(wvalid,'axi_wready[0]')
        ar_take=self.AND(arvalid,'axi_arready[0]')
        self.setbit('aw_done','@1',aw_take)
        self.setbit('w_done','@1',w_take)
        self.setbit('ar_done','@1',ar_take)

        bready=self.AND(iswrite,'$aw_done[0]','$w_done[0]',self.NOT('$response_valid[0]'))
        rready=self.AND(isread,'$ar_done[0]',self.NOT('$response_valid[0]'))
        b_take=self.AND(bready,'axi_bvalid[0]')
        r_take=self.AND(rready,'axi_rvalid[0]')
        complete=self.OR(b_take,r_take)
        self.setbit('busy','@0',complete)
        self.setbit('response_valid','@1',complete)
        self.update('response_data',self.b.const(0,self.cfg.width),b_take)
        self.update('response_data',Bus(tuple(f'axi_rdata[{i}]' for i in range(self.cfg.width))),r_take)
        bresp=self.bus('axi_bresp',2);rresp=self.bus('axi_rresp',2)
        self.update('last_axi_resp',bresp,b_take)
        self.update('last_axi_resp',rresp,r_take)
        b_error=self.OR(*bresp.bits);r_error=self.OR(*rresp.bits)
        self.setbit('response_fault',b_error,b_take)
        self.setbit('response_fault',r_error,r_take)
        pop=self.AND('$response_valid[0]',response_ready,live)
        self.setbit('response_valid','@0',pop)
        self.reset_all(reset)
        address=tuple(self.rb('address',self.cfg.address_width).bits)
        # word-index -> byte-address. AXI4-Lite beats are 32 bits, aligned.
        axiaddr=list(('@0','@0')+address+('@0',)*(30-len(address)))
        wdata=list(self.rb('data',self.cfg.width).bits)+['@0']*(32-self.cfg.width)
        out.update({'axi_awvalid':[awvalid],'axi_awaddr':axiaddr,
                    'axi_wvalid':[wvalid],'axi_wdata':wdata,
                    'axi_wstrb':list(self.b.const((1<<((self.cfg.width+7)//8))-1,4).bits),
                    'axi_bready':[bready],'axi_arvalid':[arvalid],
                    'axi_araddr':axiaddr,'axi_rready':[rready],
                    'axi_busy':['$busy[0]'],'axi_response_pending':['$response_valid[0]'],
                    'axi_last_resp':list(self.rb('last_axi_resp',2).bits),
                    'memory_request_accepted':[take],
                    'memory_response_consumed':[pop]})
        return out


def axi_lite_master(config=AXILiteConfig(),name='axi_lite_master')->DLS:
    config.validate()
    if not isinstance(name,str) or not name.isidentifier():raise ValueError('AXI.NAME: invalid module name')
    b=LogicBuilder(name,_interface(config));bridge=_Bridge(b,config)
    mem=bridge.initial('reset[0]')
    bridge.ready=mem['memory_request_ready'][0]
    req={p:[f'{p}[{i}]' for i in range(w)] for p,w in _interface(config).items() if p.startswith('memory_request_') and p!='memory_request_ready'}
    outputs={**mem,**bridge.finish(req,'memory_response_ready[0]','reset[0]')}
    d=DLS(name,b.inputs,outputs,b.nodes,b.registers,{'kind':'axi4_lite_master',
        'protocol':'AXI4-Lite single-beat 32-bit little-endian word-mapped master',
        'limitations':['single AXI transaction','no bursts','no CDC','no multiple AXI IDs']})
    d.validate();return d


def axi_tagged_fabric(config:TaggedFabricConfig=TaggedFabricConfig(memory_backend='external'),
                      name='axi_tagged_fabric')->DLS:
    config.validate()
    if config.memory_backend!='external':
        raise ValueError('AXI.FABRIC_MEMORY: AXI-backed fabric requires fabric.memory_backend: external')
    if not isinstance(name,str) or not name.isidentifier():
        raise ValueError('AXI.NAME: invalid top-level module name')
    child=tagged_fabric(config,'tagged_resource_core')
    aw=len(child.outputs['memory_request_address'])
    # External fabric exports the full operand address width, not depth-sized built-in RAM indices.
    cfg=AXILiteConfig(config.width,aw)
    excluded={'memory_request_ready','memory_response_valid','memory_response_data','memory_response_fault'}
    ports={k:v for k,v in child.inputs.items() if k not in excluded}
    ports.update(AXI_INPUTS)
    b=LogicBuilder(name,ports);bridge=_Bridge(b,cfg)
    mem=bridge.initial('reset[0]');bridge.ready=mem['memory_request_ready'][0]
    inputs={}
    for k,w in child.inputs.items():
        if k in mem:inputs[k]=list(mem[k])
        else:inputs[k]=[f'{k}[{j}]' for j in range(w)]
    wires={k:[f'core_{k}_{j}' for j in range(len(v))] for k,v in child.outputs.items()}
    b.submodules[child.name]=child
    b.instances.append({'name':'resource_core','module':child.name,'at':len(b.nodes),
                        'inputs':inputs,'outputs':wires})
    req={p:wires[p] for p in ('memory_request_valid','memory_request_write',
                             'memory_request_address','memory_request_data')}
    outputs={k:list(v) for k,v in wires.items() if not k.startswith('memory_')}
    outputs.update(bridge.finish(req,wires['memory_response_ready'][0],'reset[0]'))
    meta={'kind':'axi_tagged_fabric','schedule':{**child.metadata['schedule'],
          'mode':'axi_lite_fabric','memory_backend':'axi4_lite',
          'axi_data_width':32,'axi_address_width':32},
          'verification':'AXI4-Lite directed protocol checks; independent RTL/formal/PDK validation required',
          'limitations':['one AXI bus transaction in progress','not AXI4 burst','no cache coherence',
                         'one client ingress and egress handshake per cycle']}
    d=DLS(name,ports,outputs,b.nodes,b.registers,meta,b.instances,b.submodules)
    d.validate();return d
