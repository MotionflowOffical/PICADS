"""Standalone example: generated arbitration logic and structural RTL.

Execute from a Chip Compiler installation:
    python examples/round_robin_arbiter/generate.py
"""
from pathlib import Path
from chipcompiler.arbitration import round_robin_arbiter
from chipcompiler.export import export_verilog

root=Path(__file__).resolve().parent
out=root/'generated'
out.mkdir(exist_ok=True)
d=round_robin_arbiter(clients=3,payload_width=8,name='shared_resource_rr')
d.save(out/'shared_resource_rr.dls')
export_verilog(d,out/'shared_resource_rr.v')
sim=d.new_simulator()
print('Generated 3-client round-robin arbiter; grants under continuous contention:')
for tick in range(9):
    stimulus={'resource_ready':1,'stall':0,'reset':0,
              **{f'request_{i}':1 for i in range(3)},
              **{f'payload_{i}':0x30+i for i in range(3)}}
    print(tick,sim.step(stimulus,clock=False)['selected_client'])
    sim.step(stimulus)
print('Artifacts:',out)
