"""SymbiYosys-compatible BMC collateral for tagged fabric safety invariants.

This generates executable proof tasks but never claims properties have been
proven. A concrete SBY/Z3 run must succeed before recording external evidence.
Arithmetic functional equivalence and liveness are NOT covered by this harness.
"""
from __future__ import annotations
from pathlib import Path
import shutil
from .ir import DLS
from .export import export_verilog


def prepare_tagged_formal(design:DLS,directory:Path,depth:int=12)->dict:
    mode=design.metadata.get('schedule',{}).get('mode')
    if mode not in ('tagged_fabric','bound_fabric'):
        raise ValueError('FORMAL.MODE: expected tagged_fabric or bound_fabric DLS')
    if type(depth)!=int or not 2<=depth<=64:
        raise ValueError('FORMAL.DEPTH: BMC depth must be 2..64')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    rtl=directory/'dut.v';export_verilog(design,rtl)
    lines=['// PICADS generated safety-property harness; requires independent SymbiYosys.',
           'module picads_formal_top(input wire clk);']
    for port,width in design.inputs.items():
        lines.append(f'  (* anyseq *) wire [{width-1}:0] {port};')
    for port,bits in design.outputs.items():
        lines.append(f'  wire [{len(bits)-1}:0] {port};')
    ports=['.clk(clk)']+[f'.{k}({k})' for k in (*design.inputs,*design.outputs)]
    lines.append(f'  {design.name} dut({", ".join(ports)});')
    n=design.metadata['schedule']['clients']
    lines.append('  reg past_valid = 0;')
    lines.append('  always @(posedge clk) begin')
    lines.append('    past_valid <= 1;')
    lines.append('    if (!past_valid) assume(reset);')
    for i in range(n):
        lines.extend([
            f'    assert(request_accepted_{i} == (request_{i} && request_ready_{i}));',
            f'    assert(response_accepted_{i} == (response_valid_{i} && response_ready_{i} && !stall && !reset));',
            f'    if (duplicate_tag_{i}) assert(!request_ready_{i});',
            f'    if (stall || reset) assert(!request_accepted_{i});',
            f'    if (past_valid && $past(response_valid_{i}) && !$past(response_ready_{i}) && !$past(reset) && !reset) begin',
            f'      assert(response_valid_{i});',
            f'      assert(response_tag_{i} == $past(response_tag_{i}));',
            f'      assert(response_data_{i} == $past(response_data_{i}));',
            f'      assert(response_fault_{i} == $past(response_fault_{i}));',
            '    end',
            f'    if (past_valid && $past(stall) && !$past(reset) && !reset) begin',
            f'      assert(outstanding_{i} == $past(outstanding_{i}));',
            '    end',
        ])
    lines.extend(['  end','endmodule'])
    (directory/'properties.sv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    sby='''[options]
mode bmc
depth {depth}

[engines]
smtbmc z3

[script]
read -formal -sv dut.v
read -formal -sv properties.sv
prep -top picads_formal_top

[files]
dut.v
properties.sv
'''.format(depth=depth)
    (directory/'safety.sby').write_text(sby,encoding='utf-8')
    (directory/'README.txt').write_text(
        'PICADS safety BMC collateral. Run: sby -f safety.sby\n'
        'PASS, if obtained on a real SBY/Z3 toolchain, proves ONLY the assertions\n'
        f'within {depth} bounded clock steps and the formal reset assumption.\n'
        'It does not prove unbounded correctness, gate-delay/timing, circuit function,\n'
        'power, DRC, LVS, physical reliability, or foundry manufacturing signoff.\n',encoding='utf-8')
    return {'status':'GENERATED_UNVERIFIED','top':design.name,'depth':depth,
            'properties_per_client':10,'files':['dut.v','properties.sv','safety.sby','README.txt'],
            'tool_requirements':['sby','yosys','z3']}


def prepare_axi_lite_formal(design:DLS,directory:Path,depth:int=18)->dict:
    """Generate bounded *safety* assertions for the 32-bit AXI4-Lite master.

    Valid/payload hold under backpressure, mutually exclusive read/write and
    request acceptance are checked under an initial reset assumption. This
    does NOT claim full AXI compliance, liveness, or downstream correctness.
    """
    if design.metadata.get('kind') not in ('axi4_lite_master','axi_tagged_fabric'):
        raise ValueError('FORMAL.AXI_MODE: expected AXI4-Lite master or tagged wrapper')
    if type(depth)!=int or not 3<=depth<=96:
        raise ValueError('FORMAL.AXI_DEPTH: BMC depth must be 3..96')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    export_verilog(design,directory/'dut.v')
    lines=['// PICADS v0.11 AXI4-Lite bounded safety verification.',
           'module picads_axi_formal_top(input wire clk);']
    for port,width in design.inputs.items():
        lines.append(f'  (* anyseq *) wire [{width-1}:0] {port};')
    for port,bits in design.outputs.items():
        lines.append(f'  wire [{len(bits)-1}:0] {port};')
    ports=['.clk(clk)']+[f'.{name}({name})' for name in (*design.inputs,*design.outputs)]
    lines.append(f'  {design.name} dut({", ".join(ports)});')
    lines.extend(['  reg past_valid = 0;',
       '  always @(posedge clk) begin',
       '    past_valid <= 1;',
       '    if (!past_valid) assume(reset);',
       '    if (!reset) begin',
       '      assert(!(axi_awvalid && axi_arvalid));',
       '      assert(!(axi_bready && axi_rready));',
       '      assert(!(axi_wvalid && axi_arvalid));',
       '    end',
       '    if (past_valid && !$past(reset) && !reset) begin',
       '      if ($past(axi_awvalid && !axi_awready)) begin',
       '        assert(axi_awvalid);',
       '        assert(axi_awaddr == $past(axi_awaddr));',
       '      end',
       '      if ($past(axi_wvalid && !axi_wready)) begin',
       '        assert(axi_wvalid);',
       '        assert(axi_wdata == $past(axi_wdata));',
       '        assert(axi_wstrb == $past(axi_wstrb));',
       '      end',
       '      if ($past(axi_arvalid && !axi_arready)) begin',
       '        assert(axi_arvalid);',
       '        assert(axi_araddr == $past(axi_araddr));',
       '      end',
       '    end',
       '  end','endmodule'])
    (directory/'properties.sv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (directory/'safety.sby').write_text(f'''[options]
mode bmc
depth {depth}

[engines]
smtbmc z3

[script]
read -formal -sv dut.v
read -formal -sv properties.sv
prep -top picads_axi_formal_top

[files]
dut.v
properties.sv
''',encoding='utf-8')
    (directory/'README.txt').write_text(
        'Run sby -f safety.sby with real Yosys, SymbiYosys, and Z3.\n'
        'These are bounded protocol safety checks, NOT a complete AXI protocol proof.\n'
        'Only real external proof execution can produce PASS/FAIL evidence.\n',encoding='utf-8')
    return {'status':'GENERATED_UNVERIFIED','depth':depth,
            'properties':['read/write mutual exclusion','AW hold','W hold','AR hold'],
            'files':['dut.v','properties.sv','safety.sby','README.txt'],
            'tool_requirements':['sby','yosys','z3']}


def prepare_global_shared_formal(design:DLS,directory:Path,depth:int=20)->dict:
    """Generate checked-on-real-tool bounded mutual-exclusion/ownership assertions.

    This proves *only safety* for source-process ADD/MUL grant wiring, not
    full behavioral equivalence, fair scheduling, or unbounded liveness.
    """
    meta=design.metadata.get('schedule',{})
    if meta.get('mode')!='global_source_processes':
        raise ValueError('FORMAL.GLOBAL_MODE: expected globally shared source processes')
    if type(depth)!=int or not 3<=depth<=96:
        raise ValueError('FORMAL.GLOBAL_DEPTH: depth must be 3..96')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    export_verilog(design,directory/'dut.v')
    lines=['// Safety only; no claim of general sequential equivalence.',
           'module picads_global_formal_top(input wire clk);']
    for port,width in design.inputs.items():lines.append(f'  (* anyseq *) wire [{width-1}:0] {port};')
    for port,pins in design.outputs.items():lines.append(f'  wire [{len(pins)-1}:0] {port};')
    ports=['.clk(clk)']+[f'.{p}({p})' for p in (*design.inputs,*design.outputs)]
    lines.append(f'  {design.name} dut({", ".join(ports)});')
    lines.extend(['  reg initialized = 0;','  always @(posedge clk) begin',
                  '    initialized <= 1;','    if (!initialized) assume(reset);'])
    properties=0
    for kind,names in meta['served_clients'].items():
        lower=kind.lower()
        for i,name in enumerate(names):
            g=f'arb_grant_{lower}_{name}';r=f'arb_request_{lower}_{name}'
            lines.append(f'    assert(!{g} || ({r} && !reset));')
            properties+=1
            for other in names[i+1:]:
                lines.append(f'    assert(!({g} && arb_grant_{lower}_{other}));')
                properties+=1
    if meta.get('global_shared_memory'):
        names=[c['client'] for c in meta['source_bindings']]
        for index,name in enumerate(names):
            g=f'arb_grant_mem_{name}';r=f'arb_request_mem_{name}'
            lines.append(f'    assert(!{g} || ({r} && !reset));')
            properties+=1
            for other in names[index+1:]:
                lines.append(f'    assert(!({g} && arb_grant_mem_{other}));')
                properties+=1
    if not properties:
        raise ValueError('FORMAL.GLOBAL_EMPTY: generated harness has no invariants')
    lines.extend(['  end','endmodule'])
    (directory/'properties.sv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (directory/'safety.sby').write_text(f'''[options]
mode bmc
depth {depth}

[engines]
smtbmc z3

[script]
read -formal -sv dut.v
read -formal -sv properties.sv
prep -top picads_global_formal_top

[files]
dut.v
properties.sv
''',encoding='utf-8')
    (directory/'README.txt').write_text(
        'Run sby -f safety.sby on your machine with Yosys/SymbiYosys/Z3.\n'
        'Generated formal files are UNVERIFIED until the actual solver succeeds.\n'
        'Checks: per-operator and shared-memory grant mutual exclusion, ownership and reset gating.\n'
        'Does NOT prove source equivalence, fairness/liveness, timing, DRC or signoff.\n',
        encoding='utf-8')
    return {'status':'GENERATED_UNVERIFIED','depth':depth,
            'properties':properties,'property_classes':['single grant per physical resource','grant implies request and not reset'],
            'files':['dut.v','properties.sv','safety.sby','README.txt'],
            'tool_requirements':['sby','yosys','z3']}
