"""CO stay-out constraints apply to editor movements and physical macro output."""
from pathlib import Path
import shutil
import pytest
import yaml
from chipcompiler.co_macros import (
    read_macro_constraints, allocate_macro_rectangles, check_macro_placement_zones,
    _validate_2d_clearance, MacroConstraintError)
from chipcompiler.co_macro_editor import coordinates_from_blocks, save_macro_locations

EXAMPLE=Path(__file__).parents[1]/'examples'/'tiny8_co_native'


def cpu(tmp_path):
    folder=tmp_path/'cpu';shutil.copytree(EXAMPLE,folder)
    contents=(folder/'architecture.co').read_text()
    contents=contents.replace('    mode: compact',
        '    mode: compact\n    region_um: [20, 20, 520, 480]\n    stayouts_um: [[245, 210, 285, 300]]')
    (folder/'architecture.co').write_text(contents)
    doc=yaml.safe_load(contents)
    spec=read_macro_constraints(doc['physical_macros'],folder,
        yaml.safe_load((folder/'chip.yaml').read_text())['physical'])
    return folder,spec


def boxes(spec):
    return [{**b,'size_um':[b['width'],b['height']]} for b in spec['blocks']]


def test_co_parser_placement_zone_and_stayouts(tmp_path):
    _,s=cpu(tmp_path)
    assert s['placement_region_um']==[20.,20.,520.,480.]
    assert s['placement_stayouts_um']==[[245.,210.,285.,300.]]
    rows,_=allocate_macro_rectangles(boxes(s),s['spacing'],mode='compact',
        region_um=s['placement_region_um'],stayouts_um=s['placement_stayouts_um'],halo_um=s['halo_um'])
    assert check_macro_placement_zones(rows,region_um=s['placement_region_um'],
        stayouts_um=s['placement_stayouts_um'],halo_um=s['halo_um'])
    _validate_2d_clearance(rows,s['spacing'])


def test_reject_crossing_region_and_stayout(tmp_path):
    _,s=cpu(tmp_path)
    b=boxes(s)[0]
    row=coordinates_from_blocks([b],{b['instance']:[245,210]},min_coord=0)
    with pytest.raises(MacroConstraintError,match='STAYOUT'):
        check_macro_placement_zones(row,region_um=s['placement_region_um'],
            stayouts_um=s['placement_stayouts_um'],halo_um=s['halo_um'])
    row=coordinates_from_blocks([b],{b['instance']:[460,360]},min_coord=0)
    with pytest.raises(MacroConstraintError,match='REGION'):
        check_macro_placement_zones(row,region_um=s['placement_region_um'],
            stayouts_um=s['placement_stayouts_um'],halo_um=s['halo_um'])


def test_saved_manual_placement_cannot_bypass_stayout(tmp_path):
    folder,s=cpu(tmp_path)
    rows,_=allocate_macro_rectangles(boxes(s),s['spacing'],mode='compact',
        region_um=s['placement_region_um'],stayouts_um=s['placement_stayouts_um'],halo_um=s['halo_um'])
    valid={r['instance']:[r['x_um'],r['y_um']] for r in rows}
    assert save_macro_locations(folder,valid)['status']=='SAVED_REQUIRES_LAYOUT_REBUILD'
    original=(folder/'architecture.co').read_text()
    valid['u_memory']=[245,215]
    with pytest.raises(MacroConstraintError):save_macro_locations(folder,valid)
    assert (folder/'architecture.co').read_text()==original


def test_invalid_zone_is_refused(tmp_path):
    folder,s=cpu(tmp_path)
    doc=yaml.safe_load((folder/'architecture.co').read_text())
    doc['physical_macros']['placement']['stayouts_um']=[[0,0,999,999]]
    with pytest.raises(MacroConstraintError,match='outside placement region'):
        read_macro_constraints(doc['physical_macros'],folder,
            yaml.safe_load((folder/'chip.yaml').read_text())['physical'])


def test_legacy_required_floorplan_keepout_protects_macro_editor(tmp_path):
    folder,s=cpu(tmp_path)
    doc=yaml.safe_load((folder/'architecture.co').read_text())
    # An r8 hard stay-out is still an enforced obstacle in the r9d GUI.
    doc['physical_macros']['placement']['stayouts_um']=[]
    doc['floorplan']={'keepouts':[{'name':'AnalogExclusion','kind':'hard',
        'enforcement':'required','bounds_um':[245,210,285,300]}]}
    spec=read_macro_constraints(doc['physical_macros'],folder,
        yaml.safe_load((folder/'chip.yaml').read_text())['physical'],doc['floorplan'])
    assert spec['placement_stayouts_um']==[[245.,210.,285.,300.]]
