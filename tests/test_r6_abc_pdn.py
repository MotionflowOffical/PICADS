import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from chipcompiler.aig import inspect_aiger_header
from chipcompiler.pdn import inspect_def_specialnets
from chipcompiler.physical_flow import normalize_physical_settings, physical_preflight
from chipcompiler.project import open_project
from chipcompiler.diagnostics import IssueCollector

BASE={'enabled':True,'pdk':'sky130A','clock_period_ns':20}

def test_pdk_power_grid_defaults():
    _,ll=normalize_physical_settings(BASE,True)
    assert ll['PDN_ENABLE_RAILS'] and ll['PDN_MULTILAYER']
    assert ll['PDN_ENABLE_GLOBAL_CONNECTIONS'] and ll['PDN_CONNECT_MACROS_TO_GRID']
    assert ll['PDN_CORE_RING'] is False
    out=physical_preflight(BASE,True,check_tools=False)
    assert out.checks['pdn_configuration']['status']=='PASS'
    assert out.status=='PARTIAL' # PDK location unverified

def test_custom_pdn_explicit_straps():
    _,ll=normalize_physical_settings({**BASE,'power_grid':{
      'core_ring':True,'vertical_pitch_um':30,'horizontal_pitch_um':40,
      'vertical_width_um':2,'horizontal_width_um':3}},True)
    assert (ll['PDN_VPITCH'],ll['PDN_HPITCH'],ll['PDN_VWIDTH'],ll['PDN_HWIDTH'])==(30,40,2,3)
    assert ll['PDN_CORE_RING']

@pytest.mark.parametrize('override',[{'rail':False},{'global_connections':False},
    {'vertical_pitch_um':3,'vertical_width_um':4},{'vertical_pitch_um':-1},
    {'bad_key':3},{'core_ring':'true'}])
def test_unsafe_pdn_rejected(override):
    with pytest.raises(ValueError):normalize_physical_settings({**BASE,'power_grid':override},True)

def test_aiger_header(tmp_path):
    p=tmp_path/'abc_optimized.aig';p.write_bytes(b'aig 9 4 2 1 3\n\x00\x01')
    info=inspect_aiger_header(p)
    assert info['format']=='aig' and info['and_nodes']==3 and info['latches']==2
    p.write_bytes(b'not aiger\n')
    with pytest.raises(ValueError):inspect_aiger_header(p)

def test_pdn_specialnets_inspection(tmp_path):
    p=tmp_path/'routed.def'
    p.write_text('VERSION 5.8 ;\nSPECIALNETS 2 ;\n- VPWR + ROUTED met1 (0 0) (10 10) ;\n- VGND + ROUTED met1 (0 1) (10 11) ;\nEND SPECIALNETS\nEND DESIGN\n')
    out=inspect_def_specialnets(p)
    assert out['status']=='PASS' and out['names']==['VPWR','VGND']
    p.write_text('VERSION 5.8 ;\nEND DESIGN\n')
    assert inspect_def_specialnets(p)['status']=='UNVERIFIED'

def test_project_accepts_co_abc_aig_and_floorplan(tmp_path):
    src=Path(__file__).parent.parent/'examples'/'nested_named_modules'
    import shutil,yaml
    dest=tmp_path/'demo';shutil.copytree(src,dest)
    co_path=dest/'architecture.co'
    co=yaml.safe_load(co_path.read_text())
    co['synthesis']={'abc_aig':True}
    co['floorplan']={'enabled':False}
    co_path.write_text(yaml.safe_dump(co))
    issues=IssueCollector();prj=open_project(dest,issues)
    assert prj is not None and not [x for x in issues.issues if x.severity=='ERROR']

def test_abc_aig_pipeline_opt_in_not_fake_for_physical(tmp_path,monkeypatch):
    import shutil,yaml
    from chipcompiler import pipeline
    from chipcompiler.pipeline import BuildSession
    src=Path(__file__).parent.parent/'examples'/'first_physical_chip'
    dest=tmp_path/'chip';shutil.copytree(src,dest)
    co_path=dest/'architecture.co'
    co=yaml.safe_load(co_path.read_text());co['synthesis']={'abc_aig':True}
    co_path.write_text(yaml.safe_dump(co))
    seen=[]
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kwargs):
        seen.append((stage,argv))
        if stage=='yosys': (cwd/'synthesized.v').write_text('module first_chip(); endmodule')
        if stage=='abc_aig': (cwd/'abc_optimized.aig').write_bytes(b'aig 6 2 2 1 2\n\x00\x00')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    result=BuildSession(dest,'build').run()
    assert result.stages['abc_aig']['status']=='PASS',result.as_dict()
    assert 'abc -g AND' in seen[1][1][2]
    assert result.files['abc_optimized_aig'].endswith('abc_optimized.aig')
    assert [s for s,_ in seen]==['yosys','abc_aig']


def test_invalid_abc_aig_halts_without_fabricating_success(tmp_path,monkeypatch):
    import shutil,yaml
    from chipcompiler import pipeline
    from chipcompiler.pipeline import BuildSession
    src=Path(__file__).parent.parent/'examples'/'first_physical_chip'
    dest=tmp_path/'chip';shutil.copytree(src,dest)
    co_path=dest/'architecture.co'
    co=yaml.safe_load(co_path.read_text());co['synthesis']={'abc_aig':True}
    co_path.write_text(yaml.safe_dump(co))
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kwargs):
        if stage=='yosys':(cwd/'synthesized.v').write_text('module first_chip(); endmodule')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    r=BuildSession(dest,'build').run()
    assert r.stages['abc_aig']['status']=='FAIL'
    assert any(i['code']=='ABC.AIG_INVALID' for i in r.issues)
