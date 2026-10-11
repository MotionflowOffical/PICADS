"""VCD trace export of actual DLS execution, not timing-accurate simulation.

Clock period is the virtual testbench period. There is no RC or gate delay,
so timestamps are logical samples only. Nodes are taken from DLS execution.
"""
from __future__ import annotations
from pathlib import Path
import math
from .ir import DLS
from .project import atomic_write

CHARACTERS='!#$%&()*+,-./:;<=>?@[]^_`{|}~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

def ident(n):
    base=len(CHARACTERS);out=''
    while True:
        out=CHARACTERS[n%base]+out
        n//=base
        if not n:break
    return out

def vcd_bits(value,width):
    return 'x'*width if value is None else format(value&((1<<width)-1),f'0{width}b')

def export_vcd(dls:DLS,vectors:list[dict],path:Path,clock_period_ns:int=10,
               include_internal:bool=False,max_internal:int=2000)->dict:
    dls.validate()
    if type(clock_period_ns)!=int or clock_period_ns<2:raise ValueError('Virtual clock period must be an integer >=2 ns')
    if not vectors:raise ValueError('Cannot export a waveform without input vectors')
    if len(vectors)>100_000:raise ValueError('Waveform vector limit: 100000')
    internal=dls.nodes[:max_internal] if include_internal else []
    # Declare all register paths including clocked child instances. A logical
    # trace must not silently omit state simply because the top is a wrapper.
    hierarchical={}
    def register_names(module,prefix):
        if prefix != dls.name:  # Root registers already use legacy reg_<name>.
            for name,desc in module.registers.items():
                key=f'{prefix}/r_{name}'
                label='state_'+prefix.replace('/','__')+'__r_'+name
                hierarchical[label]=(key,len(desc['next']))
        for inst in module.instances:
            register_names(module.submodules[inst['module']],prefix+'/'+inst['name'])
    register_names(dls,dls.name)
    clock_label='clk' if 'clk' not in dls.inputs and 'clk' not in dls.outputs else 'chipcompiler_cycle_clock'
    declared=[(clock_label,1),*dls.inputs.items(),
              *((name,len(bits)) for name,bits in dls.outputs.items()),
              *((f'reg_{name}',len(spec['next'])) for name,spec in dls.registers.items()),
              *((label,width) for label,(_,width) in hierarchical.items()),
              *((f'gate_{node.name}',1) for node in internal)]
    decl={}
    for name,width in declared:
        if name in decl:
            raise ValueError(f'VCD signal name collision: {name!r}; no waveform was exported.')
        decl[name]=width
    codes={n:ident(i) for i,n in enumerate(decl)}
    lines=['$date recorded by Chip Compiler $end','$version ChipCompiler virtual-cycle DLS trace (NOT physical gate timing) $end',
           '$timescale 1ns $end','$scope module '+dls.name+' $end']
    for name,width in decl.items():
        lines.append(f'$var wire {width} {codes[name]} {name} $end')
    lines+=['$upscope $end','$enddefinitions $end']
    sim=dls.new_simulator()
    def values(cycle_result,clock_state):
        output={clock_label:clock_state,**sim.last_inputs,**cycle_result}
        for name,bits in sim.registers.items():
            # Values on the waveform reflect the post-edge register state.
            output['reg_'+name]=(None if None in bits else sum(int(b)<<i for i,b in enumerate(bits)))
        snap=sim.register_snapshot()
        for label,(key,_) in hierarchical.items():output[label]=snap[key]
        for node in internal:output['gate_'+node.name]=sim.last_signals[node.name]
        return output
    last={}
    for tick,vector in enumerate(vectors):
        if not isinstance(vector,dict):raise TypeError(f'Vector {tick} is not a dictionary')
        t=tick*clock_period_ns
        # Sample the combinational network before a rising edge, advance all
        # registers simultaneously, then re-evaluate post-edge signals.
        before=sim.step(vector,clock=False)
        pre=values(before,0)
        sim.step(vector,clock=True)
        after=sim.step(vector,clock=False)
        post=values(after,1)
        for time,value_map in ((t,pre),(t+clock_period_ns//2,post)):
            lines.append('#'+str(time))
            for name,width in decl.items():
                value=value_map[name]
                bits=vcd_bits(value,width)
                if last.get(name)==bits:continue
                last[name]=bits
                lines.append(f'b{bits} {codes[name]}')
    lines.append('#'+str(len(vectors)*clock_period_ns))
    atomic_write(path,'\n'.join(lines)+'\n')
    return {'file':str(path),'vectors':len(vectors),'virtual_clock_period_ns':clock_period_ns,
            'internal_exported':len(internal),'internal_total':len(dls.nodes),
            'hierarchical_registers_exported':len(hierarchical),
            'internal_truncated':len(internal)<len(dls.nodes) if include_internal else False,
            'timing_model':'logical_cycle_only_not_physical'}
