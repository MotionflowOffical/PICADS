"""MCD explicit network composition: typed connections, causality, independent state."""
from pathlib import Path
import copy
import pytest
from chipcompiler.network import compile_network
from chipcompiler.diagnostics import IssueCollector, DiagnosticException
from chipcompiler.verification import verify
from chipcompiler.export import verilog
from chipcompiler.pipeline import BuildSession
from chipcompiler.ir import DLS

SOURCE='''def add(a:u4,b:u4)->u5:\n return a+b\ndef mul(a:u4,b:u4)->u8:\n return a*b\ndef choose(sum_value:u5,product:u8,flag:bool)->u8:\n return product if flag else sum_value\ndef top(a:u4,b:u4,flag:bool)->u8:\n return a*b if flag else a+b\n'''
NETWORK={'network':{'instances':[
    {'name':'select','function':'choose','inputs':{'sum_value':'s.result','product':'m.result'}},
    {'name':'m','function':'mul'},
    {'name':'s','function':'add'},
], 'outputs':{'result':'select.result'}}}

def test_network_infers_external_ports_sorts_dependencies_and_exhaustively_verifies():
    outcome=compile_network(SOURCE,'design.py','top',NETWORK)
    d=outcome.design
    assert d.metadata['network']['topological_order']==['m','s','select']
    assert d.instances[-1]['name']=='select'
    assert len([c for c in outcome.connections if c['mode']=='auto-top'])==5
    assert verify(SOURCE,d,IssueCollector()).status=='PASS_EXHAUSTIVE'
    assert 'choose select' in verilog(d)


def test_network_roundtrip(tmp_path):
    d=compile_network(SOURCE,'design.py','top',NETWORK).design
    file=tmp_path/'x.dls';d.save(file)
    assert DLS.load(file).new_simulator().step({'a':7,'b':9,'flag':1})=={'result':63}
    assert DLS.load(file).new_simulator().step({'a':7,'b':9,'flag':0})=={'result':16}


@pytest.mark.parametrize('change,code',[
    (lambda n:n['instances'][0]['inputs'].update({'sum_value':'none.result'}),'UNKNOWN_INSTANCE'),
    (lambda n:n['instances'][0]['inputs'].update({'sum_value':'s.no_such_output'}),'UNKNOWN_OUTPUT'),
    (lambda n:n['instances'][0]['inputs'].update({'sum_value':'top.a'}),'WIDTH'),
    (lambda n:n['instances'][0]['inputs'].update({'sum_value':'s.result[5:0]'}),'SLICE'),
    (lambda n:n['instances'][0]['inputs'].update({'missing_port':'top.a'}),'UNKNOWN_PORT'),
    (lambda n:n['instances'][1].update({'inputs': {'a':'select.result'}}),'WIDTH'),
    (lambda n:n['outputs'].update({'result':'s.result'}),'OUTPUT_WIDTH'),
    (lambda n:n['instances'][0].update({'function':'missing'}),'UNKNOWN_FUNCTION'),
])
def test_bad_network_has_specific_origin(change,code):
    m=copy.deepcopy(NETWORK);change(m['network']);diagnostics=IssueCollector()
    with pytest.raises(DiagnosticException):compile_network(SOURCE,'design.py','top',m,issues=diagnostics)
    assert any(i.code=='MCD.NETWORK.'+code for i in diagnostics.errors),[x.code for x in diagnostics.errors]
    assert all(i.origin=='MCD' for i in diagnostics.errors)
    assert not any(i.code=='INTERNAL.UNEXPECTED' for i in diagnostics.errors)


def test_unknown_connections_report_multiple_independent_errors():
    m=copy.deepcopy(NETWORK)
    m['network']['instances'][0]['inputs'].update({'sum_value':'x.result','product':'m.bogus'})
    issues=IssueCollector()
    with pytest.raises(DiagnosticException):compile_network(SOURCE,'design.py','top',m,issues=issues)
    assert {i.code for i in issues.errors}>={'MCD.NETWORK.UNKNOWN_INSTANCE','MCD.NETWORK.UNKNOWN_OUTPUT'}


def test_cyclic_instances_rejected_without_downstream_cascade():
    source='''def passthrough(a:u4)->u4:\n return a\ndef top(a:u4)->u4:\n return a\n'''
    m={'network':{'instances':[{'name':'u','function':'passthrough','inputs':{'a':'v.result'}},
                                 {'name':'v','function':'passthrough','inputs':{'a':'u.result'}}],
                  'outputs':{'result':'u.result'}}}
    issues=IssueCollector()
    with pytest.raises(DiagnosticException):compile_network(source,'x.py','top',m,issues=issues)
    assert 'MCD.NETWORK.CYCLE' in [i.code for i in issues.errors]


def test_instance_register_state_and_project_pipeline(tmp_path):
    from chipcompiler.cli import init_project
    src='''def delay(x:u4)->u4:\n return reg("q",x,init=0)\ndef combine(x:u4,y:u4)->u5:\n return x+y\ndef top(a:u4,b:u4)->u5:\n return delay(a)+delay(b)\n'''
    mcd='''top: top
modules:
  - {name: Delay, function: delay}
requires:
  - {module: Delay, min_instances: 2}
network:
  instances:
    - {name: one, function: delay, inputs: {x: a}}
    - {name: two, function: delay, inputs: {x: b}}
    - {name: summer, function: combine, inputs: {x: one.result, y: two.result}}
  outputs: {result: summer.result}
'''
    root=tmp_path/'project';init_project(root)
    (root/'circuit.py').write_text(src)
    (root/'design.mcd').write_text(mcd)
    (root/'architecture.co').write_text('modules:\n  naming: mcd\n  hierarchy: preserve\n')
    res=BuildSession(root).run()
    assert res.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),res.issues
    assert res.stages['network']['status']=='PASS'
    assert res.stages['equivalence']['status']=='PASS_SAMPLED'
    d=DLS.load(Path(res.files['dls']))
    assert len(d.instances)==3 and d.requires_clock()
    assert verilog(d).count('Delay ')==2
    sim=d.new_simulator()
    assert sim.step({'a':3,'b':7})=={'result':0}
    assert sim.step({'a':5,'b':1})=={'result':10}
    assert sim.step({'a':9,'b':2})=={'result':6}
    assert len(sim.register_snapshot())==2


def test_project_network_conflicting_schedule_fails_explicitly(tmp_path):
    from chipcompiler.cli import init_project
    root=tmp_path/'project';init_project(root)
    (root/'circuit.py').write_text(SOURCE)
    import yaml
    (root/'design.mcd').write_text(yaml.safe_dump({'top':'top',**NETWORK}))
    (root/'architecture.co').write_text('schedule:\n  mode: time_share\n')
    res=BuildSession(root).run()
    assert res.status=='FAILED'
    assert any(i['code']=='MCD.NETWORK_SCHEDULE_CONFLICT' for i in res.issues)
    assert res.stages['equivalence']['status']=='BLOCKED'

@pytest.mark.parametrize('source,vectors',[
    ('''def top(x:u4,en:bool)->u4:\n return reg("q",x,init=2,enable=en)\n''',
     [({'x':9,'en':0},2),({'x':8,'en':1},2),({'x':3,'en':0},8),({'x':1,'en':1},8),({'x':0,'en':0},1)]),
    ('''def top(x:u4,rst:bool)->u4:\n return reg("q",x,init=3,reset=rst)\n''',
     [({'x':7,'rst':0},3),({'x':4,'rst':1},7),({'x':5,'rst':0},3),({'x':2,'rst':0},5)]),
    ('''def top(x:u4,en:bool,rst:bool)->u4:\n return reg("q",x,init=6,enable=en,reset=rst)\n''',
     [({'x':7,'en':1,'rst':0},6),({'x':12,'en':0,'rst':0},7),({'x':8,'en':0,'rst':1},7),({'x':0,'en':1,'rst':0},6)]),
])
def test_reg_enable_reset_source_reference_and_gate_level_verilog(source,vectors):
    from chipcompiler.generator import HardwareCompiler
    d=HardwareCompiler().compile_source(source,top='top')
    assert len(d.registers)==1
    assert 'always @(posedge clk)' in verilog(d)
    sim=d.new_simulator()
    for inp,expected in vectors:
        assert sim.step(inp)=={'result':expected}
    rep=verify(source,d,IssueCollector(),cycles=96)
    assert rep.status=='PASS_SAMPLED',rep.failures


def test_register_enable_reset_in_independent_child_instances():
    from chipcompiler.generator import HardwareCompiler
    src='''def gated(x:u4,en:bool,rst:bool)->u4:\n return reg("q",x,init=1,enable=en,reset=rst)\ndef top(a:u4,b:u4,e1:bool,e2:bool,r:bool)->u5:\n return gated(a,e1,r)+gated(b,e2,r)\n'''
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(src,top='top')
    rep=verify(src,d,IssueCollector(),cycles=96)
    assert rep.status=='PASS_SAMPLED',rep.failures
    sim=d.new_simulator()
    assert sim.step({'a':4,'b':3,'e1':1,'e2':0,'r':0})=={'result':2}
    assert sim.step({'a':2,'b':9,'e1':0,'e2':1,'r':0})=={'result':5}
    assert sim.step({'a':0,'b':0,'e1':0,'e2':0,'r':1})=={'result':13}
    assert sim.step({'a':0,'b':0,'e1':0,'e2':0,'r':0})=={'result':2}


def test_invalid_reg_keyword_is_source_error_not_internal_crash():
    from chipcompiler.generator import HardwareCompiler
    source='''def top(x:u4)->u4:\n return reg("q",x,enabel=True)\n'''
    with pytest.raises(DiagnosticException) as exc:
        HardwareCompiler().compile_source(source,top='top')
    assert exc.value.issue.code=='SOURCE.REG_KEYWORD'

@pytest.mark.parametrize('corruption,code',[
    ({'mystery':'not implemented'},'MCD.NETWORK.UNKNOWN_FIELD'),
    ({'instances':[{'name':'f','function':'add','unknown_feature':True}]},'MCD.NETWORK.UNKNOWN_INSTANCE_FIELD'),
])
def test_unimplemented_network_directives_are_errors(corruption,code):
    m=copy.deepcopy(NETWORK);m['network'].update(corruption)
    issues=IssueCollector()
    with pytest.raises(DiagnosticException):compile_network(SOURCE,'x.py','top',m,issues=issues)
    assert code in [i.code for i in issues.errors]


@pytest.mark.parametrize('source,code',[
    ('def top(a:u4)->u4:\n return reg("not safe!", a)\n','SOURCE.REG_NAME'),
    ('def top(a:u4)->u4:\n x=reg("q",a)\n return reg("q",x)\n','SOURCE.REG_DUPLICATE'),
])
def test_bad_register_description_produces_source_diagnostic(source,code):
    from chipcompiler.generator import HardwareCompiler
    with pytest.raises(DiagnosticException) as e:
        HardwareCompiler().compile_source(source,top='top')
    assert e.value.issue.code==code


def test_optional_external_rtl_testbench_is_structural_and_clocked(tmp_path):
    from chipcompiler.rtl_check import make_testbench,make_vectors
    from chipcompiler.generator import HardwareCompiler
    source='''def inner(x:u4,en:bool)->u4:\n return reg("q",x,enable=en,init=1)\ndef top(x:u4,en:bool)->u4:\n return inner(x,en)\n'''
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(source,top='top')
    vectors=make_vectors(d,10)
    bench=make_testbench(d,vectors)
    assert 'reg clk = 0;' in bench
    assert '.clk(clk)' in bench
    assert f'CCRTL_V1_END|{len(vectors)}' in bench
    assert bench.count('clk=1;')==len(vectors)
    assert 'top dut' in bench


def test_rtl_probe_does_not_claim_success_when_simulator_missing(tmp_path,monkeypatch):
    from chipcompiler.rtl_check import check_rtl
    from chipcompiler.generator import HardwareCompiler
    from chipcompiler.diagnostics import EventLog
    import chipcompiler.rtl_check as rc
    d=HardwareCompiler().compile_source('def top(x:u4)->u4:\n return x ^ 3\n',top='top')
    rtl=tmp_path/'top.v';rtl.write_text(verilog(d))
    def missing(argv,cwd,logs,issues,events,stage,**options):
        i=issues.add('TOOL.MISSING','ERROR','DEPENDENCY',stage,'External simulator unavailable.')
        return {'status':'UNAVAILABLE','issue_id':i.issue_id}
    monkeypatch.setattr(rc,'run_external',missing)
    issues=IssueCollector()
    result=check_rtl(d,rtl,tmp_path,issues,EventLog(tmp_path/'events.jsonl'))
    assert result['status']=='UNAVAILABLE'
    assert issues.errors[0].code=='TOOL.MISSING'
    assert (tmp_path/'rtl_check_tb.v').is_file()


def test_rtl_checker_detects_divergent_and_matching_simulator_results(tmp_path,monkeypatch):
    from chipcompiler.rtl_check import check_rtl
    from chipcompiler.generator import HardwareCompiler
    from chipcompiler.diagnostics import EventLog
    import chipcompiler.rtl_check as rc
    d=HardwareCompiler().compile_source('def top(x:u4)->u4:\n return x ^ 3\n',top='top')
    rtl=tmp_path/'top.v';rtl.write_text(verilog(d))
    state={'corrupt':True}
    def fake(argv,cwd,logs,issues,events,stage,**options):
        if stage=='rtl_compile':(tmp_path/'rtl_check.vvp').write_text('synthetic test stub')
        else:
            vec=rc.make_vectors(d,8)
            records=[]
            for i,v in enumerate(vec):
                answer=v['x']^3
                if state['corrupt'] and i==3:answer^=1
                records.append(f'[STDOUT] CCRTL_V1|{i}|{answer:x}')
            records.append(f'[STDOUT] CCRTL_V1_END|{len(vec)}')
            (tmp_path/'rtl_execute.log').write_text('\n'.join(records))
        return {'status':'PASS','log':str(tmp_path/(stage+'.log'))}
    monkeypatch.setattr(rc,'run_external',fake)
    issues=IssueCollector()
    result=check_rtl(d,rtl,tmp_path,issues,EventLog(tmp_path/'events.jsonl'),vector_count=8)
    assert result['status']=='FAIL'
    assert result['failures'][0]['index']==3
    assert issues.errors[0].code=='RTL.BEHAVIOR_MISMATCH'
    state['corrupt']=False
    issues=IssueCollector()
    result=check_rtl(d,rtl,tmp_path,issues,EventLog(tmp_path/'events.jsonl'),vector_count=8)
    assert result['status']=='PASS'
    assert not issues.errors


def test_rtl_check_opt_in_failure_blocks_dependent_builds(tmp_path,monkeypatch):
    from chipcompiler.cli import init_project
    import chipcompiler.rtl_check as rc
    root=tmp_path/'demo';init_project(root)
    (root/'chip.yaml').write_text((root/'chip.yaml').read_text()+
                                  'verification:\n  external_rtl: true\n  rtl_vectors: 4\n')
    def fake(argv,cwd,logs,issues,events,stage,**options):
        i=issues.add('TOOL.MISSING','ERROR','DEPENDENCY',stage,'Icarus is absent.')
        return {'status':'UNAVAILABLE','issue_id':i.issue_id}
    monkeypatch.setattr(rc,'run_external',fake)
    r=BuildSession(root,mode='build').run()
    assert r.status=='FAILED'
    assert r.stages['rtl_check']['status']=='UNAVAILABLE'
    assert r.stages['yosys']['status']=='BLOCKED'
    assert any(i['code']=='TOOL.MISSING' for i in r.issues)


def test_failed_network_reports_causal_stages_not_spurious_generator_errors(tmp_path):
    from chipcompiler.cli import init_project
    import yaml
    root=tmp_path/'fault';init_project(root)
    (root/'circuit.py').write_text(SOURCE)
    broken=copy.deepcopy(NETWORK)
    broken['network']['instances'][0]['inputs']['sum_value']='typo.result'
    (root/'design.mcd').write_text(yaml.safe_dump({'top':'top',**broken}))
    r=BuildSession(root).run()
    assert r.status=='FAILED'
    assert r.stages['network']['status']=='FAIL'
    assert r.stages['generate']['status']=='BLOCKED'
    assert r.stages['equivalence']['status']=='BLOCKED'
    assert any(i['code']=='MCD.NETWORK.UNKNOWN_INSTANCE' for i in r.issues)
    assert not any(i['code']=='INTERNAL.UNEXPECTED' for i in r.issues)


def test_missing_physical_metrics_stay_unverified(tmp_path):
    from chipcompiler.physical import inspect_librelane
    evidence=inspect_librelane(tmp_path/'no_real_run')
    assert evidence.status=='FAIL'
    assert evidence.checks['lvs']['status']=='UNVERIFIED'
    assert evidence.checks['timing']['status']=='UNVERIFIED'
    assert evidence.checks['drc_klayout']['status']=='UNVERIFIED'


def test_unique_width_procedural_inference_works_and_warns():
    m=copy.deepcopy(NETWORK)
    m['network']['auto_connect']='unique_width'
    m['network']['instances'][0].pop('inputs')
    issues=IssueCollector()
    built=compile_network(SOURCE,'x.py','top',m,issues=issues)
    links={r['destination']:r for r in built.connections}
    assert links['select.sum_value']['source']=='s.result'
    assert links['select.product']['source']=='m.result'
    assert links['select.flag']['source']=='flag'
    assert any(i.code=='MCD.NETWORK.WIDTH_INFERRED' for i in issues.warnings)
    assert verify(SOURCE,built.design,IssueCollector()).status=='PASS_EXHAUSTIVE'


def test_width_inference_reports_ambiguous_producers():
    m=copy.deepcopy(NETWORK)
    m['network']['auto_connect']='unique_width'
    m['network']['instances'].append({'name':'extra','function':'add'})
    m['network']['instances'][0].pop('inputs')
    issues=IssueCollector()
    with pytest.raises(DiagnosticException):compile_network(SOURCE,'x.py','top',m,issues=issues)
    matched=[i for i in issues.errors if i.code=='MCD.NETWORK.AMBIGUOUS_AUTO']
    assert matched
    assert set(matched[0].evidence['candidates'])=={'s.result','extra.result'}


def test_clocked_submodule_sets_librelane_clock_contract(tmp_path,monkeypatch):
    import shutil,json,yaml
    from chipcompiler import pipeline
    old=Path(__file__).parent.parent/'examples'/'clocked_hierarchy'
    root=tmp_path/'clocked'
    shutil.copytree(old,root,ignore=shutil.ignore_patterns('build','.chipcompiler','__pycache__'))
    conf=yaml.safe_load((root/'chip.yaml').read_text())
    conf['physical']={'enabled':True,'pdk':'sky130A','clock_period_ns':20}
    (root/'chip.yaml').write_text(yaml.safe_dump(conf))
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**opts):
        if stage=='yosys':
            (cwd/'synthesized.v').write_text('module accumulate_view(input clk, output result); endmodule\n')
        return {'status':'PASS','returncode':0,'log':'fake-run-not-real'}
    monkeypatch.setattr(pipeline,'run_external',fake)
    result=BuildSession(root,mode='physical').run()
    assert result.status=='FAILED' # no real GDS exists; fake process status must not count
    config=json.loads((root/'build/latest/config.json').read_text())
    assert config['CLOCK_PORT']=='clk'
    assert config['CLOCK_PERIOD']==20
    assert not any(i['code']=='PHYSICAL.COMBINATIONAL' for i in result.issues)
    assert any(i['code']=='PHYSICAL.ARTIFACT_INVALID' for i in result.issues)
