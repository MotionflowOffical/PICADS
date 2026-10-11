"""Failure-oriented checks for the new language, architecture and physical adapters."""
import json, itertools, shutil
from pathlib import Path
import pytest
from chipcompiler.cfrontend import translate_c, CFrontendError
from chipcompiler.generator import HardwareCompiler
from chipcompiler.diagnostics import IssueCollector,DiagnosticException
from chipcompiler.verification import verify
from chipcompiler.cli import init_project
from chipcompiler.pipeline import BuildSession
from chipcompiler.physical import inspect_librelane
from chipcompiler.architecture import analyze
from chipcompiler.native_reference import verify_native

@pytest.mark.parametrize('suffix',['.c','.cpp','.cc','.cxx'])
def test_c_arithmetic_translation(suffix):
    src='#include <stdint.h>\nuint8_t f(uint8_t a,uint8_t b){return a+b;}'
    translated=translate_c(src,suffix)
    d=HardwareCompiler().compile_source(translated.source,top='f')
    assert d.new_simulator().step({'a':250,'b':20})['result']==14

@pytest.mark.parametrize('bad,code',[
    ('#define X 3\nuint8_t f(uint8_t a){return a;}', 'C.PREPROCESSOR'),
    ('uint8_t f(uint8_t *a){return 0;}', 'C.UNSUPPORTED_TYPE'),
    ('uint8_t f(uint8_t a){while(a){a=0;}return a;}', 'C.STATEMENT'),
    ('uint8_t f(uint8_t a){return a/2;}', 'C.BINARY_OP'),
    ('uint8_t f(uint8_t a){a+=1;return a;}', 'C.ASSIGN'),
    ('uint8_t f(uint8_t a){uint8_t b;return a;}', 'C.UNINITIALIZED'),
])
def test_c_explicit_rejection(bad,code):
    with pytest.raises(CFrontendError) as exc:translate_c(bad)
    assert exc.value.code==code

def test_c_fixed_counted_loop_and_helper():
    src='''uint8_t helper(uint8_t a) {return a+a;}
uint8_t calculate(uint8_t a) {uint8_t b=0;for(int i=0;i<3;i++){b=b+helper(a);}return b;}'''
    tr=translate_c(src)
    d=HardwareCompiler().compile_source(tr.source,top='calculate')
    for a in range(256):
        assert d.new_simulator().step({'a':a})['result']==(a*6)&255

@pytest.mark.parametrize('mode,expected_count', [('off',2),('force',1),('auto',2)])
def test_conditional_sharing_and_safe_equivalence(mode,expected_count):
    source='''def calculate(a:u2,b:u2,c:u2,d:u2,sel:bool)->u3:
    if sel: return a+b
    return c+d
'''
    co={'allocation':{'sharing':mode}}
    issues=IssueCollector();d=HardwareCompiler(issues,co).compile_source(source)
    assert d.metadata['operator_counts']['ADD']==expected_count
    report=verify(source,d,issues)
    assert report.status=='PASS_EXHAUSTIVE',report.failures

@pytest.mark.parametrize('operator,expr', [('MUL','*'),('AND','&'),('XOR','^')])
def test_forced_sharing_other_operators(operator,expr):
    source=f'''def calculate(a:u2,b:u2,c:u2,d:u2,sel:bool)->u4:
    if sel: return a{expr}b
    return c{expr}d
'''
    issues=IssueCollector()
    d=HardwareCompiler(issues,{'allocation':{'sharing':'force'}}).compile_source(source)
    assert d.metadata['operator_counts'][operator]==1
    assert verify(source,d,issues).status=='PASS_EXHAUSTIVE'

def test_invalid_shared_type_is_not_forced():
    source='''def calculate(a:u2,b:u3,c:u2,d:u2,sel:bool)->u4:
    return (a+b) if sel else (c+d)
'''
    d=HardwareCompiler(co={'allocation':{'sharing':'force'}}).compile_source(source)
    assert d.metadata['operator_counts']['ADD']==2

def test_max_instances_fails_with_one_root_cause():
    source='''def calculate(a:u2,b:u2,c:u2,d:u2,sel:bool)->u3:
    return (a+b) if sel else (c+d)
'''
    issues=IssueCollector()
    with pytest.raises(DiagnosticException) as exc:
        HardwareCompiler(issues,{'allocation':{'sharing':'off','max_instances':{'ADD':1}}}).compile_source(source)
    assert exc.value.issue.code=='CO.RESOURCE_LIMIT'
    assert exc.value.issue.origin=='CO'
    assert 'operations' in exc.value.issue.evidence

def test_allocation_and_modules(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'circuit.py').write_text('''def helper(a:u2,b:u2)->u3:
    return a+b

def calculate(a:u2,b:u2,d:bool)->u3:
    if d: return helper(a,b)
    return a+b
''')
    (root/'design.mcd').write_text('top: calculate\nmodules:\n  - name: alu\n    function: helper\n')
    r=BuildSession(root).run()
    assert r.status=='SUCCESS'
    graph=json.loads(Path(r.files['architecture']).read_text())
    assert graph['reachable']==['calculate','helper']
    assert graph['edges'][0]['callee']=='helper'
    assert (root/'build/latest/modules/helper.dls').is_file()
    assert r.stages['module_allocation']['physical_hierarchy']=='flattened'

def test_missing_explicit_module_binding_is_config_error(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'design.mcd').write_text('top: calculate\nmodules:\n  - name: nonexistent\n    function: missing\n')
    r=BuildSession(root).run()
    assert any(i['code']=='MCD.FUNCTION_NOT_FOUND' for i in r.issues)
    assert r.stages['generate']['status']=='BLOCKED'

def test_c_pipeline_normalized_and_diagnostics(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'chip.yaml').write_text('name: CTest\nmcd: design.mcd\nsource: circuit.c\nco: architecture.co\n')
    (root/'circuit.c').write_text('#include <stdint.h>\nuint8_t calculate(uint8_t a,uint8_t b,uint8_t d){return d?a*b:a+b;}')
    r=BuildSession(root).run()
    assert r.status=='SUCCESS_WITH_WARNINGS'
    assert r.stages['project']['source_kind']=='c-subset'
    assert Path(r.files['normalized_source']).is_file()
    assert any(i['code']=='C.SEMANTICS' for i in r.issues)
    assert r.stages['equivalence']['status']=='PASS_SAMPLED'

@pytest.mark.skipif(shutil.which('gcc') is None,reason='GCC not installed')
def test_native_reference_real_c_and_mismatch(tmp_path):
    src=tmp_path/'chip.c';src.write_text('#include <stdint.h>\nuint8_t calculate(uint8_t a,uint8_t b){return a+b;}')
    normalized=translate_c(src.read_text()).source
    d=HardwareCompiler().compile_source(normalized)
    result=verify_native(src,d,normalized,max_vectors=50)
    assert result.status=='PASS',result
    src.write_text('#include <stdint.h>\nuint8_t calculate(uint8_t a,uint8_t b){return a-b;}')
    invalid=verify_native(src,d,normalized,max_vectors=50)
    assert invalid.status=='FAIL'
    assert invalid.counterexample

def test_physical_evidence_missing_is_failure(tmp_path):
    ev=inspect_librelane(tmp_path/'nonexistent')
    assert ev.status=='FAIL'
    assert not ev.gds
    assert 'missing' in ev.notes[0].lower()

def test_physical_evidence_gds_and_known_checks(tmp_path):
    final=tmp_path/'run'/'final';(final/'gds').mkdir(parents=True)
    import struct
    def rec(t,d=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,t,d)+payload
    minimal=(rec(0,2,struct.pack('>H',600))+rec(1,2,b'\0'*24)+rec(2,6,b'TEST')+
             rec(5,2,b'\0'*24)+rec(6,6,b'TOP')+rec(8)+rec(13,2,struct.pack('>H',1))+
             rec(14,2,struct.pack('>H',0))+rec(17)+rec(7)+rec(4))
    (final/'gds'/'chip.gds').write_bytes(minimal)
    (final/'metrics.json').write_text(json.dumps({'klayout__drc_error__count':0,
        'magic__drc_error__count':0,'netgen__lvs_error__count':0,
        'klayout__antenna_error__count':0,'timing__setup__ws':0.015}))
    ev=inspect_librelane(tmp_path/'run')
    assert ev.status=='LAYOUT_GENERATED'
    assert all(v['status']=='PASS' for v in ev.checks.values())
    (final/'metrics.json').write_text(json.dumps({'klayout__drc_error__count':7}))
    ev=inspect_librelane(tmp_path/'run')
    assert ev.status=='FAIL'
    assert ev.checks['drc_klayout']['status']=='FAIL'
    assert ev.checks['lvs']['status']=='UNVERIFIED'

def test_physical_command_zero_exit_without_gds_not_accepted(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    cfg=(root/'chip.yaml');cfg.write_text(cfg.read_text().replace('enabled: false','enabled: true\n  pdk: sky130A'))
    from chipcompiler import pipeline
    def fake(argv,cwd,logs,issues,events,stage,timeout=600):
        if stage=='yosys':
            (cwd/'synthesized.v').write_text('module calculate(input wire a, output wire result); assign result = a; endmodule\n')
        return {'status':'PASS','returncode':0,'argv':argv}
    monkeypatch.setattr(pipeline,'run_external',fake)
    r=BuildSession(root,mode='physical').run()
    assert r.stages['physical']['status']=='FAIL'
    assert any(i['code']=='PHYSICAL.ARTIFACT_INVALID' for i in r.issues)
    assert r.stages['signoff']['status']=='BLOCKED'


def test_gds_stream_inventory_and_bad_lengths(tmp_path):
    import struct
    from chipcompiler.maskinspect import inspect_gds,GDSFormatError
    def rec(t,d=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,t,d)+payload
    path=tmp_path/'top.gds'
    path.write_bytes(rec(0,2,b'\2\x58')+rec(1,2,b'\0'*24)+rec(2,6,b'DEMO')+
                     rec(5,2,b'\0'*24)+rec(6,6,b'CELL')+rec(8)+rec(13,2,b'\0\7')+
                     rec(17)+rec(7)+rec(4))
    data=inspect_gds(path)
    assert data.structures==['CELL']
    assert data.layer_elements=={7:1}
    assert data.elements==1
    path.write_bytes(b'not a GDSII file')
    with pytest.raises(GDSFormatError):inspect_gds(path)


def test_vcd_export_real_signals_and_unknowns(tmp_path):
    from chipcompiler.waveform import export_vcd
    source='def calculate(a:u2,b:u2)->u3:\n return a+b\n'
    d=HardwareCompiler().compile_source(source)
    path=tmp_path/'wave.vcd'
    result=export_vcd(d,[{'a':1,'b':2},{'a':3,'b':3}],path,include_internal=True)
    assert result['internal_total']==len(d.nodes)
    assert result['timing_model']=='logical_cycle_only_not_physical'
    text=path.read_text()
    assert '$timescale 1ns $end' in text
    assert '#0' in text and '#5' in text and '#10' in text
    assert 'result' in text
    assert len(text)>100


def test_frontend_c_source_provenance_mapping(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'chip.yaml').write_text('name: CProvenance\nmcd: design.mcd\nsource: circuit.c\n')
    (root/'circuit.c').write_text('#include <stdint.h>\nuint8_t calculate(uint8_t a) {\n    return something;\n}\n')
    r=BuildSession(root).run()
    issue=next(i for i in r.issues if i['code']=='SOURCE.UNDEFINED_SYMBOL')
    assert issue['line']==3,issue
    assert 'normalized_line' in issue['evidence']


def test_co_invalid_limit_is_root_config_error(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'architecture.co').write_text('allocation:\n  sharing: true\n  max_instances:\n    ADD: 0\n')
    r=BuildSession(root).run()
    codes={i['code'] for i in r.issues}
    assert {'CO.SHARING','CO.INVALID_LIMIT'}.issubset(codes)
    assert r.stages['generate']['status']=='BLOCKED'


def test_clean_build_runs_do_not_mix_logs(tmp_path):
    root=tmp_path/'chip';init_project(root)
    a=BuildSession(root).run()
    b=BuildSession(root).run()
    assert a.run_id!=b.run_id
    assert Path(b.files['previous_build_archive']).is_dir()
    archived=json.loads((Path(b.files['previous_build_archive'])/'report.json').read_text())
    assert archived['run_id']==a.run_id
    current=[json.loads(x) for x in Path(b.files['events']).read_text().splitlines()]
    assert current and all(x['run_id']==b.run_id for x in current)
    assert all(x['run_id']!=a.run_id for x in current)


def test_trace_cli_from_external_vectors(tmp_path,capsys):
    from chipcompiler.cli import main
    root=tmp_path/'chip';init_project(root)
    inputs=tmp_path/'vectors.json'
    inputs.write_text(json.dumps([{'a':3,'b':4,'d':0},{'a':2,'b':6,'d':1}]))
    out=tmp_path/'out.vcd'
    code=main(['trace',str(root),'--vectors',str(inputs),'--output',str(out),'--include-internal'])
    captured=capsys.readouterr().out
    report=json.loads(captured)
    assert code==0
    assert report['trace']['vectors']==2
    assert report['trace']['internal_exported']>0
    assert out.is_file()


def test_c_void_parameter_is_supported():
    tr=translate_c('uint8_t calculate(void){return 3;}')
    d=HardwareCompiler().compile_source(tr.source)
    assert d.new_simulator().step({})['result']==3
