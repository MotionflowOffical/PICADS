"""v0.12 global source-operator sharing: real gates, contention and diagnostics."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import pytest

SOURCE='''def choose(a: u4, b: u4, multiply: bool) -> u8:
    if multiply:
        result: u8 = a * b
    else:
        result: u8 = a + b
    return result

def accumulate(a: u4, b: u4) -> u8:
    total: u8 = a + b
    total = total + a
    return total
'''
CLIENTS=[{'name':'lane0','function':'choose'},
         {'name':'lane1','function':'accumulate'},
         {'name':'lane2','function':'choose'}]
CO={'schedule':{'global_shared_types':['ADD','MUL'],'latencies':{'MUL':2}}}

def compile_(clients=None,co=None):
    from chipcompiler.global_sharing import compile_global_source_processes
    return compile_global_source_processes(SOURCE,clients or CLIENTS,co or CO,
                                           'PICADSSharedTest')


def test_one_physical_operator_per_kind():
    d=compile_()
    assert d.validate()
    assert d.metadata['schedule']['shared_physical_units']=={'ADD':1,'MUL':1}
    assert d.stats()['hierarchical_instances']==0
    assert sorted(d.metadata['schedule']['served_clients']['ADD'])==['lane0','lane1','lane2']
    assert sorted(d.metadata['schedule']['served_clients']['MUL'])==['lane0','lane2']
    assert d.stats()['primitive_gates']>10
    assert all(n.op not in ('ADD','MUL') for n in d.nodes)
    assert not d.submodules
    assert 'arb_grant_add_lane0' in d.outputs


def test_randomized_source_equivalence_12_rounds():
    from chipcompiler.global_sharing import check_global_source_processes
    from chipcompiler.diagnostics import IssueCollector
    d=compile_();r=check_global_source_processes(SOURCE,d,IssueCollector(),rounds=12)
    assert r['status']=='PASS',r
    assert r['completed_transactions']==36


def test_mixed_input_widths_and_shared_add_only():
    src='''def first(a:u3,b:u4)->u8:
    x:u8=a+b
    return x

def second(a:u6,b:u2)->u8:
    x:u8=a+b
    return x
'''
    from chipcompiler.global_sharing import compile_global_source_processes,check_global_source_processes
    from chipcompiler.diagnostics import IssueCollector
    clients=[{'name':'x','function':'first'},{'name':'y','function':'second'}]
    co={'schedule':{'global_shared_types':['ADD']}}
    issues=IssueCollector();d=compile_global_source_processes(src,clients,co,'Widths',issues)
    assert d.validate()
    r=check_global_source_processes(src,d,issues,rounds=15)
    assert r['status']=='PASS',r


def test_local_memory_remains_private():
    src='''def local_store(addr:u2, value:u4, write:bool)->u4:
    if write:
        mem_write(addr,value)
    data:u4=mem_read(addr)
    plus:u4=data+value
    return plus
'''
    from chipcompiler.global_sharing import compile_global_source_processes,check_global_source_processes
    from chipcompiler.diagnostics import IssueCollector
    clients=[{'name':'one','function':'local_store'},{'name':'two','function':'local_store'}]
    cfg={'schedule':{'global_shared_types':['ADD']},'memory':{'depth':4,'data_width':4}}
    issues=IssueCollector()
    d=compile_global_source_processes(src,clients,cfg,'LocalMem',issues)
    assert sum(n.startswith('p_one__mem_') for n in d.registers)==4
    assert sum(n.startswith('p_two__mem_') for n in d.registers)==4
    result=check_global_source_processes(src,d,issues,rounds=6)
    assert result['status']=='PASS',result


def test_mutation_rejected_by_independent_scoreboard():
    from chipcompiler.global_sharing import check_global_source_processes
    from chipcompiler.diagnostics import IssueCollector
    d=compile_()
    assert check_global_source_processes(SOURCE,d,IssueCollector(),rounds=4)['status']=='PASS'
    # Corrupt the actual shared ALU result; deterministic all-zero output.
    target=[n for n in d.nodes if n.name=='shared_mul_lane0_result_0'][0]
    target.inputs=['@0']
    observed=check_global_source_processes(SOURCE,d,IssueCollector(),rounds=20)
    assert observed['status']=='FAIL',observed
    assert observed['reason']=='source result mismatch'


def test_rtl_and_dls_serialization(tmp_path):
    from chipcompiler.export import export_verilog
    from chipcompiler.ir import DLS
    from chipcompiler.rtl_check import make_source_process_vectors,make_testbench
    d=compile_();path=tmp_path/'shared.dls';d.save(path)
    restored=DLS.load(path)
    assert restored.stats()==d.stats()
    rtl=export_verilog(restored,tmp_path/(restored.name+'.v')).read_text()
    assert 'always @(posedge clk)' in rtl
    assert rtl.count('module PICADSSharedTest(')==1
    assert 'arb_grant_add_lane0' in rtl
    vectors=make_source_process_vectors(restored,128)
    bench=make_testbench(restored,vectors)
    assert len(vectors)==128
    assert 'CCRTL_V1_END|128' in bench


def test_reject_invalid_config_and_client_declarations():
    from chipcompiler.global_sharing import compile_global_source_processes
    for types in ([],['DIV'],['ADD','ADD']):
        with pytest.raises(ValueError,match='GLOBAL_SHARE_TYPES'):
            compile_global_source_processes(SOURCE,CLIENTS,{'schedule':{'global_shared_types':types}},'X')
    with pytest.raises(ValueError,match='GLOBAL_UNUSED_OPERATOR'):
        compile_global_source_processes(SOURCE,[{'name':'l','function':'accumulate'},
                                                    {'name':'r','function':'accumulate'}],CO,'X')
    with pytest.raises(ValueError,match='PROCESS_DUPLICATE'):
        compile_global_source_processes(SOURCE,[CLIENTS[0],CLIENTS[0]],CO,'X')


def test_topological_cycle_detection():
    from chipcompiler.global_sharing import _ordered_nodes
    from chipcompiler.ir import Node
    with pytest.raises(ValueError,match='COMBINATIONAL_CYCLE'):
        _ordered_nodes([Node('a','NOT',['b']),Node('b','NOT',['a'])],{}, {})
    with pytest.raises(ValueError,match='UNCONNECTED'):
        _ordered_nodes([Node('a','NOT',['nonexistent'])],{}, {})


def test_formal_collateral_bounded_only(tmp_path):
    from chipcompiler.formal import prepare_global_shared_formal
    d=compile_()
    generated=prepare_global_shared_formal(d,tmp_path,depth=16)
    assert generated['status']=='GENERATED_UNVERIFIED'
    text=(tmp_path/'properties.sv').read_text()
    assert 'assert(!(arb_grant_add_lane0 && arb_grant_add_lane1))' in text
    assert 'assert(!arb_grant_mul_lane0 ||' in text
    assert 'mode bmc' in (tmp_path/'safety.sby').read_text()


def test_real_project_build_with_global_metadata(tmp_path):
    import shutil
    from chipcompiler.pipeline import BuildSession
    original=Path(__file__).resolve().parents[1]/'examples'/'global_shared_processes'
    directory=tmp_path/'hardware'
    shutil.copytree(original,directory,ignore=shutil.ignore_patterns('build'))
    outcome=BuildSession(directory).run()
    assert outcome.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),outcome.as_dict()
    assert outcome.stages['equivalence']['status']=='PASS_SAMPLED'
    assert outcome.stages['scheduling']['physical_shared_units']=={'ADD':1,'MUL':1}
    scheduler=json.loads(Path(outcome.files['global_schedule']).read_text())
    assert scheduler['shared_physical_units']=={'ADD':1,'MUL':1}


def test_invalid_project_co_configuration_fails_causally(tmp_path):
    import shutil
    from chipcompiler.pipeline import BuildSession
    original=Path(__file__).resolve().parents[1]/'examples'/'global_shared_processes'
    target=tmp_path/'bad';shutil.copytree(original,target,ignore=shutil.ignore_patterns('build'))
    (target/'architecture.co').write_text('schedule:\n  mode: source_processes\n  global_shared_types: [DIV]\n')
    result=BuildSession(target).run()
    assert result.status=='FAILED',result.as_dict()
    assert any('GLOBAL_SHARE_TYPES' in x['code'] for x in result.issues)
    assert result.stages['generate']['status']=='BLOCKED'


def test_round_robin_grants_three_simultaneous_clients():
    from chipcompiler.global_sharing import compile_global_source_processes
    source='def add(a:u4,b:u4)->u5:\n    return a+b\n'
    names=('x','y','z')
    design=compile_global_source_processes(source,
        [{'name':name,'function':'add'} for name in names],
        {'schedule':{'global_shared_types':['ADD']}},'RoundRobin3')
    sim=design.new_simulator()
    driver={name:0 for name in design.inputs}
    driver['reset']=1;sim.step(driver);driver['reset']=0
    for i,name in enumerate(names):
        driver[name+'_start']=1
        driver[name+'_a']=i+2
        driver[name+'_b']=5
    sim.step(driver)
    for name in names:driver[name+'_start']=0
    winner=[]
    for edge in range(8):
        outs=sim.step(driver,clock=False)
        granted=[name for name in names if outs[f'arb_grant_add_{name}']]
        assert len(granted)<=1
        winner+=granted
        sim.step(driver)
    assert winner==list(names)
    for name in names:
        assert sim.step(driver,clock=False)[f'{name}_result']==({'x':7,'y':8,'z':9}[name])


def test_reset_during_contention_clears_controller():
    from chipcompiler.global_sharing import compile_global_source_processes
    source='def add(a:u4,b:u4)->u5:\n    return a+b\n'
    names=('x','y','z')
    design=compile_global_source_processes(source,
        [{'name':name,'function':'add'} for name in names],
        {'schedule':{'global_shared_types':['ADD']}},'ResetFair')
    sim=design.new_simulator();v={port:0 for port in design.inputs}
    v['reset']=1;sim.step(v);v['reset']=0
    for name in names:v[name+'_start']=1;v[name+'_a']=3;v[name+'_b']=8
    sim.step(v)
    for name in names:v[name+'_start']=0
    sim.step(v)
    v['reset']=1;sim.step(v)
    for name in names:
        assert sim.step(v,clock=False)[name+'_ready']==1
        assert sim.step(v,clock=False)[name+'_done']==0
    assert sim.register_snapshot()['ResetFair/r_rr_add_0']==1
    assert all(sim.register_snapshot()[f'ResetFair/r_rr_add_{i}']==0 for i in (1,2))


def test_sharing_area_overhead_is_disclosed_not_hidden():
    from chipcompiler.diagnostics import IssueCollector
    issues=IssueCollector()
    from chipcompiler.global_sharing import compile_global_source_processes
    design=compile_global_source_processes(SOURCE,CLIENTS,CO,'AreaDisclosure',issues)
    estimate=design.metadata['gate_cost_comparison']
    assert estimate['shared_primitive_gates']==design.stats()['primitive_gates']
    assert estimate['independent_primitive_gates']>0
    assert estimate['delta_shared_minus_independent']==(estimate['shared_primitive_gates']-
                                                          estimate['independent_primitive_gates'])
    if estimate['delta_shared_minus_independent']>0:
        assert any(i.code=='CO.GLOBAL_GATE_OVERHEAD' for i in issues.warnings)
