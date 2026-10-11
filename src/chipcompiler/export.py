"""Structural gate-level Verilog export. Never substitutes behavioral operations for DLS gates."""
from pathlib import Path
from .ir import DLS
from .project import atomic_write
import re

def _module_verilog(design:DLS)->str:
    design.validate()
    if not re.fullmatch('[a-zA-Z_][a-zA-Z0-9_]*',design.name):raise ValueError('Unsafe Verilog module name')
    ports=[*design.inputs,*design.outputs]
    if design.requires_clock():ports=['clk',*ports]
    out=['// Generated from executable gate-level DLS. Do not edit generated outputs.',
         f'module {design.name}({", ".join(ports)});']
    if design.requires_clock():out.append('  input wire clk;')
    for name,width in design.inputs.items():
        out.append(f'  input wire [{width-1}:0] {name};')
    for name,pins in design.outputs.items():
        out.append(f'  output wire [{len(pins)-1}:0] {name};')
    for n in design.nodes:out.append(f'  wire {n.name};')
    for inst in design.instances:
        for pins in inst['outputs'].values():
            for p in pins:out.append(f'  wire {p};')
    for reg,d in design.registers.items():
        n=len(d['next']);out.append(f'  reg [{n-1}:0] r_{reg} = {n}\'d{d.get("init",0)&((1<<n)-1)};')
    def pin(p):
        if p=='@0':return "1'b0"
        if p=='@1':return "1'b1"
        if p.startswith('$'):
            body=p[1:];r,i=body.split('[');return f'r_{r}[{i}'
        return p
    symbols={'AND':'&','OR':'|','XOR':'^','NAND':'&','NOR':'|','XNOR':'^'}
    by_position={}
    for instance in design.instances:by_position.setdefault(instance['at'],[]).append(instance)
    for idx in range(len(design.nodes)+1):
        for inst in by_position.get(idx,[]):
            ports=[]
            if design.submodules[inst['module']].requires_clock():
                ports.append('.clk(clk)')
            for name,bits in inst['inputs'].items():
                ports.append(f'.{name}({{{", ".join(pin(p) for p in reversed(bits))}}})')
            for name,bits in inst['outputs'].items():
                ports.append(f'.{name}({{{", ".join(pin(p) for p in reversed(bits))}}})')
            out.append(f'  {inst["module"]} {inst["name"]}({", ".join(ports)});')
        if idx==len(design.nodes):break
        n=design.nodes[idx]
        a=[pin(x) for x in n.inputs]
        if n.op in symbols:
            expression=f'({a[0]} {symbols[n.op]} {a[1]})'
            if n.op in ('NAND','NOR','XNOR'):expression='~'+expression
        elif n.op=='NOT':expression='~'+a[0]
        elif n.op=='BUF':expression=a[0]
        elif n.op=='MUX':expression=f'({a[0]} ? {a[2]} : {a[1]})'
        else:raise ValueError(f'Unknown exported gate {n.op}')
        out.append(f'  assign {n.name} = {expression};')
    for name,pins in design.outputs.items():
        out.append(f'  assign {name} = {{{", ".join(pin(p) for p in reversed(pins))}}};')
    if design.registers:
        out.append('  always @(posedge clk) begin')
        for name,d in design.registers.items():
            out.append(f'    r_{name} <= {{{", ".join(pin(p) for p in reversed(d["next"]))}}};')
        out.append('  end')
    out.extend(['endmodule',''])
    return '\n'.join(out)

def verilog(design:DLS)->str:
    """Emit each nested module definition exactly once, in dependency order."""
    design.validate()
    definitions={}
    order=[]
    def traverse(module):
        for child in module.submodules.values():traverse(child)
        body=_module_verilog(module)
        if module.name in definitions:
            if definitions[module.name]!=body:
                raise ValueError(f'Conflicting hierarchical definitions for {module.name!r}')
            return
        definitions[module.name]=body
        order.append(module.name)
    traverse(design)
    return '\n'.join(definitions[name] for name in order)

def export_verilog(design:DLS,path:Path)->Path:
    text=verilog(design);atomic_write(Path(path),text);return Path(path)
