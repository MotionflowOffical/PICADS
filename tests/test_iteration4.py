"""v0.4 implementation regression and negative tests, not masked fixtures."""
import json
from pathlib import Path
import pytest
from chipcompiler.time_sharing import TimeShareCompiler, verify_time_share
from chipcompiler.diagnostics import IssueCollector, DiagnosticException
from chipcompiler.generator import HardwareCompiler
from chipcompiler.export import verilog
from chipcompiler.pipeline import BuildSession
from chipcompiler.cli import init_project
from chipcompiler.verification import verify
from chipcompiler.ir import DLS


@pytest.mark.parametrize('source,values', [
    ('''def calculate(a:u4,b:u4,d:bool)->u8:
 if d:
  return a*b
 return a+b
''', {'a':3,'b':6,'d':1}),
    ('''def calculate(a:u4,b:u4,d:bool)->u8:
 if d:
  return a*b
 else:
  return a+b
''', {'a':3,'b':6,'d':0}),
    ('''def calculate(a:u4,b:u4,d:bool)->u8:
 return a*b if d else a+b
''', {'a':3,'b':6,'d':1}),
    ('''def calculate(a:u4,b:u4,d:bool)->u8:
 if a>b:
  return a*b
 return a+b
''', {'a':3,'b':6,'d':1}),
    ('''def calculate(a:u4,b:u4,d:bool)->u8:
 return a*b if not d else a+b
''', {'a':3,'b':6,'d':1}),
])
def test_time_shared_predicated_outcomes(source,values):
    issues=IssueCollector()
    d=TimeShareCompiler(issues,{'allocation':{'max_instances':{'ADD':1,'MUL':1}}}).compile_source(source,top='calculate')
    result=verify_time_share(source,d,issues,random_vectors=45)
    assert result.status=='PASS_SAMPLED',result.failures
    assert d.metadata['predicates']
    assert 'r_step_' in verilog(d)


def test_time_share_predicate_computed_from_intermediate():
    src='''def compute(a:u4,b:u4,c:u4)->u9:
 x=a+b
 y=a*c
 z=(x+c) if x>b else y
 return z+1
'''
    d=TimeShareCompiler(co={'allocation':{'max_instances':{'ADD':1}}}).compile_source(src,top='compute')
    result=verify_time_share(src,d,IssueCollector(),random_vectors=80)
    assert result.status=='PASS_SAMPLED',result.failures
    binding={x['operation']:x['cycle'] for x in d.metadata['schedule']['bindings']}
    assert binding['op_0003']>binding['op_0002']


def test_time_share_rejects_impure_branch():
    source='''def f(a:u4,b:u4,d:bool)->u5:
 if d:
  a=a+b
 else:
  b=b+a
 return a
'''
    with pytest.raises(DiagnosticException,match='CO.TIME_SHARE_BRANCH'):
        TimeShareCompiler().compile_source(source,top='f')


NESTED='''def leaf(a:u4,b:u4)->u5:
 return a+b

def mid(a:u4,b:u4)->u6:
 return leaf(a,b)+1

def top(a:u4,b:u4)->u7:
 return mid(a,b)+mid(b,a)
'''

def test_preserved_nested_hierarchy_and_deduplicated_rtl(tmp_path):
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(NESTED,top='top')
    assert set(d.submodules)=={'mid'}
    assert set(d.submodules['mid'].submodules)=={'leaf'}
    assert len(d.instances)==2
    v=verilog(d)
    assert v.count('module leaf(')==1
    assert v.count('module mid(')==1
    assert v.count('module top(')==1
    result=verify(NESTED,d,IssueCollector())
    assert result.status=='PASS_EXHAUSTIVE',result.failures
    f=tmp_path/'test.dls';d.save(f)
    restored=DLS.load(f)
    assert restored.new_simulator().step({'a':3,'b':5})==d.new_simulator().step({'a':3,'b':5})


def test_recursive_hierarchy_has_named_root_cause():
    bad='''def one(a:u2)->u2:
 return two(a)
def two(a:u2)->u2:
 return one(a)
'''
    with pytest.raises(DiagnosticException,match='SOURCE.RECURSION'):
        HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(bad,top='one')


def _project(tmp_path):
    root=tmp_path/'chip';init_project(root)
    (root/'circuit.py').write_text(NESTED)
    (root/'design.mcd').write_text('top: top\nmodules:\n  - name: SmallAdder\n    function: leaf\n')
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\n')
    return root


def test_mcd_mandatory_function_count_and_evidence(tmp_path):
    root=_project(tmp_path)
    with (root/'design.mcd').open('a') as f:
        f.write('requires:\n  - {module: SmallAdder, min_instances: 2}\n  - mid\n')
    r=BuildSession(root).run()
    assert r.status=='SUCCESS',r.issues
    requirements=json.loads(Path(r.files['required_capabilities']).read_text())
    assert all(x['status']=='SATISFIED' for x in requirements)
    assert requirements[0]['expanded_calls']==2


def test_mcd_independent_requirement_errors_without_cascades(tmp_path):
    root=_project(tmp_path)
    with (root/'design.mcd').open('a') as f:
        f.write('requires:\n  - {function: leaf, min_instances: 3}\n  - missing_core\n')
    r=BuildSession(root).run()
    codes=[i['code'] for i in r.issues if i['severity']=='ERROR']
    assert codes==['MCD.REQUIRED_INSUFFICIENT','MCD.REQUIRED_UNKNOWN'],r.issues
    assert r.stages['equivalence']['status']=='BLOCKED'
    assert Path(r.files['required_capabilities']).is_file()


def test_mcd_rejects_malformed_required_capabilities(tmp_path):
    root=_project(tmp_path)
    with (root/'design.mcd').open('a') as f:
        f.write('requires:\n  - {function: leaf, min_instances: false}\n')
    r=BuildSession(root).run()
    assert any(x['code']=='MCD.REQUIRES_FORMAT' for x in r.issues)
    assert r.stages['generate']['status']=='BLOCKED'


def test_mcd_hardware_module_naming(tmp_path):
    root=_project(tmp_path)
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\n  naming: mcd\n')
    r=BuildSession(root).run()
    assert r.status=='SUCCESS',r.issues
    v=Path(r.files['verilog']).read_text()
    assert 'module SmallAdder(' in v
    assert 'SmallAdder u_000000(' in v
    d=DLS.load(Path(r.files['dls']))
    assert set(d.submodules['mid'].submodules)=={'SmallAdder'}
    assert 'leaf' not in d.submodules['mid'].submodules


def test_mcd_binding_conflict_error(tmp_path):
    root=_project(tmp_path)
    (root/'design.mcd').write_text('top: top\nmodules:\n  - name: mid\n    function: leaf\n')
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\n  naming: mcd\n')
    r=BuildSession(root).run()
    assert r.status=='FAILED',r.issues
    assert any(x['code']=='MCD.BINDING_INVALID' for x in r.issues)
    assert r.stages['export']['status']=='BLOCKED'


def test_time_share_bounded_loop_generation_and_equivalence():
    src='''def accumulate(a:u4,b:u4)->u8:
 total:u8=0
 for i in range(3):
  total:u8=total+a
 return total+b
'''
    d=TimeShareCompiler(co={'allocation':{'max_instances':{'ADD':1}}}).compile_source(src,top='accumulate')
    assert d.metadata['unrolled_iterations']==3
    assert d.metadata['schedule']['physical_units']['ADD']==1
    result=verify_time_share(src,d,IssueCollector(),random_vectors=100)
    assert result.status=='PASS_SAMPLED',result.failures


def test_scheduled_loop_rejects_unbounded_ranges():
    src='''def accumulate(a:u4,b:u4)->u8:
 total:u8=0
 for i in range(b):
  total=total+a
 return total
'''
    with pytest.raises(DiagnosticException,match='CO.TIME_SHARE_LOOP'):
        TimeShareCompiler().compile_source(src,top='accumulate')


def _example_gds(path,with_ref=True):
    import struct
    def rec(t,dt=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,t,dt)+payload
    def rectangle(points):
        flat=[x for p in points for x in p]
        return (rec(8)+rec(13,2,struct.pack('>h',7))+rec(16,3,struct.pack('>'+len(flat)*'i',*flat))+rec(17))
    rect=rectangle([(0,0),(100,0),(100,50),(0,50),(0,0)])
    seq=[rec(0,2,struct.pack('>H',600)),rec(1,2,b'\0'*24),rec(2,6,b'LIB\0')]
    if with_ref:
        seq += [rec(5,2,b'\0'*24),rec(6,6,b'CHILD\0'),rect,rec(7)]
    seq += [rec(5,2,b'\0'*24),rec(6,6,b'TOP\0')]
    if with_ref:
        seq += [rec(10),rec(18,6,b'CHILD\0'),rec(16,3,struct.pack('>ii',200,300)),rec(17)]
    else:seq.append(rect)
    seq += [rec(7),rec(4)]
    path.write_bytes(b''.join(seq))


def test_gds_actual_geometry_rendering_and_hierarchy(tmp_path):
    from chipcompiler.maskrender import render_gds_svg
    f=tmp_path/'design.gds';out=tmp_path/'layout.svg'
    _example_gds(f)
    result=render_gds_svg(f,out)
    assert result.top=='TOP' and result.visible_shapes==1
    assert result.layers=={7:1}
    assert result.status=='READ_ONLY_GEOMETRY'
    svg=out.read_text()
    assert '<polygon' in svg
    assert 'TOP' in svg
    assert 'GDS shapes' in svg
    assert result.warnings # No UNITS on this test stream: intentionally reports DBU


def test_gds_preview_reports_shape_limit_without_faking_completion(tmp_path):
    from chipcompiler.maskrender import render_gds_svg
    f=tmp_path/'design.gds';out=tmp_path/'layout.svg'
    _example_gds(f,with_ref=False)
    result=render_gds_svg(f,out,max_shapes=1)
    assert result.visible_shapes==1
    assert result.status=='READ_ONLY_GEOMETRY'
    with pytest.raises(ValueError,match='max_shapes'):
        render_gds_svg(f,out,max_shapes=0)


def test_render_mask_cli(tmp_path,capsys):
    from chipcompiler.cli import main
    f=tmp_path/'test.gds';_example_gds(f)
    assert main(['render-mask',str(f),'--output',str(tmp_path/'x.svg')])==0
    d=json.loads(capsys.readouterr().out)
    assert d['visible_shapes']==1 and Path(d['svg']).exists()


def test_global_module_resource_limit_has_nonmisleading_count(tmp_path):
    root=_project(tmp_path)
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\nallocation:\n  max_instances:\n    ADD: 2\n')
    result=BuildSession(root).run()
    assert result.status=='FAILED'
    issues=[x for x in result.issues if x['code']=='CO.GLOBAL_RESOURCE_LIMIT']
    assert len(issues)==1
    assert issues[0]['evidence']['required']==5 # two mid + two leaf + top addition
    assert result.stages['export']['status']=='BLOCKED'


def test_gds_reference_error_is_not_silently_ignored(tmp_path):
    from chipcompiler.maskrender import render_gds_svg
    from chipcompiler.maskinspect import GDSFormatError
    f=tmp_path/'test.gds';_example_gds(f)
    # Replace only referenced child name, not cell definition. Same string size.
    data=f.read_bytes()
    last=data.rfind(b'CHILD')
    f.write_bytes(data[:last]+b'GHOST'+data[last+5:])
    with pytest.raises(GDSFormatError) as exc:
        render_gds_svg(f,tmp_path/'preview.svg',top='TOP')
    assert exc.value.code=='GDS.UNKNOWN_REFERENCE'


def test_gds_preview_shape_limit_returns_partial_and_cli_exit_two(tmp_path,capsys):
    import struct
    from chipcompiler.maskrender import render_gds_svg
    from chipcompiler.cli import main
    f=tmp_path/'test.gds';_example_gds(f,with_ref=False)
    data=f.read_bytes();endstr=b'\x00\x04\x07\x00'
    index=data.index(endstr)
    def rec(t,dt=0,p=b''):
        if len(p)%2:p+=b'\0'
        return struct.pack('>HBB',len(p)+4,t,dt)+p
    extra=(rec(8)+rec(13,2,struct.pack('>h',8))+
           rec(16,3,struct.pack('>10i',0,0,10,0,10,10,0,10,0,0))+rec(17))
    f.write_bytes(data[:index]+extra+data[index:])
    dest=tmp_path/'output.svg'
    r=render_gds_svg(f,dest,max_shapes=1)
    assert r.status=='PARTIAL' and r.visible_shapes==1
    assert any('clipped' in w for w in r.warnings)
    code=main(['render-mask',str(f),'--output',str(dest),'--max-shapes','1'])
    assert code==2
    message=json.loads(capsys.readouterr().out)
    assert message['status']=='PARTIAL'
