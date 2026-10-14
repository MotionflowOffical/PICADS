"""Regression for ASTER-8's observed PDN-0178/0179 failure, without fake signoff.

The saved r9d layout placed six hard macros at ~25 um pitch; OpenROAD
reported two metal1 channels only 14.72 um wide after halo/row cutting.
These tests verify code-level avoidance and truthful error diagnostics. The
actual physical flow must still be rerun under LibreLane/WSL on the target PC.
"""
from pathlib import Path
import shutil
import yaml
import pytest

from chipcompiler.co_macros import (
    MacroConstraintError, allocate_macro_rectangles, collect_pdn_errors,
    read_macro_constraints, _rect_gap,
)

TINY = Path(__file__).resolve().parents[1] / 'examples' / 'tiny8_co_native'


def test_rich_wrapped_openroad_pdn_channel_errors_are_recovered(tmp_path):
    log = tmp_path / 'physical.log'
    log.write_text(
        '[STDOUT] \x1b[33mWARNING\x1b[0m [PDN-0178] Remaining channel (178.9400,      openroad.py:314\n'
        '[STDOUT]                     891.9200) - (193.6600, 914.1600) on met1 for\n'
        '[STDOUT]                     nets: VGND\n'
        '[STDOUT] WARNING [PDN-0178] Remaining channel (331.6600, openroad.py:314\n'
        '[STDOUT]                     886.4800) - (346.3800, 914.1600) on met1 for\n'
        '[STDOUT]                     nets: VGND\n'
        '[STDOUT] ERROR [PDN-0179] Unable to repair all channels.\n'
    )
    result = collect_pdn_errors(log)
    assert result['status'] == 'PDN_CHANNEL_REPAIR_FAILED'
    assert {f['code'] for f in result['findings']} == {'PDN-0178','PDN-0179'}
    assert result['remaining_channels'] == [
        {'bounds_um':[178.94,891.92,193.66,914.16], 'layer':'met1', 'nets':'VGND'},
        {'bounds_um':[331.66,886.48,346.38,914.16], 'layer':'met1', 'nets':'VGND'},
    ]


def test_narrow_channel_spacing_causes_geometry_risk_in_old_floorplan():
    # Real observed macro x coordinates for ASTER-8 control/register row.
    control={'instance':'u_control','x_um':30,'y_um':832.245,'width_um':143.675,'height_um':154.395}
    regs={'instance':'u_registers','x_um':198.675,'y_um':832.245,'width_um':127.735,'height_um':130}
    assert _rect_gap(control,regs) == pytest.approx(25)
    # Recorded PDN channel was 14.72 um, not the full 25 um body clearance.
    assert 193.66-178.94 == pytest.approx(14.72)


def test_pdn_guard_keeps_six_macro_floorplan_in_region():
    # LEF-like dimensions reconstructed from placement evidence. Test checks
    # geometry / constraints only; no claim of routed PDN or signoff.
    sizes=[[448.87,443.205],[298.32,309.04],[143.675,154.395],
           [127.735,130],[93.6,104.32],[127.46,104.32]]
    bs=[{'instance':f'u_{i}','module':f'm{i}','name':f'M{i}', 'size_um':s}
        for i,s in enumerate(sizes)]
    spacing={'min_um':15,'preferred_um':60,'max_um':90}
    region=[30,30,1230,1100]
    stayouts=[[650,650,705,715]]
    rows,die=allocate_macro_rectangles(bs,spacing,mode='compact',region_um=region,
                                       stayouts_um=stayouts,halo_um=5)
    assert die[1] < 1120
    assert all(region[0]<=r['x_um'] and region[1]<=r['y_um']
               and r['x_um']+r['width_um']<=region[2]
               and r['y_um']+r['height_um']<=region[3] for r in rows)
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            assert _rect_gap(a,b)>=59.999
    assert allocate_macro_rectangles(bs,spacing,mode='compact',region_um=region,
                                     stayouts_um=stayouts,halo_um=5)[0]==rows


def _co(path):
    raw=yaml.safe_load((path/'architecture.co').read_text())['physical_macros']
    physical=yaml.safe_load((path/'chip.yaml').read_text())['physical']
    return raw,physical


def test_tiny8_unchanged_and_sky130_six_macro_auto_spacing(tmp_path):
    root=tmp_path/'tiny';shutil.copytree(TINY,root)
    raw,physical=_co(root)
    before=read_macro_constraints(raw,root,physical)
    assert before['spacing']['preferred_um']==30
    assert before['packing_spacing']['preferred_um']==30
    # Fourth explicit RTL block triggers conservative multi-macro packing.
    extra=dict(raw['blocks'][2]);extra.update(name='ArithmeticLogic2',module='tiny8_alu2',instance='u_alu2',rtl='rtl/tiny8_alu2.v')
    (root/'rtl/tiny8_alu2.v').write_text((root/'rtl/tiny8_alu.v').read_text().replace('module tiny8_alu','module tiny8_alu2'))
    top=(root/'rtl/tiny8_modular_top.v')
    top.write_text(top.read_text().replace('endmodule', '\n tiny8_alu2 u_alu2();\nendmodule'))
    raw['blocks'].append(extra)
    after=read_macro_constraints(raw,root,physical)
    assert after['spacing']['preferred_um']==30  # CO remains unchanged
    assert after['packing_spacing']['preferred_um']==60  # physical pack adjusted
    # The user can specify a smaller/larger guard within their CO maximum.
    raw['spacing']['pdn_min_um']=45
    assert read_macro_constraints(raw,root,physical)['packing_spacing']['preferred_um']==45
    raw['spacing']['pdn_min_um']=80
    with pytest.raises(MacroConstraintError,match='PDN_SPACING'):
        raw['spacing']['max_um']=75
        read_macro_constraints(raw,root,physical)


def test_manual_placement_never_automatically_relocates():
    bs=[{'instance':'u_a','module':'a','name':'A','size_um':[70,70],'location_um':[30,30]},
        {'instance':'u_b','module':'b','name':'B','size_um':[70,70],'location_um':[125,30]}]
    spacing={'min_um':15,'preferred_um':60,'max_um':90}
    rows,_=allocate_macro_rectangles(bs,spacing,mode='manual')
    assert [(r['x_um'],r['y_um']) for r in rows]==[(30,30),(125,30)]
