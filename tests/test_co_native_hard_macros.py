"""Native CO macro integration tests. No fake physical success assertions."""
import json
from pathlib import Path
import shutil
import pytest
from chipcompiler.co_macros import (
    read_macro_constraints,MacroConstraintError,allocate_macro_rectangles,
    verify_routed_macro_def,read_lef_size)
from chipcompiler.pipeline import BuildSession

EXAMPLE=Path(__file__).resolve().parents[2]/'Tiny8_CO_Native_Project'
# The release example is copied under examples for tests.
EXAMPLE_IN_REPO=Path(__file__).resolve().parents[1]/'examples'/'tiny8_co_native'


def test_co_native_macro_project_stays_normal_picads_project(tmp_path):
    folder=tmp_path/'cpu'
    shutil.copytree(EXAMPLE_IN_REPO,folder)
    result=BuildSession(folder,'compile').run()
    assert result.stages['export']['status']=='PASS',result.as_dict()
    assert not any(i['code']=='CO.UNSUPPORTED_DIRECTIVE' for i in result.issues)
    c=read_macro_constraints(__import__('yaml').safe_load((folder/'architecture.co').read_text())['physical_macros'],folder,
                             __import__('yaml').safe_load((folder/'chip.yaml').read_text())['physical'])
    assert [b['instance'] for b in c['blocks']]==['u_memory','u_control','u_alu']


def test_hard_macro_validation_rejects_unknown_block_and_traversal(tmp_path):
    shutil.copytree(EXAMPLE_IN_REPO,tmp_path/'cpu')
    folder=tmp_path/'cpu'
    import yaml
    raw=yaml.safe_load((folder/'architecture.co').read_text())['physical_macros']
    physical=yaml.safe_load((folder/'chip.yaml').read_text())['physical']
    raw['blocks'][0]['instance']='u_missing'
    with pytest.raises(MacroConstraintError,match='BINDING'):
        read_macro_constraints(raw,folder,physical)
    raw['blocks'][0]['instance']='u_memory'
    raw['blocks'][0]['rtl']='../outside.v'
    with pytest.raises(MacroConstraintError,match='PATH'):
        read_macro_constraints(raw,folder,physical)
    raw['blocks'][0]['rtl']='rtl/tiny8_memory.v'
    raw['spacing']['min_um']=80
    with pytest.raises(MacroConstraintError,match='SPACING'):
        read_macro_constraints(raw,folder,physical)


def test_lef_and_placement_evidence(tmp_path):
    lef=tmp_path/'block.lef'
    lef.write_text('MACRO myblock\n SIZE 42.5 BY 24 ;\nEND myblock\n')
    assert read_lef_size(lef,'myblock')==[42.5,24]
    blocks=[{'name':'RAM','module':'ram','instance':'u_ram','size_um':[42.5,24]},
            {'name':'ALU','module':'alu','instance':'u_alu','size_um':[23,18]}]
    spacing={'min_um':5,'preferred_um':10,'max_um':20}
    rows,die=allocate_macro_rectangles(blocks,spacing)
    for r in rows:r.update(min_spacing_um=5,max_spacing_um=20)
    def write_def(x):
        (tmp_path/'final.def').write_text(
            'UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 2 ;\n'
            f'- u_ram ram + FIXED ( 30000 30000 ) N ;\n'
            f'- u_alu alu + FIXED ( {x} 30000 ) N ;\nEND COMPONENTS\n')
    write_def(82500)
    evidence=verify_routed_macro_def(tmp_path/'final.def',rows)
    assert evidence['status']=='MACRO_DEF_PLACEMENTS_VERIFIED'
    write_def(130000)
    with pytest.raises(MacroConstraintError,match='moved'):
        verify_routed_macro_def(tmp_path/'final.def',rows)


def test_native_co_automatically_dispatches_from_gui_layout_mode(tmp_path,monkeypatch):
    from chipcompiler import pipeline,co_macros
    from types import SimpleNamespace
    folder=tmp_path/'cpu'
    shutil.copytree(EXAMPLE_IN_REPO,folder)
    calls=[]
    def fake_preflight(*args,**kwargs):
        return SimpleNamespace(status='READY_TO_ATTEMPT',checks={'settings':{'status':'PASS'}},
                               librelane_config={'FP_CORE_UTIL':25,'CLOCK_PERIOD':100},
                               as_dict=lambda:{'status':'READY_TO_ATTEMPT','checks':{'settings':{'status':'PASS'}}})
    def fake_external(argv,cwd,logs,issues,events,stage,timeout=600,**opts):
        calls.append((stage,list(argv)))
        return {'status':'FAIL','returncode':11}
    monkeypatch.setattr(pipeline,'physical_preflight',fake_preflight)
    monkeypatch.setattr(co_macros,'run_external',fake_external)
    result=BuildSession(folder,'layout').run()
    assert result.stages['export']['status']=='PASS'
    assert result.stages['physical']['status']=='FAIL'
    assert calls[0][0]=='macro_tiny8_memory',calls
    assert calls[0][1][-3:] == ['--to','Magic.WriteLEF','config.json'],calls
    assert not (folder/'build/latest/layout_artifacts.json').exists()
    assert (folder/'build/co_macro_cache/tiny8_memory/config.json').exists()
    assert not list(folder.rglob('*.bat'))


def _fake_gds(path,top,children):
    import struct
    def r(rec,dt=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',4+len(payload),rec,dt)+payload
    def string(s):return s.encode('ascii')
    out=bytearray()
    out+=r(0,2,struct.pack('>H',600))
    out+=r(1,2,bytes(24))
    out+=r(2,6,string('PICADS'))
    out+=r(3,5,bytes(16))
    for name in children+[top]:
        out+=r(5,2,bytes(24))+r(6,6,string(name))
        # One geometric polygon, so the GDS has nonzero physical elements.
        out+=r(8)+r(13,2,struct.pack('>H',68))+r(14,2,struct.pack('>H',20))
        out+=r(16,3,struct.pack('>10i',0,0,100,0,100,100,0,100,0,0))+r(17)
        if name==top:
            for child in children:
                out+=r(10)+r(18,6,string(child))+r(16,3,struct.pack('>ii',0,0))+r(17)
        out+=r(7)
    out+=r(4)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(out)


def test_native_macro_full_layout_mock_requires_actual_def_gds(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from chipcompiler import pipeline,co_macros
    folder=tmp_path/'cpu';shutil.copytree(EXAMPLE_IN_REPO,folder)
    monkeypatch.setattr(pipeline,'physical_preflight',lambda *a,**k:SimpleNamespace(
        status='READY_TO_ATTEMPT',checks={'settings':{'status':'PASS'}},
        librelane_config={'CLOCK_PORT':'clk','CLOCK_PERIOD':100},
        as_dict=lambda:{'status':'READY_TO_ATTEMPT','checks':{'settings':{'status':'PASS'}}}))
    calls=[]
    commands=[]
    def fake_run(argv,cwd,logs,issues,events,stage,timeout=600,**opts):
        calls.append(stage)
        commands.append((stage, list(argv)))
        if stage.startswith('abc_'):
            (cwd/'abc_optimized.aig').write_bytes(b'aig 0 0 0 0 0\n')
            return {'status':'PASS','returncode':0}
        tag=argv[argv.index('--run-tag')+1]
        run=cwd/'runs'/tag
        if stage.startswith('macro_'):
            name=stage[6:]
            _fake_gds(run/'final/gds'/f'{name}.gds',name,[])
            (run/'final/lef').mkdir(parents=True,exist_ok=True)
            (run/'final/lef'/f'{name}.lef').write_text(f'MACRO {name}\n SIZE 60 BY 80 ;\nEND {name}\n')
            (run/'final/nl').mkdir(parents=True,exist_ok=True)
            (run/'final/nl'/f'{name}.nl.v').write_text(f'module {name}(); endmodule')
        elif stage=='physical':
            plan=json.loads((cwd/'co_macros/co_macro_plan.json').read_text())
            _fake_gds(run/'final/gds/tiny8_modular_top.gds', 'tiny8_modular_top',
                      [b['module'] for b in plan['blocks']])
            d=run/'final/def/tiny8_modular_top.def';d.parent.mkdir(parents=True,exist_ok=True)
            rows=['UNITS DISTANCE MICRONS 1000 ;',f'COMPONENTS {len(plan["blocks"])} ;']
            for b in plan['blocks']:
                rows.append(f'- {b["instance"]} {b["module"]} + FIXED ( {round(b["x_um"]*1000)} {round(b["y_um"]*1000)} ) N ;')
            rows+=['END COMPONENTS','END DESIGN']
            d.write_text('\n'.join(rows))
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(co_macros,'run_external',fake_run)
    result=BuildSession(folder,'layout').run()
    assert result.stages['physical']['status']=='PASS',result.as_dict()
    assert result.stages['physical']['macro_placement']=='MACRO_GDS_AND_DEF_PLACEMENT_VERIFIED'
    assert set(calls)>={'macro_tiny8_memory','macro_tiny8_control','macro_tiny8_alu','physical'}
    for stage,argv in commands:
        if stage.startswith('macro_'):
            assert argv[-3:] == ['--to','Magic.WriteLEF','config.json']
        elif stage == 'physical':
            assert argv[-3:] == ['--to','KLayout.StreamOut','config.json']
    manifest=json.loads((folder/'build/latest/layout_artifacts.json').read_text())
    assert [x['module'] for x in manifest['macro_children']]==['tiny8_memory','tiny8_control','tiny8_alu']
    assert all(x['views']['gds']['sha256'] for x in manifest['macro_children'])
    assert manifest['top']=='tiny8_modular_top'
    assert manifest['source_equivalence']=='NOT_ESTABLISHED'
    assert (folder/'build/latest/co_macros/co_macro_placement_verified.json').exists()


def test_co_native_macros_can_be_disabled_without_broken_project(tmp_path):
    import yaml
    folder=tmp_path/'cpu';shutil.copytree(EXAMPLE_IN_REPO,folder)
    co=yaml.safe_load((folder/'architecture.co').read_text())
    co['physical_macros']={'enabled':False}
    (folder/'architecture.co').write_text(yaml.safe_dump(co))
    result=BuildSession(folder,'compile').run()
    assert result.stages['export']['status']=='PASS',result.as_dict()


def test_macro_verification_reuses_saved_views_and_checks_xor(tmp_path,monkeypatch):
    """The second GUI action must verify, not synthesize/reroute, child macros."""
    from types import SimpleNamespace
    from chipcompiler import co_macros
    from chipcompiler.physical_flow import artifact_hash
    from chipcompiler.diagnostics import IssueCollector
    root=tmp_path/'cpu';root.mkdir()
    folder=root/'build/co_macro_cache/tiny8_memory'
    (folder/'runs/hard_0123456789abcd').mkdir(parents=True)
    (folder/'final').mkdir()
    saved=[]
    for rel,content in [('design.v','module tiny8_memory; endmodule'),
                        ('config.json','{}'),('runs/hard_0123456789abcd/final/gds/tiny8_memory.gds','gds'),
                        ('runs/hard_0123456789abcd/final/lef/tiny8_memory.lef','lef'),
                        ('runs/hard_0123456789abcd/final/nl/tiny8_memory.v','nl')]:
        p=folder/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        saved.append((rel,artifact_hash(p)))
    receipt={'module':'tiny8_memory','run_tag':'hard_0123456789abcd',
             'source_sha256':saved[0][1], 'config_sha256':saved[1][1],
             'views':{kind:{'relative_path':path,'sha256':checksum}
                      for kind,(path,checksum) in zip(('gds','lef','nl'),saved[2:])}}
    calls=[]
    def fake_external(argv,cwd,logs,issues,events,stage,timeout,**opts):
        calls.append((argv,stage));return {'status':'PASS','returncode':0}
    monkeypatch.setattr(co_macros,'run_external',fake_external)
    class Session:
        def __init__(self):
            self.root=root;self.issues=IssueCollector();self.events=None;self.status=[]
        def _done(self,stage,status,**kwargs):self.status.append((stage,status,kwargs))
    session=Session()
    assert co_macros.verify_cached_macro_children(session,
        {'macro_children':[receipt]}, {'pdk':'sky130A'}, {'runner':'wsl','wsl_distribution':'Ubuntu'})
    assert '--from' in calls[0][0]
    assert calls[0][0][calls[0][0].index('--from')+1]=='Odb.CheckDesignAntennaProperties'
    assert '--to' not in calls[0][0]
    assert session.status[-1][1]=='PASS'
    # An altered LEF must prevent external-tool execution and fail closed.
    (folder/saved[3][0]).write_text('changed LEF')
    session=Session();calls.clear()
    assert not co_macros.verify_cached_macro_children(session,
        {'macro_children':[receipt]}, {'pdk':'sky130A'}, {'runner':'wsl','wsl_distribution':'Ubuntu'})
    assert not calls
    assert session.status[-1][1]=='FAIL'


def test_macro_xor_failure_remains_blocking_at_verification(tmp_path, monkeypatch):
    from chipcompiler import co_macros
    from chipcompiler.diagnostics import IssueCollector
    from chipcompiler.physical_flow import artifact_hash
    root = tmp_path/'cpu'
    folder = root/'build/co_macro_cache/tiny8_memory'
    tag = 'hard_0123456789abcd'
    paths = {'src':folder/'design.v', 'config':folder/'config.json',
             'gds':folder/'runs'/tag/'final/gds/m.gds',
             'lef':folder/'runs'/tag/'final/lef/m.lef',
             'nl':folder/'runs'/tag/'final/nl/m.v'}
    for path in paths.values():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'example')
    receipt = {'module':'tiny8_memory','run_tag':tag,
               'source_sha256':artifact_hash(paths['src']),
               'config_sha256':artifact_hash(paths['config']),
               'views':{key:{'relative_path':str(paths[key].relative_to(folder)),
                             'sha256':artifact_hash(paths[key])} for key in ('gds','lef','nl')}}
    class Session:
        def __init__(self):
            self.root = root;self.issues=IssueCollector();self.events=None;self.stages={}
        def _done(self,stage,status,**details):self.stages[stage]={'status':status,**details}
    session=Session()
    monkeypatch.setattr(co_macros,'run_external',lambda *a,**k:
                        {'status':'FAIL','returncode':2,'stderr_tail':'1 XOR differences found'})
    assert not co_macros.verify_cached_macro_children(session,
        {'macro_children':[receipt]}, {'pdk':'sky130A'}, {'runner':'wsl'})
    assert session.stages['macro_signoff']['status']=='FAIL'
    assert any(i.code=='VERIFY.MACRO_SIGNOFF_FAILED' for i in session.issues.issues)
