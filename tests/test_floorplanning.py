"""Hard geometry and semantics checks for CO hierarchical floorplan planning."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from chipcompiler.floorplanning import plan_floorplan, render_floorplan_svg, FloorplanError
from chipcompiler.pipeline import BuildSession


def dummy(*, resource=True):
    sched={'physical_units':{'ADD':1} if resource else {}}
    dls=SimpleNamespace(name='top', instances=[], nodes=[], registers=[], submodules={},metadata={'schedule':sched})
    arch=SimpleNamespace(reachable=['top','a','b'])
    return dls,arch


def spec():
    return {'enabled':True,'region_um':[0,0,400,240],'min_spacing_um':12,
            'max_spacing_um':40,'preferred_spacing_um':16,'border_um':10,
            'modules':[{'name':'Processor','weight':3,'modules':[
                {'name':'A','source_function':'a','weight':1},
                {'name':'B','source_function':'b','weight':2}]},
                {'name':'OptionalMux','resource':'MUL'},
                {'name':'Arithmetic','resource':'ADD','weight':1}]}


def box_gap(a,b):
    return max(0,b[0]-a[2],a[0]-b[2],b[1]-a[3],a[1]-b[3])


def test_geometry_and_pruning(tmp_path):
    d,a=dummy()
    plan=plan_floorplan(spec(),d,a)
    assert plan['status']=='GUIDE_ONLY_NOT_ENFORCED'
    assert len(plan['pruned'])==1
    assert len(plan['modules'])==4
    regions={m['path']:m['bounds_um'] for m in plan['modules']}
    assert regions['Processor/A'][0]>=regions['Processor'][0]
    assert regions['Processor/B'][2]<=regions['Processor'][2]
    assert box_gap(regions['Processor/A'],regions['Processor/B']) == pytest.approx(16)
    assert box_gap(regions['Processor'],regions['Arithmetic']) == pytest.approx(16)
    assert any(m['binding']=='CO_RESOURCE_NOT_CELL_MAPPED' for m in plan['modules'])
    svg=render_floorplan_svg(plan,tmp_path/'image.svg')
    assert '<svg' in svg.read_text() and 'OptionalMux' not in svg.read_text()


def test_required_unused_is_error():
    d,a=dummy(resource=False)
    conf=spec();conf['modules']=[{'name':'ALU','resource':'ADD','required':True}]
    with pytest.raises(FloorplanError,match='REQUIRED'):
        plan_floorplan(conf,d,a)


def test_all_pruned_does_not_make_empty_success():
    d,a=dummy(resource=False)
    conf=spec();conf['modules']=[{'name':'Mux','resource':'MUL'}]
    with pytest.raises(FloorplanError,match='EMPTY'):
        plan_floorplan(conf,d,a)


@pytest.mark.parametrize('key,value',[
    ('max_spacing_um',3),('preferred_spacing_um',80),('region_um',[0,0,1,1]),
    ('region_um',[0,2,1,1]),('enforcement','required')])
def test_constraints_rejected(key,value):
    d,a=dummy();conf=spec();conf[key]=value
    with pytest.raises(FloorplanError):plan_floorplan(conf,d,a)


def test_unknown_key_rejected():
    d,a=dummy();conf=spec();conf['magic']='delete_the_design'
    with pytest.raises(FloorplanError,match='UNKNOWN'):plan_floorplan(conf,d,a)


def test_external_physical_die_bounds_checked():
    d,a=dummy()
    with pytest.raises(FloorplanError,match='OUTSIDE_DIE'):
        plan_floorplan(spec(),d,a,physical={'die_area_um':[0,0,300,300]})


def test_pipeline_real_project_integration(tmp_path):
    root=Path(__file__).parent.parent/'examples'/'nested_named_modules'
    # Uses an existing actual hierarchy example without modifying its source.
    import shutil,yaml
    target=tmp_path/'chip';shutil.copytree(root,target)
    co=yaml.safe_load((target/'architecture.co').read_text())
    co['floorplan']={'region_um':[0,0,500,300], 'min_spacing_um':5,
        'max_spacing_um':25,'preferred_spacing_um':10,'border_um':8}
    (target/'architecture.co').write_text(yaml.safe_dump(co))
    session=BuildSession(target,'compile');result=session.run()
    assert result.stages.get('floorplan',{}).get('status')=='GUIDE_ONLY', result.issues
    assert Path(result.files['module_floorplan_svg']).exists()
    saved=json.loads(Path(result.files['module_floorplan']).read_text())
    assert saved['modules']
    assert all(m['binding']=='DLS_INSTANCE_PRE_SYNTHESIS' for m in saved['modules'])
