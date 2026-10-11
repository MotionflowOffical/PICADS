"""DLS is the generated, executable gate-level truth. Serializes as audited JSON.

No high-level 'ADD' or 'MUL' opcodes are allowed in saved generated DLS:
they must be synthesized to actual primitive gates before simulation or export.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
from pathlib import Path
import json
from .gates import gate, PRIMITIVES, Bit

@dataclass(frozen=True)
class Bus:
    bits: tuple[str, ...]
    signed: bool = False
    def __len__(self): return len(self.bits)

@dataclass
class Node:
    name: str
    op: str
    inputs: list[str]
    origin: str = ''

@dataclass
class DLS:
    name: str
    inputs: dict[str, int]
    outputs: dict[str, list[str]]
    nodes: list[Node]
    registers: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Instances are ordered insertions into the gate evaluation stream.
    # Child modules contain actual executable DLS, not opaque labels.
    instances: list[dict[str, Any]] = field(default_factory=list)
    submodules: dict[str, "DLS"] = field(default_factory=dict)
    VERSION = 2

    def to_dict(self):
        return {'format':'ChipCompiler-DLS', 'version': self.VERSION, 'name':self.name,
                'inputs':self.inputs, 'outputs':self.outputs,
                'nodes':[asdict(n) for n in self.nodes], 'registers':self.registers,
                'metadata':self.metadata,
                'instances':self.instances,'submodules':{k:v.to_dict() for k,v in self.submodules.items()}}

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        import os, tempfile
        path = Path(path)
        fd, tmp = tempfile.mkstemp(prefix='.dls-',suffix='.tmp',dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(),f,indent=2,ensure_ascii=False,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    @classmethod
    def load(cls, path: Path):
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        x=cls.from_dict(d)
        x.validate()
        return x

    @classmethod
    def from_dict(cls,d):
        if d.get('format') != 'ChipCompiler-DLS' or d.get('version') not in (1,2):
            raise ValueError('Unsupported DLS format/version')
        return cls(name=d['name'],inputs=d['inputs'],outputs=d['outputs'],
                   nodes=[Node(**n) for n in d['nodes']],registers=d.get('registers',{}),
                   metadata=d.get('metadata',{}),instances=d.get('instances',[]),
                   submodules={k:cls.from_dict(v) for k,v in d.get('submodules',{}).items()})

    def requires_clock(self) -> bool:
        """A hierarchy uses one shared rising-edge clock if any descendant owns state.

        The implicit clock is not an ordinary DLS data input. It is forwarded
        at every level of a clocked instance chain, including pure wrappers.
        """
        return bool(self.registers) or any(child.requires_clock() for child in self.submodules.values())

    def validate(self):
        if not self.name.isidentifier():raise ValueError(f'Invalid DLS module name {self.name!r}')
        if len(set(self.inputs)|set(self.outputs))!=len(self.inputs)+len(self.outputs):
            raise ValueError('DLS input and output port names collide')
        if self.requires_clock() and 'clk' in self.inputs:
            raise ValueError('DLS input clk conflicts with implicit sequential clock port')
        if self.requires_clock() and 'clk' in self.outputs:
            raise ValueError('DLS output clk conflicts with implicit sequential clock port')
        if any(not name.isidentifier() for name in self.outputs):
            raise ValueError('Invalid DLS output port identifier')
        defined={'@0','@1'}
        for name,width in self.inputs.items():
            if not name.isidentifier() or not isinstance(width,int) or width<1 or width>4096: raise ValueError(f'Invalid input {name} width {width}')
            for i in range(width): defined.add(f'{name}[{i}]')
        for reg,desc in self.registers.items():
            if not reg.isidentifier() or len(desc.get('next',[])) < 1: raise ValueError(f'Invalid register {reg}')
            for i in range(len(desc['next'])): defined.add(f'${reg}[{i}]')
        for module,child in self.submodules.items():
            if not module.isidentifier() or child.name != module:
                raise ValueError(f'Invalid hierarchical module definition {module!r}')
            child.validate()
        by_position={}
        used_names=set()
        for inst in self.instances:
            module=inst.get('module');name=inst.get('name');at=inst.get('at')
            if not isinstance(name,str) or not name.isidentifier() or name in used_names:
                raise ValueError(f'Invalid or duplicate instance name: {name!r}')
            used_names.add(name)
            if module not in self.submodules:raise ValueError(f'{name}: unknown submodule {module!r}')
            if type(at)!=int or not 0<=at<=len(self.nodes):
                raise ValueError(f'{name}: invalid insertion position {at!r}')
            by_position.setdefault(at,[]).append(inst)
        for position in range(len(self.nodes)+1):
            for inst in by_position.get(position,[]):
                child=self.submodules[inst['module']]
                if set(inst['inputs']) != set(child.inputs) or set(inst['outputs']) != set(child.outputs):
                    raise ValueError(f'{inst["name"]}: instance interface mismatch')
                for name,width in child.inputs.items():
                    pins=inst['inputs'][name]
                    if len(pins)!=width or any(pin not in defined for pin in pins):
                        raise ValueError(f'{inst["name"]}: disconnected or wrong-width port {name}')
                for name,child_bits in child.outputs.items():
                    pins=inst['outputs'][name]
                    if len(pins)!=len(child_bits):raise ValueError(f'{inst["name"]}: output width mismatch {name}')
                    for pin in pins:
                        if pin in defined or not pin.isidentifier():
                            raise ValueError(f'{inst["name"]}: conflicting output pin {pin}')
                        defined.add(pin)
            if position<len(self.nodes):
                n=self.nodes[position]
                if n.op not in PRIMITIVES or n.op == 'DFF':raise ValueError(f'Unsupported combinational gate {n.op}')
                if len(n.inputs)!=PRIMITIVES[n.op]:raise ValueError(f'{n.name}: {n.op} expects {PRIMITIVES[n.op]} inputs')
                if n.name in defined:raise ValueError(f'DLS duplicate driver or name: {n.name}')
                for pin in n.inputs:
                    if pin not in defined:raise ValueError(f'{n.name}: undefined or forward reference {pin}')
                defined.add(n.name)
        for output,bits in {**self.outputs,**{f'reg:{n}':d['next'] for n,d in self.registers.items()}}.items():
            if not bits or any(b not in defined for b in bits):
                raise ValueError(f'{output}: signal is missing or undefined')
        return True

    def new_simulator(self): self.validate(); return DLSSimulator(self)

    def stats(self):
        by_gate={}
        for n in self.nodes: by_gate[n.op] = by_gate.get(n.op,0)+1
        return {'primitive_gates':len(self.nodes), 'hierarchical_instances':len(self.instances), 'gate_types':by_gate,
                'state_bits':sum(len(d['next']) for d in self.registers.values()),
                'input_bits':sum(self.inputs.values()), 'output_bits':sum(len(x) for x in self.outputs.values())}

class DLSSimulator:
    def __init__(self, design: DLS):
        self.design=design
        self.registers={k:[(d.get('init',0)>>i)&1 for i in range(len(d['next']))] for k,d in design.registers.items()}
        # One independent simulator for each physical instance, not for each
        # module definition. State persists across calls and clock edges.
        self.children = {inst['name']: design.submodules[inst['module']].new_simulator()
                         for inst in design.instances}
        self.cycle=0
        self.last_signals={}
        self.last_inputs={}
        self.last_outputs={}

    def register_snapshot(self) -> dict[str, int | None]:
        """Copy register values using physical instance paths for diagnostics.

        Every independently instantiated child has a distinct path. The
        snapshot represents the current simulated state, not physical timing.
        """
        values = {}
        def visit(sim, path):
            for name,bits in sim.registers.items():
                values[f'{path}/r_{name}'] = (None if None in bits else
                                                sum(int(bit)<<i for i,bit in enumerate(bits)))
            for inst in sim.design.instances:
                visit(sim.children[inst['name']], f'{path}/{inst["name"]}')
        visit(self, self.design.name)
        return values

    def step(self, inputs: dict[str,int|None], clock: bool=True) -> dict[str,int|None]:
        d=self.design
        known={'@0':0,'@1':1}
        for name,width in d.inputs.items():
            if name not in inputs: raise ValueError(f'Missing DLS simulation input: {name}')
            v=inputs[name]
            if v is None:
                for i in range(width): known[f'{name}[{i}]']=None
            elif not isinstance(v,int): raise TypeError(f'{name} must be integer or None (unknown)')
            else:
                for i in range(width): known[f'{name}[{i}]']=(v>>i)&1
        for name,bits in self.registers.items():
            for i,v in enumerate(bits): known[f'${name}[{i}]']=v
        at={}
        for inst in d.instances:at.setdefault(inst['at'],[]).append(inst)
        for i in range(len(d.nodes)+1):
            for inst in at.get(i,[]):
                child=d.submodules[inst['module']]
                cinputs={key:sum(int(known[p])<<j for j,p in enumerate(bits))
                         if all(known[p] is not None for p in bits) else None
                         for key,bits in inst['inputs'].items()}
                coutputs=self.children[inst['name']].step(cinputs,clock=clock)
                for name,bits in inst['outputs'].items():
                    val=coutputs[name]
                    for j,pin in enumerate(bits):known[pin]=None if val is None else (val>>j)&1
            if i<len(d.nodes):
                n=d.nodes[i]
                known[n.name]=gate(n.op,tuple(known[p] for p in n.inputs))
        def asnum(names):
            bits=[known[k] for k in names]
            return None if None in bits else sum(int(bit)<<i for i,bit in enumerate(bits))
        result={name:asnum(bits) for name,bits in d.outputs.items()}
        self.last_signals=dict(known)
        self.last_inputs=dict(inputs)
        self.last_outputs=dict(result)
        if clock:
            next_values={name:[known[b] for b in spec['next']] for name,spec in d.registers.items()}
            self.registers=next_values; self.cycle+=1
        return result
