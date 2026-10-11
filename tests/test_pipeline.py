import json,os,zipfile
from pathlib import Path
import pytest
from chipcompiler.cli import init_project
from chipcompiler.pipeline import BuildSession
from chipcompiler.project import snapshot,restore,atomic_write,open_project
from chipcompiler.diagnostics import IssueCollector
from chipcompiler.tools import probe
from chipcompiler.ir import DLS
from chipcompiler.library import try_reuse
from chipcompiler.generator import HardwareCompiler

@pytest.fixture
def project(tmp_path):
    p=tmp_path/'chip';init_project(p);return p

def test_compile_reports_correct_artifacts(project):
    r=BuildSession(project).run()
    assert r.status=='SUCCESS'
    assert r.stages['equivalence']['status']=='PASS_EXHAUSTIVE'
    for name in ('dls','verilog','events','report','equivalence'):assert Path(r.files[name]).is_file()
    report=json.loads(Path(r.files['report']).read_text())
    assert report['status']=='SUCCESS'
    assert DLS.load(Path(r.files['dls'])).new_simulator().step({'a':2,'b':3,'d':1})=={'result':6}

def test_independent_config_errors_no_cascade(project):
    (project/'design.mcd').write_text('top: [not, scalar]\nrequires: 99\n',encoding='utf-8')
    (project/'architecture.co').write_text('architecture:\n  adder: fake\n  mystery: foo\n',encoding='utf-8')
    r=BuildSession(project).run()
    codes={x['code'] for x in r.issues}
    assert {'MCD.BAD_TOP','MCD.REQUIRES','CO.BAD_VALUE','CO.UNKNOWN_KEY'}.issubset(codes)
    assert r.stages['generate']['status']=='BLOCKED'
    assert not [i for i in r.issues if i['severity']=='ERROR' and i['origin']=='GENERATOR']
    assert all(i['blocked_by'] for i in r.issues if i['severity']=='BLOCKED')

def test_missing_external_tool_report(project,monkeypatch):
    from chipcompiler import tools
    monkeypatch.setattr(tools.shutil,'which',lambda name:None)
    r=BuildSession(project,mode='build').run()
    assert r.stages['generate']['status']=='PASS'
    assert r.stages['yosys']['status']=='UNAVAILABLE'
    assert r.stages['physical']['status']=='BLOCKED'
    assert sum(x['code']=='TOOL.MISSING' for x in r.issues)==1
    issue=next(x for x in r.issues if x['code']=='TOOL.MISSING')
    dependent=next(x for x in r.issues if x['code']=='PIPELINE.BLOCKED' and x['stage']=='physical')
    assert issue['issue_id'] in dependent['blocked_by']

def test_backup_restoration_safety(project):
    a=snapshot(project,'test')
    orig=(project/'circuit.py').read_text()
    (project/'circuit.py').write_text('BROKEN',encoding='utf-8')
    with pytest.raises(ValueError,match='confirm'):restore(project,Path(a['file']),confirm=False)
    b=restore(project,Path(a['file']),confirm=True)
    assert (project/'circuit.py').read_text()==orig
    assert Path(b['pre_restore_snapshot']).is_file()

def test_reject_zip_slip(project,tmp_path):
    archive=tmp_path/'evil.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape','BAD')
    with pytest.raises(ValueError,match='escapes'):restore(project,archive,confirm=True)

def test_dls_library_candidate_verified(project):
    original=HardwareCompiler().compile_source('def calculate(a:u4,b:u4,d:bool)->u8:\n return (a*b) if d else (a+b)\n')
    lib=project/'library';lib.mkdir()
    candidate=HardwareCompiler().compile_source('def calculate(a:u4,b:u4,d:bool)->u8:\n return a+b\n')
    assert len(candidate.nodes)<len(original.nodes)
    candidate.save(lib/'wrong_behavior.dls')
    i=IssueCollector();chosen=try_reuse(original,lib,i)
    assert chosen is original

def test_run_ids_and_logs(project):
    r=BuildSession(project).run()
    lines=[json.loads(x) for x in Path(r.files['events']).read_text().splitlines()]
    assert lines and all(e['run_id']==r.run_id for e in lines)
    assert any(e['stage']=='generate' for e in lines)

def test_independent_syntax_and_co_failure(project):
    (project/'architecture.co').write_text('architecture:\n  adder: nonsense\n')
    (project/'circuit.py').write_text('def calculate(???\n')
    r=BuildSession(project).run()
    codes=[x['code'] for x in r.issues]
    assert 'SOURCE.SYNTAX' in codes and 'CO.BAD_VALUE' in codes
    assert r.stages['generate']['status']=='BLOCKED'

def test_diagnose_bundle_excludes_source_by_default(project):
    from chipcompiler.diagnose import package
    BuildSession(project).run()
    result=package(project)
    with zipfile.ZipFile(result['archive']) as z:
        assert 'report.json' in z.namelist()
        assert 'environment_manifest.json' in z.namelist()
        assert not any(x.startswith('source/') for x in z.namelist())

def test_snapshot_large_file_exclusion_is_visible(project):
    (project/'large.bin').write_bytes(b'a'*(16*1024*1024+1))
    result=snapshot(project,'size-policy')
    assert any(x['path']=='large.bin' and '16 MiB' in x['reason'] for x in result['excluded'])
    with zipfile.ZipFile(result['file']) as z:
        manifest=json.loads(z.read('_snapshot_manifest.json'))
    assert manifest['excluded']==result['excluded']
