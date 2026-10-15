"""r12: sized physical die != placement constraints; GUI preserves physical aspect."""
from pathlib import Path
import json
import shutil
import pytest

from chipcompiler.co_macros import (
    autosized_macro_die, read_macro_constraints, allocate_macro_rectangles,
    MacroConstraintError,
)


def test_autodie_exact_geometry_excludes_extra_placement_region():
    rows=[{'instance':'u_mem','x_um':30.,'y_um':30.,'width_um':160.,'height_um':120.},
          {'instance':'u_alu','x_um':250.,'y_um':30.,'width_um':50.,'height_um':70.}]
    metrics=autosized_macro_die(rows)
    assert metrics['die_area_um']==[0,0,330,180]
    assert metrics['macro_coverage_percent']==round(100*(160*120+50*70)/(330*180),2)
    assert metrics['sizing_basis']=='placed_macro_bounds_plus_margin'
    assert metrics['reserved_for_routing_pdn_and_top_cells_percent']>0


def test_autodie_tracks_manual_movement_and_rejects_empty_input():
    rows=[{'x_um':30,'y_um':50,'width_um':100,'height_um':90}]
    assert autosized_macro_die(rows)['die_area_um']==[0,0,160,170]
    rows[0]['x_um']=90
    assert autosized_macro_die(rows)['die_area_um']==[0,0,220,170]
    with pytest.raises(MacroConstraintError,match='no placed macros'):
        autosized_macro_die([])


def test_real_tiny8_compact_die_smaller_than_hard_region(tmp_path):
    import yaml
    from chipcompiler.co_macros import check_macro_placement_zones, _validate_2d_clearance
    example=Path(__file__).resolve().parents[1]/'examples'/'tiny8_co_native'
    shutil.copytree(example,tmp_path/'project')
    root=tmp_path/'project'
    doc=yaml.safe_load((root/'architecture.co').read_text())
    phys=yaml.safe_load((root/'chip.yaml').read_text())['physical']
    spec=read_macro_constraints(doc['physical_macros'],root,phys,doc.get('floorplan'))
    sizes=[{**b,'size_um':[b['width'],b['height']]} for b in spec['blocks']]
    rows,die=allocate_macro_rectangles(sizes,spec['packing_spacing'],
        mode=spec['placement_mode'],region_um=spec['placement_region_um'],
        stayouts_um=spec['placement_stayouts_um'],halo_um=spec['halo_um'])
    assert len(rows)==len(sizes)
    assert die==[autosized_macro_die(rows)['width_um'],autosized_macro_die(rows)['height_um']]
    _validate_2d_clearance(rows,spec['spacing'])
    check_macro_placement_zones(rows,region_um=spec['placement_region_um'],
        stayouts_um=spec['placement_stayouts_um'],halo_um=spec['halo_um'])


def test_gui_floorplan_labels_and_preview_keep_aspect(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6.QtSvg')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPainter
    from chipcompiler.gui import AspectPreservingSvgWidget,AspectFitGraphicsView,DraggableMacro
    from PySide6.QtWidgets import QGraphicsScene
    app=QApplication.instance() or QApplication([])
    svg=tmp_path/'rect.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="500" height="250" viewBox="0 0 500 250"><rect width="500" height="250" fill="red"/></svg>')
    w=AspectPreservingSvgWidget();w.load(svg)
    assert w._renderer.aspectRatioMode()==Qt.AspectRatioMode.KeepAspectRatio
    w.resize(1300,200)
    scene=QGraphicsScene()
    view=AspectFitGraphicsView(scene)
    view.resize(1000,400)
    from PySide6.QtCore import QRectF
    view.fit_rect(QRectF(0,0,400,400))
    assert view.transform().m11()==pytest.approx(view.transform().m22())
    class Editor:pass
    b={'name':'ProcessorControl','instance':'u_control','size_um':[250,200]}
    block=DraggableMacro(Editor(),b,1)
    from chipcompiler.floorplan_labels import macro_label_layout
    import inspect
    # Rendering now happens in the block paint() itself; a child label with
    # ItemIgnoresTransformations was invisible in some manual placements.
    assert 'painter.drawText' in inspect.getsource(DraggableMacro.paint)
    assert 'Processor' in macro_label_layout('ProcessorControl','u_control',250,200)['text']
    w.close();view.close()


@pytest.mark.parametrize('available',[(1500,240),(240,1500),(800,800),(500,250)])
def test_svg_viewport_preserves_aspect_without_qt(available):
    from chipcompiler.preview_geometry import aspect_fit_rectangle
    left,top,width,height=aspect_fit_rectangle(500,250,*available)
    assert width/height==pytest.approx(2.0)
    assert left>=0 and top>=0
    assert left+width<=available[0]+1e-7
    assert top+height<=available[1]+1e-7


def test_svg_viewport_rejects_invalid_ratio():
    from chipcompiler.preview_geometry import aspect_fit_rectangle
    with pytest.raises(ValueError):aspect_fit_rectangle(100,0,900,700)
