"""r14 regressions: hard CO validation on Save, manual die and automatic die envelope.

The GUI drag release is inspected statically where PySide6 is unavailable;
physical GDS signoff still requires a real LibreLane run.
"""
from pathlib import Path
import shutil
import yaml
import pytest
from chipcompiler.co_macros import (MacroConstraintError,read_macro_constraints,
    effective_macro_die,autosized_macro_die,allocate_macro_rectangles)
from chipcompiler.co_macro_editor import (update_co_macro_locations,save_macro_locations)

SOURCE=Path(__file__).resolve().parents[1]/'examples'/'tiny8_co_native'


def project(tmp_path):
    dest=tmp_path/'tiny'
    shutil.copytree(SOURCE,dest)
    spec=yaml.safe_load((dest/'architecture.co').read_text())
    physical=yaml.safe_load((dest/'chip.yaml').read_text())['physical']
    co=read_macro_constraints(spec['physical_macros'],dest,physical)
    sized=[{**b,'size_um':[b['width'],b['height']]} for b in co['blocks']]
    rows,_=allocate_macro_rectangles(sized,co['packing_spacing'],mode='compact')
    locs={r['instance']:[r['x_um'],r['y_um']] for r in rows}
    return dest,co,rows,locs


def test_default_auto_die_is_minimal_envelope(tmp_path):
    _,co,rows,_=project(tmp_path)
    assert co['die_size_um']=='auto'
    auto=autosized_macro_die(rows)
    effective=effective_macro_die(rows,mode='compact',die_size_um=[9999,9999],halo_um=5)
    assert effective['die_area_um']==auto['die_area_um']


def test_manual_explicit_dimensions_roundtrip(tmp_path):
    root,_,rows,locs=project(tmp_path)
    target=[850,760]
    result=save_macro_locations(root,locs,die_size_um=target)
    doc=yaml.safe_load((root/'architecture.co').read_text())
    assert doc['physical_macros']['placement']['mode']=='manual'
    assert doc['physical_macros']['placement']['die_size_um']==target
    assert result['die']['width_um']==target[0]
    assert result['die']['height_um']==target[1]
    assert all('location_um' in b for b in doc['physical_macros']['blocks'])
    # Confirm second save can restore automatic size without shifting blocks.
    again=save_macro_locations(root,locs,die_size_um='auto')
    assert again['die']['sizing_basis']=='placed_macro_bounds_plus_margin'
    assert yaml.safe_load((root/'architecture.co').read_text())['physical_macros']['placement']['die_size_um']=='auto'


def test_reject_chip_too_small_without_overwriting_file(tmp_path):
    root,_,rows,locs=project(tmp_path)
    before=(root/'architecture.co').read_bytes()
    with pytest.raises(MacroConstraintError,match='CO.MACROS_DIE'):
        save_macro_locations(root,locs,die_size_um=[65,65])
    assert (root/'architecture.co').read_bytes()==before


def test_chip_edge_halo_is_enforced():
    rows=[{'instance':'x','x_um':30,'y_um':30,'width_um':100,'height_um':110}]
    # Edge must leave 10 um for CORE_AREA and an additional 5 for halo.
    with pytest.raises(MacroConstraintError,match='CO.MACROS_DIE'):
        effective_macro_die(rows,mode='manual',die_size_um=[142,150],halo_um=5)
    assert effective_macro_die(rows,mode='manual',die_size_um=[145,155],halo_um=5)['width_um']==145


def test_read_explicit_size_and_reject_malformed(tmp_path):
    root,_,rows,locs=project(tmp_path)
    doc=yaml.safe_load((root/'architecture.co').read_text())
    doc['physical_macros']['placement']['die_size_um']=[700,800]
    physical=yaml.safe_load((root/'chip.yaml').read_text())['physical']
    co=read_macro_constraints(doc['physical_macros'],root,physical)
    assert co['die_size_um']==[700,800]
    for bad in ([100],[-1,900],True,'fixed'):
        doc['physical_macros']['placement']['die_size_um']=bad
        with pytest.raises(MacroConstraintError):
            read_macro_constraints(doc['physical_macros'],root,physical)


def test_editor_does_not_block_mouse_drag_before_save():
    gui=(Path(__file__).resolve().parents[1]/'src/chipcompiler/gui.py').read_text()
    item=gui[gui.index('class DraggableMacro'):gui.index('class MacroFloorplanEditor')]
    assert 'self.editor.clamp_drag' not in item
    editor=gui[gui.index('class MacroFloorplanEditor'):gui.index('class BuildWorker')]
    assert 'die_size_um=self.die_size_preference' in editor
    assert 'self._geometry_error()' in editor
    assert 'self.view.fit_target=None' in editor


def test_co_writer_does_not_touch_unrelated_project_sections(tmp_path):
    root,_,_,locs=project(tmp_path)
    old=(root/'architecture.co').read_text()
    new=update_co_macro_locations(old,locs,die_size_um=[750,750])
    assert old.split('physical_macros:',1)[0]==new.split('physical_macros:',1)[0]
    assert '    die_size_um: [750, 750]' in new
    assert update_co_macro_locations(new,locs,die_size_um=[750,750])==new


def test_manual_to_automatic_switch_clears_locations_and_die_override(tmp_path):
    from chipcompiler.co_macro_editor import save_automatic_macro_placement
    root,_,rows,locs=project(tmp_path)
    save_macro_locations(root,locs,die_size_um=[850,760])
    result=save_automatic_macro_placement(root)
    doc=yaml.safe_load((root/'architecture.co').read_text())
    p=doc['physical_macros']
    assert p['placement']['mode']=='compact'
    assert p['placement']['die_size_um']=='auto'
    assert all('location_um' not in b for b in p['blocks'])
    assert result['die']['sizing_basis']=='placed_macro_bounds_plus_margin'
    assert result['status']=='AUTO_PLACEMENT_SAVED_REQUIRES_LAYOUT_REBUILD'
    assert (root/'.chipcompiler'/'floorplan_backups').is_dir()


def test_automatic_layout_uses_actual_die_area_rank_not_inner_box():
    from inspect import getsource
    from chipcompiler.co_macros import allocate_macro_rectangles
    source=getsource(allocate_macro_rectangles)
    assert 'area=dw*dh' in source
    assert 'rank=(round(area,4)' in source
