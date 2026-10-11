"""Optional real external gate-level RTL vs executable DLS comparison.

This is NOT a replacement for formal equivalence: it generates a reproducible
sample testbench for an independently executed simulator (Icarus Verilog).
When the tool is absent or the sample protocol fails, no verification PASS is
issued. Supports combinational and single-clock synchronous DLS hierarchy.
"""
from __future__ import annotations
import itertools
import json
import random
from pathlib import Path
from .ir import DLS
from .project import atomic_write
from .tools import run_external

PREFIX='CCRTL_V1'


def make_vectors(d:DLS, count:int=64, seed:int=2781)->list[dict]:
    if not 1<=count<=256:raise ValueError('Requested RTL sample count must be within 1..256.')
    rng=random.Random(seed)
    widths=d.inputs
    vectors=[{name:0 for name in widths},
             {name:(1<<width)-1 for name,width in widths.items()}]
    total=sum(widths.values())
    if total<=8 and (1<<total)<=count:
        vectors=[dict(zip(widths,v)) for v in itertools.product(*(range(1<<w) for w in widths.values()))]
    else:
        vectors.extend({name:rng.getrandbits(width) for name,width in widths.items()} for _ in range(count-2))
    return vectors


def make_transaction_vectors(d:DLS, count:int=64, seed:int=2781)->list[dict]:
    """Exercise scheduled START/READY/DONE, preserving transaction inputs.

    The generated sample stream drives a clocked simulator and collects
    cycles both before/after DONE. It is not a source equivalence proof.
    """
    if not 8<=count<=256:raise ValueError('Scheduled RTL sample count must be between 8 and 256 cycles.')
    rng=random.Random(seed)
    sim=d.new_simulator()
    widths={k:v for k,v in d.inputs.items() if k not in ('start','stall','reset') and not k.startswith('unit_ready_')}
    controls=[k for k in d.inputs if k.startswith('unit_ready_')]
    vectors=[];started=0;done_count=0
    for i in range(count):
        probes={k:rng.getrandbits(w) for k,w in widths.items()}
        if i==0:probes={k:0 for k in widths}
        if i==16:probes={k:(1<<w)-1 for k,w in widths.items()}
        curr=sim.step({**probes,'start':0,**({'stall':0} if 'stall' in d.inputs else {}),
                       **({'reset':0} if 'reset' in d.inputs else {}),
                       **{k:1 for k in controls}},clock=False)
        start=(1 if curr.get('ready') and (i==0 or i%4==0) else 0)
        vector={**probes,'start':start,**{k:(0 if i%9==5 else 1) for k in controls}}
        if 'stall' in d.inputs:vector['stall']=int(i%13==7)
        if 'reset' in d.inputs:vector['reset']=0
        if start:started+=1
        vectors.append(vector)
        sim.step(vector,clock=True)
        observed=sim.step({**vector,'start':0},clock=False)
        if observed.get('done'):done_count+=1
    if not started or not done_count:
        raise ValueError('Sample vector budget did not complete a scheduled transaction; increase verification.rtl_vectors.')
    return vectors



def make_fabric_vectors(d:DLS,count:int=128,seed:int=2781)->list[dict]:
    """Deterministic clock-edge requests and environment-driven responses.

    Simulates real ready/valid acceptance, including stable external data
    during backpressure. This builds *stimulus*, not expected RTL outputs;
    expected values come from separately executing the serialized DLS.
    """
    if not 32<=count<=256:
        raise ValueError('Concurrent fabric requires 32..256 RTL stimulus cycles.')
    rng=random.Random(seed)
    spec=d.metadata['schedule'];clients=spec['clients'];width=spec['width']
    external=spec['operator']=='external'
    sim=d.new_simulator();result=[]
    # Track one outstanding external service operation, independent from DLS.
    outstanding=None
    due=0
    accepted_requests=0
    responses=0
    for clock in range(count):
        v={k:0 for k in d.inputs}
        v['reset']=int(clock==0 or clock==count//2)
        v['stall']=int(clock%19==11)
        for i in range(clients):
            v[f'response_ready_{i}']=int(clock%11 not in (2,3,4))
        if external:
            v['operator_request_ready']=int(clock%13 not in (4,5,6))
            if outstanding is not None and clock>=due:
                v['operator_response_valid']=1
                v['operator_response_data']=outstanding
        observed=sim.step(v,clock=False)
        for i in range(clients):
            # Issuing clients only drive request when their slot is free.
            # During accepted transactions their live inputs may change freely.
            if observed[f'request_ready_{i}'] and not v['reset'] and clock%5 in (0,1,2):
                v[f'request_{i}']=1
                v[f'opcode_{i}']=(clock+i)%4
                v[f'a_{i}']=rng.randrange(1<<width)
                v[f'b_{i}']=rng.randrange(1<<width)
                accepted_requests+=1
        observed=sim.step(v,clock=False)
        if external and observed['operator_request_valid'] and v['operator_request_ready']:
            if outstanding is not None:
                raise ValueError('Stimulus attempted overlapping external ALU operations.')
            a=observed['operator_request_a'];b=observed['operator_request_b']
            outstanding=(a*b if observed['operator_request_opcode']&1 else a+b)&((1<<width)-1)
            due=clock+1+(clock%7)
        if external and observed['operator_response_ready'] and v['operator_response_valid']:
            outstanding=None;responses+=1
        result.append(v)
        sim.step(v,clock=True)
        if v['reset']:outstanding=None
    if accepted_requests<3:
        raise ValueError('Fabric stimulus contained too few accepted requests.')
    return result

def make_testbench(d:DLS,vectors:list[dict])->str:
    d.validate()
    if not vectors:raise ValueError('No RTL test vectors provided.')
    inp=list(d.inputs);outs=list(d.outputs)
    lines=['`timescale 1ns/1ps','module cc_testbench;',
           '  reg clk = 0;' if d.requires_clock() else '  // Combinational DUT']
    for name,width in d.inputs.items():
        lines.append(f'  reg [{width-1}:0] {name} = {width}\'d0;')
    for name,bits in d.outputs.items():
        lines.append(f'  wire [{len(bits)-1}:0] {name};')
    ports=([ '.clk(clk)' ] if d.requires_clock() else []) + [f'.{name}({name})' for name in (*inp,*outs)]
    lines.append(f'  {d.name} dut({", ".join(ports)});')
    lines.append('  initial begin')
    for i,vector in enumerate(vectors):
        if set(vector)!=set(inp):raise ValueError(f'RTL vector {i} input ports do not match DLS interface.')
        for name,width in d.inputs.items():
            v=vector[name]
            if type(v)!=int or v<0 or v>=(1<<width):
                raise ValueError(f'RTL vector {i}, {name}: value does not fit {width} bits.')
            lines.append(f'    {name} = {width}\'d{v};')
        lines.append('    #2;')
        format_spec='|'.join(['%h']*len(outs))
        arg=(', '+', '.join(outs)) if outs else ''
        lines.append(f'    $display("{PREFIX}|{i}|{format_spec}"{arg});')
        if d.requires_clock():lines.extend(['    #1 clk=1;','    #1 clk=0;'])
    lines.extend([f'    $display("{PREFIX}_END|{len(vectors)}");','    $finish;','  end','endmodule',''])
    return '\n'.join(lines)


def check_rtl(d:DLS,rtl:Path,out:Path,issues,events,run_options:dict|None=None,
              vector_count:int=64)->dict:
    """Compile and *execute* exported RTL in a separate simulator.

    Returns status PASS, FAIL, UNAVAILABLE, or UNSUPPORTED. PASS indicates
    sampled gate-level agreement, never exhaustive temporal equivalence.
    """
    rtl=Path(rtl);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    scheduling=(d.metadata.get('schedule') or {}).get('mode')
    try:
        vectors=(make_transaction_vectors(d,vector_count) if scheduling in ('transactional','time_share')
                 else make_fabric_vectors(d,max(vector_count,32)) if scheduling=='concurrent_fabric'
                 else make_vectors(d,vector_count) if not scheduling
                 else None)
    except ValueError as exc:
        issue=issues.add('RTL.SAMPLE_CONFIG','ERROR','VERIFIER','rtl_check',str(exc),
                         remedy='Increase verification.rtl_vectors or inspect the generated handshake protocol.')
        return {'status':'FAIL','issue_id':issue.issue_id}
    if vectors is None:
        issue=issues.add('RTL.PROTOCOL_UNSUPPORTED','ERROR','VERIFIER','rtl_check',
            f'External RTL harness does not understand schedule.mode {scheduling!r}.',
            remedy='Choose a supported scheduling protocol or supply a specific testbench.')
        return {'status':'UNSUPPORTED','issue_id':issue.issue_id}
    bench=out/'rtl_check_tb.v';atomic_write(bench,make_testbench(d,vectors))
    vvp_file=out/'rtl_check.vvp'
    opts=run_options or {}
    compiled=run_external(['iverilog','-g2012','-s','cc_testbench','-o',vvp_file.name,rtl.name,bench.name],
                           out,out,issues,events,'rtl_compile',timeout=120,**opts)
    if compiled['status']!='PASS':return {'status':compiled['status'],'issue_id':compiled.get('issue_id'),
                                           'bench':str(bench),'compile':compiled}
    if not vvp_file.is_file() or not vvp_file.stat().st_size:
        issue=issues.add('RTL.BINARY_MISSING','ERROR','TOOL','rtl_check',
            'Icarus compiler exited zero but generated simulation executable is absent or empty.',
            evidence={'expected':str(vvp_file)},remedy='Inspect rtl_compile.log for the missing output.')
        return {'status':'FAIL','issue_id':issue.issue_id}
    executed=run_external(['vvp',vvp_file.name],out,out,issues,events,'rtl_execute',timeout=120,**opts)
    if executed['status']!='PASS':return {'status':executed['status'],'issue_id':executed.get('issue_id'),
                                           'bench':str(bench),'execute':executed}
    rows={};end=None;parse_errors=[]
    for line in (out/'rtl_execute.log').read_text(encoding='utf-8').splitlines():
        if not line.startswith('[STDOUT] '):continue
        raw=line[9:].strip()
        if raw.startswith(PREFIX+'_END|'):
            try:end=int(raw.split('|')[1])
            except (ValueError,IndexError):parse_errors.append(raw)
        elif raw.startswith(PREFIX+'|'):
            parts=raw.split('|')
            try:
                idx=int(parts[1])
                if idx in rows:raise ValueError('duplicate vector result')
                rows[idx]=parts[2:]
            except (ValueError,IndexError):parse_errors.append(raw)
    if end!=len(vectors) or len(rows)!=len(vectors) or parse_errors:
        issue=issues.add('RTL.OUTPUT_INCOMPLETE','ERROR','TOOL','rtl_check',
            'RTL simulation finished without the exact expected vector records.',
            evidence={'expected':len(vectors),'received':len(rows),'end_marker':end,'parse_errors':parse_errors[:5]},
            remedy='Inspect rtl_execute.log for simulator warnings, crashes, or protocol corruption.')
        return {'status':'FAIL','issue_id':issue.issue_id}
    sim=d.new_simulator();failures=[]
    for i,vector in enumerate(vectors):
        values=rows[i]
        if len(values)!=len(d.outputs):
            failures.append({'index':i,'reason':'wrong output arity','actual':values});break
        expected=sim.step(vector,clock=True)
        for (name,_),actual_text in zip(d.outputs.items(),values):
            try:actual=int(actual_text,16)
            except ValueError:
                failures.append({'index':i,'output':name,'reason':'RTL contains X/Z/invalid output',
                                 'rtl':actual_text,'expected_dls':expected[name],'inputs':vector})
                break
            if expected[name]!=actual:
                failures.append({'index':i,'inputs':vector,'output':name,'expected_dls':expected[name],
                                 'rtl':actual,'cycle':i})
                break
        if len(failures)>=8:break
    if failures:
        issue=issues.add('RTL.BEHAVIOR_MISMATCH','ERROR','VERIFIER','rtl_check',
            'Exported Verilog behavior does not match executable DLS on a sampled vector.',
            evidence={'counterexamples':failures,'seed':2781},
            cause='Either the structural export or an executable simulator disagrees with DLS.',
            remedy='Replay the counterexample in rtl_check_tb.v and inspect rtl_execute.log.')
        status='FAIL'
    else:status='PASS'
    result={'status':status,'vectors':len(vectors),'seed':2781,'exhaustive':False,
            'bench':str(bench),'compile_log':compiled.get('log'),
            'execute_log':executed.get('log'),'failures':failures,
            'meaning':'Sampled RTL-vs-DLS agreement; not formal or physical signoff'}
    atomic_write(out/'rtl_verification.json',json.dumps(result,indent=2))
    return result
