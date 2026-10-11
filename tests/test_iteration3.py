"""Revision 3 tests intentionally use different check paths and bad inputs."""
import json,random
from pathlib import Path
import pytest
from chipcompiler.cli import init_project
from chipcompiler.pipeline import BuildSession
from chipcompiler.generator import HardwareCompiler
from chipcompiler.pipelining import pipeline_dls,PipelineError
from chipcompiler.verification import verify
from chipcompiler.diagnostics import IssueCollector
from chipcompiler.ir import DLS
from chipcompiler.export import verilog

SOURCE='''def add(x:u4,y:u4)->u5:
    return x+y

def top(a:u4,b:u4,c:u4)->u6:
    left=add(a,b)
    right=add(b,c)
    return left+right
'''

@pytest.mark.parametrize('value',[(0,0,0),(2,3,4),(15,15,15),(0,15,8),(11,8,3)])
def test_real_hierarchy_and_verilog(value,tmp_path):
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(SOURCE,top='top')
    assert len(d.instances)==2
    assert set(d.submodules)=={'add'}
    assert d.instances[0]['at']==d.instances[1]['at']==0
    assert d.new_simulator().step(dict(zip(('a','b','c'),value)))['result']==sum(value[0:2])+sum(value[1:3])
    rtl=verilog(d)
    assert 'module add(' in rtl and 'module top(' in rtl
    assert 'add u_000000(' in rtl and 'add u_000001(' in rtl
    file=tmp_path/'hierarchy.dls';d.save(file)
    restored=DLS.load(file)
    assert restored.to_dict()==d.to_dict()
    assert restored.new_simulator().step(dict(zip(('a','b','c'),value))) == d.new_simulator().step(dict(zip(('a','b','c'),value)))


def test_independent_hierarchy_equivalence():
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(SOURCE,top='top')
    issues=IssueCollector();report=verify(SOURCE,d,issues)
    assert report.status=='PASS_EXHAUSTIVE' and report.vectors==4096
    # Deliberate corruption of the module is surfaced by source ↔ DLS checking.
    child=d.submodules['add']
    child.outputs['result']=['@0']*5
    assert d.validate()
    issues=IssueCollector();report=verify(SOURCE,d,issues)
    assert report.status=='FAIL'
    assert any(i.code=='VERIFY.MISMATCH' and i.evidence['first_counterexample'] for i in issues.errors)


def test_hierarchy_broken_instance_is_not_hidden():
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(SOURCE,top='top')
    d.instances[0]['inputs']['x']=['@0']
    with pytest.raises(ValueError,match='wrong-width'):d.validate()
    d.instances[0]['inputs']['x']=['a[0]']*4
    d.instances[0]['module']='missing'
    with pytest.raises(ValueError,match='unknown submodule'):d.validate()

@pytest.mark.parametrize('stages',[1,2,3,4,7,12])
def test_registered_pipeline_latency_and_exhaustive_values(stages):
    src='''def top(a:u4,b:u4,d:bool)->u8:
    if d: return a*b
    return a+b
'''
    base=HardwareCompiler().compile_source(src)
    d=pipeline_dls(base,stages)
    assert len(d.registers)>=stages
    assert d.metadata['pipeline']['latency_cycles']==stages
    assert d.metadata['pipeline']['initiation_interval_cycles']==1
    rep=verify(src,d,IssueCollector())
    assert rep.status=='PASS_EXHAUSTIVE',rep.failures
    rtl=verilog(d)
    assert 'posedge clk' in rtl
    assert 'input_valid' in rtl and 'output wire [0:0] valid;' in rtl

@pytest.mark.parametrize('count',[0,-1,33,1.5,True])
def test_pipeline_invalid_stage_counts_fail(count):
    base=HardwareCompiler().compile_source('def top(a:u2)->u2:\n return a\n')
    with pytest.raises(PipelineError,match='pipeline_stages'):pipeline_dls(base,count)


def test_sequential_user_register_rejected_with_exact_cause():
    d=HardwareCompiler().compile_source('def top(a:u2)->u2:\n return reg("r",a)\n')
    with pytest.raises(PipelineError,match='temporal contract'):pipeline_dls(d,2)


def test_project_pipeline_and_status(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'architecture.co').write_text('schedule:\n  pipeline_stages: 3\n')
    report=BuildSession(root).run()
    assert report.status=='SUCCESS',report.issues
    assert report.stages['scheduling']['latency_cycles']==3
    assert report.stages['equivalence']['status']=='PASS_EXHAUSTIVE'
    d=DLS.load(Path(report.files['dls']))
    assert d.outputs['valid'] and len(d.registers)>0
    assert 'clk' in Path(report.files['verilog']).read_text()


def test_project_preserves_real_module_hierarchy(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'circuit.py').write_text(SOURCE)
    (root/'design.mcd').write_text('top: top\nmodules:\n  - name: Arithmetic\n    function: add\n    inputs: {x: 4, y: 4}\n    outputs: {result: 5}\n')
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\n')
    report=BuildSession(root).run()
    assert report.status=='SUCCESS',report.issues
    assert report.stages['module_allocation']['physical_hierarchy']=='preserved'
    assert json.loads(Path(report.files['architecture']).read_text())['semantics']=='HIERARCHICAL_EXECUTABLE_DLS'
    assert 'add u_000001(' in Path(report.files['verilog']).read_text()


def test_bad_mcd_ports_report_exact_root_error(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'circuit.py').write_text(SOURCE)
    (root/'design.mcd').write_text('top: top\nmodules:\n  - name: Arithmetic\n    function: add\n    inputs: {x: 8, y: 4}\n')
    report=BuildSession(root).run()
    errors=[i for i in report.issues if i['severity']=='ERROR']
    assert len(errors)==1,errors
    assert errors[0]['code']=='MCD.PORT_MISMATCH'
    assert errors[0]['evidence']['declared']['x']==8
    assert report.stages['equivalence']['status']=='BLOCKED'
    assert report.stages['equivalence']['upstream_issue_ids']==[errors[0]['issue_id']]


def test_incompatible_co_is_not_ignored(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\nschedule:\n  pipeline_stages: 2\n')
    report=BuildSession(root).run()
    assert report.status=='FAILED'
    assert any(x['code']=='CO.SCHEDULE_HIERARCHY' for x in report.issues)
    assert report.stages['generate']['status']=='BLOCKED'


def test_no_hidden_clk_collision():
    bad='''def top(clk:u1)->u1:
    return reg("data",clk)
'''
    with pytest.raises(Exception,match='clk conflicts'):
        HardwareCompiler().compile_source(bad)

TIME_SHARED='''def compute(a:u4,b:u4,c:u4)->u6:
    first=a+b
    second=first+c
    return second
'''

@pytest.mark.parametrize('source,operator_count',[
    (TIME_SHARED,2),
    ('''def compute(a:u4,b:u4,c:u4,d:u4)->u8:
    x=a*b
    y=c*d
    return x+y
''',3),
    ('''def compute(a:u4,b:u4,c:u4)->u5:
    x=a-b
    y=b-c
    return x+y
''',3),
])
def test_actual_multicycle_time_sharing(source,operator_count,tmp_path):
    from chipcompiler.time_sharing import TimeShareCompiler,verify_time_share
    issues=IssueCollector()
    co={'schedule':{'mode':'time_share'},'allocation':{'max_instances':{'ADD':1,'SUB':1,'MUL':1}}}
    d=TimeShareCompiler(issues,co).compile_source(source,top='compute')
    assert d.metadata['schedule']['mode']=='time_share'
    assert len(d.metadata['schedule']['bindings'])==operator_count
    assert all(count==1 for count in d.metadata['schedule']['physical_units'].values())
    assert d.metadata['schedule']['execution_cycles']>=2
    r=verify_time_share(source,d,issues,random_vectors=150)
    assert r.status=='PASS_SAMPLED',r.failures
    rtl=verilog(d)
    assert 'posedge clk' in rtl and 'r_step_' in rtl
    assert 'r_commit' in rtl and 'r_in_a' in rtl
    file=tmp_path/'time_shared.dls';d.save(file)
    loaded=DLS.load(file)
    assert loaded.to_dict()==d.to_dict()
    assert loaded.metadata['schedule']['physical_units']==d.metadata['schedule']['physical_units']


def test_time_shared_detects_corrupted_dls():
    from chipcompiler.time_sharing import TimeShareCompiler,verify_time_share
    d=TimeShareCompiler().compile_source(TIME_SHARED,top='compute')
    d.registers['output']['next']=['@0']*6
    issues=IssueCollector();report=verify_time_share(TIME_SHARED,d,issues,random_vectors=12)
    assert report.status=='FAIL'
    assert issues.errors[0].code=='VERIFY.SCHEDULE_MISMATCH'
    assert issues.errors[0].evidence['first_counterexample']['reason']=='Incorrect scheduled result/handshake'


def test_time_shared_project_pipeline_and_cli(tmp_path,capsys):
    from chipcompiler.cli import main
    root=tmp_path/'chip';init_project(root)
    (root/'circuit.py').write_text(TIME_SHARED.replace('compute','calculate'))
    (root/'architecture.co').write_text('schedule:\n  mode: time_share\nallocation:\n  max_instances:\n    ADD: 1\n')
    report=BuildSession(root).run()
    assert report.status=='SUCCESS_WITH_WARNINGS'
    assert report.stages['scheduling']['mode']=='time_share'
    assert report.stages['equivalence']['status']=='PASS_SAMPLED'
    assert len(report.issues)==2 # descriptive MCD and sampled check are information/warning
    assert json.loads(Path(report.files['architecture']).read_text())['semantics']=='TIME_MULTIPLEXED_EXECUTABLE_DLS'
    code=main(['simulate',str(root),'--inputs','{"a":3,"b":4,"c":5}'])
    result=json.loads(capsys.readouterr().out)
    assert code==0
    assert result['simulated_output']=={'result':12,'ready':1,'done':1}
    assert result['simulated_clock_edges']==4


def test_pipeline_cli_single_vector(tmp_path,capsys):
    from chipcompiler.cli import main
    root=tmp_path/'chip';init_project(root)
    (root/'architecture.co').write_text('schedule:\n  pipeline_stages: 3\n')
    code=main(['simulate',str(root),'--inputs','{"a":3,"b":4,"d":1}'])
    result=json.loads(capsys.readouterr().out)
    assert code==0
    assert result['simulated_output']=={'result':12,'valid':1}
    assert result['simulated_clock_edges']==3


def test_time_share_rejects_unsupported_branch_and_handles_bad_config(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'architecture.co').write_text('schedule:\n  mode: time_share\n')
    report=BuildSession(root).run()
    assert report.status=='SUCCESS_WITH_WARNINGS',report.issues
    assert report.stages['equivalence']['status']=='PASS_SAMPLED'
    assert report.stages['scheduling']['mode']=='time_share'
    (root/'architecture.co').write_text('schedule:\n  mode: time_share\n  pipeline_stages: 3\n')
    report=BuildSession(root).run()
    assert report.status=='FAILED'
    assert any(i['code']=='CO.SCHEDULE_CONFLICT' for i in report.issues)
    assert report.stages['generate']['status']=='BLOCKED'


def test_time_share_parallel_unit_limit_changes_real_instances():
    from chipcompiler.time_sharing import TimeShareCompiler,verify_time_share
    src='''def compute(a:u3,b:u3,c:u3,d:u3)->u5:
    x=a+b
    y=c+d
    return x+y
'''
    one=TimeShareCompiler(co={'allocation':{'max_instances':{'ADD':1}}}).compile_source(src,top='compute')
    two=TimeShareCompiler(co={'allocation':{'max_instances':{'ADD':2}}}).compile_source(src,top='compute')
    assert one.metadata['schedule']['physical_units']['ADD']==1
    assert two.metadata['schedule']['physical_units']['ADD']==2
    assert one.metadata['schedule']['execution_cycles']==3
    assert two.metadata['schedule']['execution_cycles']==2
    for design in (one,two):
        assert verify_time_share(src,design,IssueCollector(),random_vectors=50).status=='PASS_SAMPLED'


def test_yosys_no_output_causes_explicit_error_not_success(tmp_path,monkeypatch):
    from chipcompiler import pipeline
    root=tmp_path/'chip';init_project(root)
    monkeypatch.setattr(pipeline,'run_external',lambda argv,cwd,logs,issues,events,stage,timeout=600:{'status':'PASS','returncode':0})
    result=BuildSession(root,mode='build').run()
    issue=next(x for x in result.issues if x['code']=='YOSYS.OUTPUT_MISSING')
    assert result.status=='FAILED'
    assert result.stages['yosys']['status']=='FAIL'
    assert result.stages['physical']['status']=='BLOCKED'
    assert result.stages['physical']['upstream_issue_ids']==[issue['issue_id']]
    assert 'synthesized_netlist' not in result.files


def test_yosys_wrong_top_rejected(tmp_path,monkeypatch):
    from chipcompiler import pipeline
    root=tmp_path/'chip';init_project(root)
    def fake(argv,cwd,logs,issues,events,stage,timeout=600):
        (cwd/'synthesized.v').write_text('module unexpected(); endmodule\n')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    result=BuildSession(root,mode='build').run()
    assert any(x['code']=='YOSYS.TOP_MISSING' for x in result.issues)
    assert result.stages['yosys']['status']=='FAIL'


def test_live_tool_logging_and_failing_stderr(tmp_path):
    import sys
    from chipcompiler.tools import run_external
    from chipcompiler.diagnostics import EventLog
    issues=IssueCollector();events=EventLog(tmp_path/'events.jsonl')
    result=run_external([sys.executable,'-c',
       'import sys; print("starting",flush=True); print("WARNING: minor issue",file=sys.stderr,flush=True); print("ERROR: deliberate failure",file=sys.stderr,flush=True);sys.exit(5)'],
       tmp_path,tmp_path,issues,events,'test_tool')
    assert result['status']=='FAIL'
    assert result['returncode']==5
    assert issues.errors[0].code=='TOOL.EXIT_NONZERO'
    log=Path(result['log']).read_text()
    assert '[STDOUT] starting' in log
    assert '[STDERR] ERROR: deliberate failure' in log
    records=[json.loads(line) for line in (tmp_path/'events.jsonl').read_text().splitlines()]
    assert any(e['action']=='tool_line' and e['severity']=='ERROR' for e in records)
    assert any(e['action']=='finish' for e in records)


def test_external_tool_timeout_has_original_cause_and_partial_log(tmp_path):
    import sys
    from chipcompiler.tools import run_external
    from chipcompiler.diagnostics import EventLog
    issues=IssueCollector();events=EventLog(tmp_path/'events.jsonl')
    result=run_external([sys.executable,'-c',
       'import time; print("BEFORE HANG",flush=True);time.sleep(4)'],
       tmp_path,tmp_path,issues,events,'test_timeout',timeout=1)
    assert result['status']=='TIMEOUT'
    assert issues.errors[0].code=='TOOL.TIMEOUT'
    assert 'BEFORE HANG' in Path(result['log']).read_text()
