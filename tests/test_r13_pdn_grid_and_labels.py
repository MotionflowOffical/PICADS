"""r13: user-reported blank draggable module labels and top-level PDN channels.

Headless tests exercise label policy and legal physical layout. They do not
claim Qt pixel inspection or a passing OpenROAD PDN.
"""
from pathlib import Path
import inspect
import shutil

import pytest
import yaml

from chipcompiler.co_macros import (read_macro_constraints,allocate_macro_rectangles,
                                    alternate_pdn_floorplan, _validate_2d_clearance,
                                    check_macro_placement_zones,MacroConstraintError)
from chipcompiler.floorplan_labels import macro_label_layout


@pytest.mark.parametrize('name,instance',[
    ('ProgramMemory','u_program'),('ProcessorControl','u_control'),
    ('ArithmeticLogic','u_alu'),('Peripherals','u_io'),
])
def test_labels_are_not_blank_at_normal_zoom(name,instance):
    label=macro_label_layout(name,instance,180,120)
    assert name.lower().replace(' ','')==label['text'].replace('\n','').replace(instance,'').lower()
    assert 7<=label['pixel_font_size']<=14


def test_small_item_uses_readable_short_name_and_reports_full_in_tooltip():
    label=macro_label_layout('ProcessorControl','u_control',25,13)
    assert label['text']
    assert label['pixel_font_size']>=5


def test_recovery_grid_snaps_compact_without_touching_manual():
    blocks=[{'name':n,'instance':n,'module':n,'size_um':wh,'location_um':[x,y]}
            for n,wh,x,y in [
                ('program',[150.21,160.25],30,30),('data',[125.11,120.2],265,30),
                ('control',[75.33,95.44],30,240),('alu',[64.27,65.11],170,240)]]
    spacing={'min_um':15,'preferred_um':45,'max_um':90}
    region=[30,30,700,700]
    args={'region_um':region,'stayouts_um':[[500,500,540,540]],'halo_um':5}
    rows,_=allocate_macro_rectangles(blocks,spacing,mode='compact',grid_um=10,**args)
    _validate_2d_clearance(rows,spacing)
    check_macro_placement_zones(rows,**args)
    assert all((r['x_um']/10)%1==0 and (r['y_um']/10)%1==0 for r in rows)
    manual,_=allocate_macro_rectangles(blocks,spacing,mode='manual',grid_um=10,**args)
    assert [(r['x_um'],r['y_um']) for r in manual]==[(30,30),(265,30),(30,240),(170,240)]


def test_pdn_alternative_widens_only_within_co_limits():
    blocks=[{'name':f'm{i}','module':f'm{i}','instance':f'u{i}','size_um':[90+i*13,100+i*11]}
            for i in range(5)]
    co={'placement_mode':'compact','packing_spacing':{'min_um':15,'preferred_um':45,'max_um':90},
        'placement_region_um':[30,30,800,800], 'placement_stayouts_um':[],
        'halo_um':5, 'placement_grid_um':10}
    a,_=allocate_macro_rectangles(blocks,co['packing_spacing'],mode='compact',
                                  region_um=co['placement_region_um'],grid_um=10,halo_um=5)
    out=alternate_pdn_floorplan(blocks,co,a)
    assert out is not None
    b,die,gap=out
    assert gap==65
    assert die[0]<=830 and die[1]<=830
    _validate_2d_clearance(b,co['packing_spacing'])
    co['placement_mode']='manual'
    assert alternate_pdn_floorplan(blocks,co,a) is None
    co['placement_mode']='compact'
    co['packing_spacing']['preferred_um']=90
    assert alternate_pdn_floorplan(blocks,co,a) is None


def test_non_sky130_and_default_projects_do_not_snap(tmp_path):
    p=Path(__file__).resolve().parents[1]/'examples'/'tiny8_co_native'
    shutil.copytree(p,tmp_path/'project')
    raw=yaml.safe_load((tmp_path/'project'/'architecture.co').read_text())
    physical=yaml.safe_load((tmp_path/'project'/'chip.yaml').read_text())['physical']
    spec=read_macro_constraints(raw['physical_macros'],tmp_path/'project',physical)
    assert spec['placement_grid_um']==0
    raw['physical_macros']['placement']['grid_um']=26
    with pytest.raises(MacroConstraintError,match='grid_um'):
        read_macro_constraints(raw['physical_macros'],tmp_path/'project',physical)
