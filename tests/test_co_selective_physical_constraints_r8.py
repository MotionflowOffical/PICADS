"""CO policies: explicit guarantees versus non-binding guidance."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
import yaml
from chipcompiler.floorplanning import plan_floorplan, librelane_keepout_config, FloorplanError
from chipcompiler.cli import init_project
from chipcompiler.pipeline import BuildSession
from chipcompiler import pipeline


def context():
    dls=SimpleNamespace(name='calculate',instances=[],nodes=[],registers=[],submodules={},metadata={})
    architecture=SimpleNamespace(reachable=['calculate'])
    physical={'enabled':True,'die_area_um':[0,0,100,100]}
    return dls,architecture,physical


def basic():
    return {'region_um':[0,0,100,100], 'border_um':2,
            'modules':[{'name':'Processor','source_function':'calculate'}]}


def test_guide_and_required_keepouts_are_selective():
    d,a,p=context();co=basic()
    co['keepouts']=[{'name':'ClockChannel','bounds_um':[45,0,55,100],
                    'kind':'hard','enforcement':'required'},
                   {'name':'UserReminder','bounds_um':[0,0,10,10],
                    'kind':'hard','enforcement':'guide'}]
    plan=plan_floorplan(co,d,a,physical=p)
    assert plan['modules'][0]['enforcement']=='guide'
    assert plan['keepouts'][0]['status']=='CONFIG_READY_NOT_YET_PLACED'
    assert librelane_keepout_config(plan)=={'FP_OBSTRUCTIONS':[[45.,0.,55.,100.]]}


def test_required_module_does_not_fall_back_to_svg():
    d,a,p=context();co=basic()
    co['modules'][0]['enforcement']='required'
    with pytest.raises(FloorplanError,match='ENFORCEMENT_UNSUPPORTED'):
        plan_floorplan(co,d,a,physical=p)


def test_module_validate_requires_actual_instance():
    d,a,p=context();co=basic()
    co['modules'][0]['enforcement']='validate'
    with pytest.raises(FloorplanError,match='VALIDATION_UNBOUND'):
        plan_floorplan(co,d,a,physical=p)


def test_global_required_can_be_overridden_for_guide_but_not_enforced():
    d,a,p=context();co=basic();co['enforcement']='required'
    co['modules'][0]['enforcement']='guide'
    plan=plan_floorplan(co,d,a,physical=p)
    assert plan['modules'][0]['enforcement']=='guide'
    del co['modules'][0]['enforcement']
    with pytest.raises(FloorplanError,match='ENFORCEMENT_UNSUPPORTED'):
        plan_floorplan(co,d,a,physical=p)


@pytest.mark.parametrize('change,error',[('no_die','KEEPOUT_DIE'),('disabled','PHYSICAL_DISABLED'),
                                         ('soft','SOFT_NOT_HARD'),('outside','KEEPOUT_BOUNDS')])
def test_hard_keepout_fails_closed(change,error):
    d,a,p=context();co=basic()
    keep={'name':'Guard','bounds_um':[10,20,30,60],'enforcement':'required','kind':'hard'}
    co['keepouts']=[keep]
    if change=='no_die':del p['die_area_um']
    if change=='disabled':p['enabled']=False
    if change=='soft':keep['kind']='soft'
    if change=='outside':keep['bounds_um']=[90,20,110,60]
    with pytest.raises(FloorplanError,match=error):
        plan_floorplan(co,d,a,physical=p)


def test_hard_keepouts_overlap_rejected():
    d,a,p=context();co=basic()
    co['keepouts']=[{'name':name,'bounds_um':bounds,'enforcement':'required'} for name,bounds in
                    [('One',[10,10,20,20]),('Two',[15,15,25,25])]]
    with pytest.raises(FloorplanError,match='KEEPOUT_OVERLAP'):
        plan_floorplan(co,d,a,physical=p)


def test_pipeline_passes_only_hard_keepouts_to_librelane(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    config=yaml.safe_load((root/'chip.yaml').read_text())
    config['physical']={'enabled':True,'pdk':'sky130A','die_area_um':[0,0,100,100]}
    (root/'chip.yaml').write_text(yaml.safe_dump(config))
    co=yaml.safe_load((root/'architecture.co').read_text())
    co['floorplan']=basic()
    co['floorplan']['keepouts']=[
        {'name':'Hard','kind':'hard','enforcement':'required','bounds_um':[30,40,35,70]},
        {'name':'Guide','kind':'hard','enforcement':'guide','bounds_um':[45,40,50,70]}]
    (root/'architecture.co').write_text(yaml.safe_dump(co))
    calls=[]
    def fake(args,cwd,logs,issues,events,stage,timeout=600,**kw):
        calls.append(stage)
        if stage=='yosys':(cwd/'synthesized.v').write_text('module calculate(); endmodule')
        if stage=='physical':
            cfg=json.loads((cwd/'config.json').read_text())
            assert cfg['FP_OBSTRUCTIONS']==[[30.,40.,35.,70.]]
            assert 'PL_SOFT_OBSTRUCTIONS' not in cfg
            # Deliberately do not emulate a GDS: never fake physical success.
            return {'status':'FAIL','returncode':1}
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    result=BuildSession(root,'layout').run()
    assert calls==['yosys','physical'],result.as_dict()
    assert result.stages['co_physical_constraints']['status']=='SUBMITTED_NOT_VERIFIED'
    assert result.stages['physical']['status']!='PASS'
    assert json.loads((root/'build/latest/module_floorplan.json').read_text())['keepouts']


def test_core_area_must_be_inside_die():
    from chipcompiler.physical_flow import normalize_physical_settings
    valid={'enabled':True,'pdk':'sky130A','clock_period_ns':100,
           'die_area_um':[0,0,200,200],'core_area_um':[10,10,190,190]}
    _, config=normalize_physical_settings(valid,clocked=True)
    assert config['CORE_AREA']==[10.,10.,190.,190.]
    assert config['DIE_AREA']==[0.,0.,200.,200.]
    with pytest.raises(ValueError,match='CONFIG_CORE_AREA'):
        normalize_physical_settings({**valid,'core_area_um':[10,10,210,190]},clocked=True)


def test_packaged_selective_demo_compiles_without_external_pnr():
    # Compile in an isolated location; this is an example not an external-tool test.
    from shutil import copytree
    from tempfile import TemporaryDirectory
    example=Path(__file__).resolve().parents[1]/'examples/co_selective_enforcement'
    with TemporaryDirectory() as tmp:
        root=Path(tmp)/'example'
        copytree(example,root,ignore=__import__('shutil').ignore_patterns('build','__pycache__'))
        result=BuildSession(root,'compile').run()
        assert result.stages['floorplan']['hard_keepouts']==1,result.as_dict()
        assert result.stages['export']['status']=='PASS',result.as_dict()
