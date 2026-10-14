"""Regression coverage: real 2D CO macro locations and non-duplicated GDS layers."""
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
import shutil
import pytest
from chipcompiler.co_macros import (allocate_macro_rectangles,read_macro_constraints,
                                   verify_routed_macro_def,MacroConstraintError,_rect_gap)
from chipcompiler.klayout_layers import exact_gds_palette,gds_layer_pairs,valid_lyp

EXAMPLE=Path(__file__).resolve().parents[1]/'examples/tiny8_co_native'
SPACING={'min_um':20,'preferred_um':30,'max_um':75}


def blocks():
    return [
        {'name':'RAM','module':'ram','instance':'u_memory','size_um':[183.11,193.83]},
        {'name':'CTRL','module':'ctrl','instance':'u_control','size_um':[113.68,111.27]},
        {'name':'ALU','module':'alu','instance':'u_alu','size_um':[83.24,80.54]},
    ]


def test_compact_packing_uses_two_dimensions_and_reduces_envelope():
    row,rowdie=allocate_macro_rectangles(blocks(),SPACING,mode='row')
    compact,compactdie=allocate_macro_rectangles(blocks(),SPACING,mode='compact')
    assert row[0]['y_um']==row[1]['y_um']==row[2]['y_um']
    assert len({b['y_um'] for b in compact})>1
    assert compactdie[0]*compactdie[1] < rowdie[0]*rowdie[1]
    assert {b['instance'] for b in compact}=={b['instance'] for b in row}
    assert min(_rect_gap(a,b) for i,a in enumerate(compact) for b in compact[i+1:])>=SPACING['min_um']
    second,_=allocate_macro_rectangles(blocks(),SPACING,mode='compact')
    assert compact==second


def test_def_accepts_real_non_row_coordinates_and_rejects_movement(tmp_path):
    plan,_=allocate_macro_rectangles(blocks(),SPACING,mode='compact')
    for b in plan:b.update(min_spacing_um=20,max_spacing_um=75)
    d=tmp_path/'actual.def'
    def put(moved=False):
        lines=['UNITS DISTANCE MICRONS 1000 ;','COMPONENTS 3 ;']
        for b in plan:
            x=b['x_um']+(80 if moved and b['instance']=='u_alu' else 0)
            lines.append(f'- {b["instance"]} {b["module"]} + FIXED ( {round(1000*x)} {round(1000*b["y_um"])} ) N ;')
        d.write_text('\n'.join(lines+['END COMPONENTS','END DESIGN']))
    put()
    assert verify_routed_macro_def(d,plan)['status']=='MACRO_DEF_PLACEMENTS_VERIFIED'
    put(True)
    with pytest.raises(MacroConstraintError,match='moved'):
        verify_routed_macro_def(d,plan)


def test_co_manual_is_explicit_and_fails_closed(tmp_path):
    folder=tmp_path/'cpu';shutil.copytree(EXAMPLE,folder)
    import yaml
    raw=yaml.safe_load((folder/'architecture.co').read_text())
    co=raw['physical_macros']
    physical=yaml.safe_load((folder/'chip.yaml').read_text())['physical']
    assert read_macro_constraints(co,folder,physical)['placement_mode']=='compact'
    co['placement']={'mode':'manual'}
    with pytest.raises(MacroConstraintError,match='LOCATION'):
        read_macro_constraints(co,folder,physical)
    positions=[[30,30],[260,30],[260,175]]
    for b,xy in zip(co['blocks'],positions):b['location_um']=xy
    assert read_macro_constraints(co,folder,physical)['placement_mode']=='manual'
    b=blocks()
    for item,xy in zip(b,positions):item['location_um']=xy
    # Constraint enforcement at the geometry level, not just parser.
    placed,_=allocate_macro_rectangles(b,SPACING,mode='manual')
    assert len(placed)==3
    b[2]['location_um']=[30,35]
    with pytest.raises(MacroConstraintError,match='SPACING'):
        allocate_macro_rectangles(b,SPACING,mode='manual')


def _gds(path):
    def rec(kind,datatype=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',4+len(payload),kind,datatype)+payload
    out=bytearray(rec(0,2,b'\0\6'))
    for layer,ptype,record in [(68,20,14),(68,5,22),(83,44,22)]:
        out+=rec(8 if record==14 else 12)
        out+=rec(13,2,struct.pack('>H',layer))
        out+=rec(record,2,struct.pack('>H',ptype))
        out+=rec(17)
    path.write_bytes(out)


def test_generated_palette_controls_real_layers_only(tmp_path):
    gds=tmp_path/'core.gds';_gds(gds)
    assert gds_layer_pairs(gds)=={(68,20),(68,5),(83,44)}
    # Simulate an installed PDK palette with named but incorrect datatype IDs.
    old=tmp_path/'old.lyp'
    old.write_text('<layer-properties><properties><name>metal 1</name><source>68/0@1</source>'
                   '<frame-color>#ffaa00</frame-color><fill-color>#ffbb00</fill-color>'
                   '</properties></layer-properties>')
    generated,evidence=exact_gds_palette(tmp_path,gds,palette=old)
    assert valid_lyp(generated)
    assert evidence['observed_pairs']==3
    assert evidence['mapped_pairs']==3
    entries=ET.parse(generated).getroot().findall('properties')
    sources=[n.findtext('source') for n in entries]
    assert set(sources)=={'68/20@1','68/5@1','83/44@1'}
    assert '68/0@1' not in sources
    assert len(sources)==len(set(sources))
    assert next(n for n in entries if n.findtext('source')=='68/20@1').findtext('name')=='met1.drawing'
    assert next(n for n in entries if n.findtext('source')=='68/5@1').findtext('visible')=='false'
    assert (tmp_path/'build/latest/klayout_layer_mapping.json').is_file()


def test_unknown_gds_layers_remain_visible_and_controllable(tmp_path):
    gds=tmp_path/'unmapped.gds'
    def rec(k,dt=0,p=b''):return struct.pack('>HBB',4+len(p),k,dt)+p
    gds.write_bytes(rec(8)+rec(13,2,struct.pack('>H',240))+rec(14,2,struct.pack('>H',78))+rec(17))
    path,report=exact_gds_palette(tmp_path,gds,pdk='sky130A')
    assert report['mapped_pairs']==0
    assert ET.parse(path).getroot().find('properties').findtext('name')=='GDS 240/78 (unmapped)'
