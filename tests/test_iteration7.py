"""v0.7 transactional CFG, genuine shared gate units, handshakes and arbitration."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from chipcompiler.transactional import TransactionalCompiler
from chipcompiler.transactional_verify import verify_transactional
from chipcompiler.diagnostics import IssueCollector,DiagnosticException
from chipcompiler.arbitration import round_robin_arbiter
from chipcompiler.export import verilog
from chipcompiler.ir import DLS
from chipcompiler.network import compile_network
from chipcompiler.pipeline import BuildSession

BRANCH='''def calculate(a:u4,b:u4,choose:bool)->u8:\n    if choose:\n        answer:u8=a*b\n    else:\n        answer:u8=a+b\n    return answer\n'''
MEMORY='''def calculate(addr:u3,value:u5,write:bool)->u5:\n    if write:\n        mem_write(addr,value)\n    fetched:u5=mem_read(addr)\n    return fetched\n'''
LOOP='''def calculate(x:u4)->u6:\n    total:u6=0\n    for i in range(4):\n        total=total+x\n    return total\n'''

def compile_(source,co=None):
    issues=IssueCollector();d=TransactionalCompiler(issues,co or {'schedule':{'mode':'transactional'}}).compile_source(source)
    return d,issues

@pytest.mark.parametrize('source,co',[
    (BRANCH,{'schedule':{'mode':'transactional'}}),
    (BRANCH,{'schedule':{'mode':'transactional','latencies':{'ADD':3,'MUL':4},'ready_types':['ADD','MUL']}}),
    (MEMORY,{'schedule':{'mode':'transactional'},'memory':{'depth':4,'data_width':5}}),
    (MEMORY,{'schedule':{'mode':'transactional','latencies':{'READ':2,'WRITE':3},'ready_types':['READ','WRITE']},'memory':{'depth':4,'data_width':5}}),
    (LOOP,{'schedule':{'mode':'transactional'}}),
])
def test_independent_source_comparison(source,co):
    d,issues=compile_(source,co)
    report=verify_transactional(source,d,issues,48)
    assert report.status=='PASS_SAMPLED',report.failures
    assert 'module calculate' in verilog(d)
    assert d.validate()

def test_branch_only_selected_path_runs():
    d,_=compile_(BRANCH)
    sim=d.new_simulator()
    inps={'a':4,'b':7,'choose':0,'start':1,'stall':0,'reset':0}
    sim.step(inps)
    visited=[]
    for _ in range(15):
        state=sim.register_snapshot()
        visited += [k for k,v in state.items() if '/r_pc_' in k and v]
        sim.step({**inps,'start':0})
        if sim.step({**inps,'start':0},clock=False)['done']:break
    assert not any('/r_pc_1_' in k or '/r_pc_2_' in k for k in visited)
    assert sim.step({**inps,'start':0},clock=False)['result']==11

def test_handshake_stall_freezes_every_register():
    d,_=compile_(BRANCH,{'schedule':{'mode':'transactional','latencies':{'MUL':3}}})
    sim=d.new_simulator();x={'a':3,'b':6,'choose':1,'start':1,'stall':0,'reset':0}
    sim.step(x)
    before=sim.register_snapshot()
    for _ in range(5):
        sim.step({**x,'a':14,'b':15,'stall':1},clock=True)
        assert sim.register_snapshot()==before

def test_round_robin_exact_rotation():
    for n in (2,3,5,8):
        d=round_robin_arbiter(n,6)
        sim=d.new_simulator()
        v={**{f'request_{i}':1 for i in range(n)},**{f'payload_{i}':i+20 for i in range(n)},
           'resource_ready':1,'stall':0,'reset':0}
        for t in range(2*n):
            output=sim.step(v,clock=False)
            assert output['selected_client']==t%n
            assert output['selected_payload']==20+t%n
            assert sum(output[f'grant_{i}'] for i in range(n))==1
            sim.step(v)
        assert 'posedge clk' in verilog(d)

def test_arbiter_wait_and_stall_do_not_advance():
    d=round_robin_arbiter(3)
    sim=d.new_simulator()
    base={**{f'request_{i}':1 for i in range(3)},**{f'payload_{i}':i+20 for i in range(3)}}
    for ready,stall in ((0,0),(1,1),(0,1)):
        before=sim.register_snapshot()
        out=sim.step({**base,'resource_ready':ready,'stall':stall,'reset':0})
        assert not any(out[f'grant_{i}'] for i in range(3))
        assert sim.register_snapshot()==before
    assert sim.step({**base,'resource_ready':1,'stall':0,'reset':0},clock=False)['grant_0']==1

def test_arbiter_no_request():
    d=round_robin_arbiter(2)
    sim=d.new_simulator()
    o=sim.step({'request_0':0,'request_1':0,'payload_0':0,'payload_1':0,'resource_ready':1,'stall':0,'reset':0})
    assert o['resource_valid']==0 and o['grant_0']==0 and o['grant_1']==0

@pytest.mark.parametrize('source,code',[
    ('''def calculate(x:u4)->u4:\n    if x:\n        a:u4=1\n    return a\n''','CO.CFG_UNINITIALIZED'),
    ('''def calculate(x:u4)->u4:\n    return missing\n''','SOURCE.UNDEFINED_SYMBOL'),
    ('''def calculate(x:u4)->u4:\n    while x:\n        x=x-1\n    return x\n''','CO.CFG_STATEMENT'),
    ('''def calculate(x:u4)->u4:\n    y=x+1\n    y=x*x\n    return y\n''','CO.CFG_IMPLICIT_TRUNCATION'),
    ('''def calculate(x:u4)->u4:\n    if x:\n        return x\n''','CO.CFG_FALLTHROUGH'),
])
def test_unsupported_cfg_explicit_error(source,code):
    with pytest.raises(DiagnosticException) as exc:
        compile_(source)
    assert exc.value.issue.code==code

@pytest.mark.parametrize('config',[
    {'schedule':{'mode':'transactional'},'memory':{'depth':0,'data_width':8}},
    {'schedule':{'mode':'transactional','latencies':{'MUL':0}}},
    {'schedule':{'mode':'transactional','ready_types':['bogus']}},
])
def test_invalid_configuration_fails(config):
    with pytest.raises(DiagnosticException):compile_(BRANCH,config)

def test_dls_round_trip(tmp_path):
    d,_=compile_(MEMORY,{'schedule':{'mode':'transactional'},'memory':{'depth':4,'data_width':5}})
    target=tmp_path/'run.dls';d.save(target)
    loaded=DLS.load(target)
    assert d.to_dict()==loaded.to_dict()
    assert loaded.stats()['state_bits']>0

def test_arbiter_binding_in_mcd_network():
    src='''def calculate(request_0:bool,request_1:bool,payload_0:u4,payload_1:u4,resource_ready:bool,stall:bool,reset:bool)->u4:\n    return payload_0\n'''
    inputs={k:k for k in ('request_0','request_1','payload_0','payload_1','resource_ready','stall','reset')}
    mcd={'network':{'instances':[{'name':'arb','primitive':'round_robin_arbiter','clients':2,
                                  'payload_width':4,'inputs':inputs}],
                    'outputs':{'result':'arb.selected_payload'}}}
    result=compile_network(src,'<test>','calculate',mcd)
    assert result.design.instances[0]['module']=='rr_arbiter_2_4'
    assert '.clk(clk)' in verilog(result.design)

def test_arbiter_bad_mcd_configuration():
    src='''def calculate(x:u4)->u4:\n    return x\n'''
    mcd={'network':{'instances':[{'name':'bad','primitive':'round_robin_arbiter','clients':22,
                                  'payload_width':4}], 'outputs':{'result':'bad.selected_payload'}}}
    with pytest.raises(DiagnosticException) as exc:compile_network(src,'x','calculate',mcd)
    assert exc.value.issue.code=='MCD.NETWORK.ARBITER_CONFIG'

def test_two_example_projects_end_to_end(tmp_path):
    base=Path(__file__).parents[1] / 'examples'
    for name in ('transactional_controller','transactional_memory'):
        r=BuildSession(base/name,build_dir=tmp_path/name).run()
        assert r.status=='SUCCESS_WITH_WARNINGS',r.issues
        assert r.stages['equivalence']['status']=='PASS_SAMPLED'
        assert Path(r.files['verilog']).is_file()
        metadata=json.loads(Path(r.files['dls']).read_text())['metadata']['schedule']
        assert metadata['mode']=='transactional'

def test_synchronous_reset_clears_memory_and_controller_even_when_stalled():
    d,_=compile_(MEMORY,{'schedule':{'mode':'transactional'},'memory':{'depth':4,'data_width':5}})
    sim=d.new_simulator()
    inp={'addr':2,'value':19,'write':1,'start':1,'stall':0,'reset':0}
    sim.step(inp)
    for _ in range(20):
        post=sim.step({**inp,'start':0},clock=True)
        if sim.step({**inp,'start':0},clock=False)['done']:break
    assert sim.register_snapshot()[f'{d.name}/r_mem_2']==19
    sim.step({**inp,'reset':1,'stall':1},clock=True)
    state=sim.register_snapshot()
    assert state[f'{d.name}/r_mem_2']==0
    assert state[f'{d.name}/r_idle']==1
    assert state[f'{d.name}/r_done']==0
    assert state[f'{d.name}/r_fault']==0


def test_arbitration_synchronous_reset_restarts_priority():
    d=round_robin_arbiter(3)
    sim=d.new_simulator()
    v={'resource_ready':1,'stall':0,'reset':0,**{f'request_{i}':1 for i in range(3)},
       **{f'payload_{i}':i+1 for i in range(3)}}
    sim.step(v)
    assert sim.step(v,clock=False)['selected_client']==1
    sim.step({**v,'reset':1},clock=True)
    assert sim.step(v,clock=False)['selected_client']==0


def test_multi_cycle_request_port_indicates_active_unit():
    d,_=compile_(BRANCH,{'schedule':{'mode':'transactional',
                                       'latencies':{'MUL':4},'ready_types':['MUL']}})
    sim=d.new_simulator()
    inp={'a':2,'b':5,'choose':1,'start':1,'stall':0,'reset':0,'unit_ready_mul':0}
    sim.step(inp)
    busy_seen=False
    for _ in range(20):
        state=sim.step({**inp,'start':0},clock=False)
        busy_seen|=bool(state['unit_active_mul'])
        if busy_seen:
            before=sim.register_snapshot()
            for _ in range(3):
                sim.step({**inp,'start':0,'stall':1})
                assert sim.register_snapshot()==before
            break
        sim.step({**inp,'start':0})
    assert busy_seen


def test_scheduled_external_rtl_testbench_is_generated_without_faking_tool(tmp_path):
    from chipcompiler.rtl_check import check_rtl,make_transaction_vectors,make_testbench
    from chipcompiler.diagnostics import EventLog
    d,issues=compile_(BRANCH,{'schedule':{'mode':'transactional'}})
    v=make_transaction_vectors(d,64)
    assert sum(int(x['start']) for x in v)>1
    bench=make_testbench(d,v)
    assert 'posedge' not in bench and "clk=1" in bench
    rtl=tmp_path/'calculate.v';rtl.write_text(verilog(d))
    # The environment lacks Icarus: an absent tool must NOT become PASS.
    result=check_rtl(d,rtl,tmp_path,issues,EventLog(tmp_path/'events.jsonl'),vector_count=64)
    assert result['status']!='PASS'
    assert (tmp_path/'rtl_check_tb.v').is_file()
    assert any(i.code=='TOOL.MISSING' for i in issues.issues)


def test_terminal_if_else_return_only():
    source='''def calculate(a:u4,b:u4,flag:bool)->u5:\n    if flag:\n        return a+b\n    else:\n        return a-b\n'''
    d,i=compile_(source)
    assert verify_transactional(source,d,i,32).status=='PASS_SAMPLED'


def test_pure_ternary_and_boolean_cfg():
    ss=['''def calculate(a:u4,b:u4,c:bool)->u8:\n    return a*b if c else b*a\n''',
        '''def calculate(a:u4,b:u4,c:bool)->u1:\n    if (a<b) and c:\n        return 1\n    return 0\n''']
    for source in ss:
        d,i=compile_(source)
        assert verify_transactional(source,d,i,24).status=='PASS_SAMPLED'


def test_bounded_for_loop_under_transactional_mode():
    d,i=compile_(LOOP)
    assert verify_transactional(LOOP,d,i,30).status=='PASS_SAMPLED'
    assert d.metadata['schedule']['instruction_count']>=10

def test_mutated_generated_dls_is_reported_as_real_counterexample():
    d,issues=compile_(BRANCH)
    d.outputs['result']=['@0']*8
    outcome=verify_transactional(BRANCH,d,issues,15)
    assert outcome.status=='FAIL'
    assert outcome.failures and outcome.failures[0]['execution_trace']
    assert any(i.code=='VERIFY.CFG_MISMATCH' and i.evidence.get('first_counterexample') for i in issues.issues)


def test_unselected_memory_branch_does_not_fault():
    source='''def calculate(addr:u4,select:bool)->u5:\n    if select:\n        result:u5=mem_read(addr)\n    else:\n        result:u5=7\n    return result\n'''
    d,i=compile_(source,{'schedule':{'mode':'transactional'},'memory':{'depth':3,'data_width':5}})
    assert verify_transactional(source,d,i,42).status=='PASS_SAMPLED'
    sim=d.new_simulator()
    x={'addr':15,'select':0,'start':1,'stall':0,'reset':0}
    sim.step(x)
    for _ in range(12):
        sim.step({**x,'start':0})
        result=sim.step({**x,'start':0},clock=False)
        if result['done']:
            assert result['result']==7 and result['fault']==0
            break
    else:pytest.fail('Branch transaction never completed')


def test_transactional_c_subset_example_builds(tmp_path):
    r=BuildSession(Path(__file__).parents[1]/'examples'/'transactional_c',build_dir=tmp_path/'c').run()
    assert r.status=='SUCCESS_WITH_WARNINGS',r.issues
    assert r.stages['equivalence']['status']=='PASS_SAMPLED'
    assert Path(r.files['normalized_source']).is_file()
    assert Path(r.files['co_schedule']).is_file()


def test_co_bad_memory_configuration_blocks_upstream_not_fake_route(tmp_path):
    project=tmp_path/'invalid_memory';project.mkdir()
    (project/'chip.yaml').write_text('name: InvalidMemory\nsource: circuit.py\nmcd: design.mcd\nco: architecture.co\n')
    (project/'circuit.py').write_text(BRANCH)
    (project/'design.mcd').write_text('top: calculate\n')
    (project/'architecture.co').write_text('schedule:\n  mode: transactional\nmemory:\n  depth: 0\n  data_width: 8\n')
    r=BuildSession(project).run()
    assert r.status=='FAILED'
    assert any(i['code']=='CO.MEMORY_SPEC' and i['origin']=='CO' for i in r.issues)
    assert r.stages['generate']['status']=='BLOCKED'
    assert 'physical' not in r.stages or r.stages['physical']['status']!='PASS'
