"""No external tools: verify named layers and fail-closed unknown mapping."""
from pathlib import Path
import hashlib, struct
import xml.etree.ElementTree as ET
from chipcompiler.klayout_layers import gds_layer_pairs,named_sky130_palette,klayout_open_argv

def record(t,dt,data=b''):
    if len(data) & 1:data+=b'\x00'
    return struct.pack('>HBB',len(data)+4,t,dt)+data

def demo_gds(path):
    content=record(0,2,b'\x00\x06')+record(1,2,b'\x00'*24)+record(2,6,b'LIB')
    content+=record(3,5,struct.pack('>H',1000))+record(5,2,b'\x00'*24)+record(6,6,b'top')
    for layer,datatype in [(64,5),(65,20),(66,44),(68,20),(69,44),(250,200)]:
        content+=record(8,0)+record(13,2,struct.pack('>H',layer))+record(14,2,struct.pack('>H',datatype))+record(17,0)
    content+=record(7,0)+record(4,0)
    path.write_bytes(content)

def test_catalog_applies_to_actual_present_layers_without_mutating_gds(tmp_path):
    gds=tmp_path/'chip.gds';demo_gds(gds)
    palette=tmp_path/'base.lyp'
    palette.write_text('<layer-properties><properties><name>metal 1</name><source>68/20@1</source></properties></layer-properties>')
    original=hashlib.sha256(gds.read_bytes()).digest()
    output,info=named_sky130_palette(palette,gds,project=tmp_path)
    assert output.exists() and output!=palette
    assert hashlib.sha256(gds.read_bytes()).digest()==original
    names={p.findtext('source'):p.findtext('name') for p in ET.parse(output).getroot().findall('properties')}
    assert names['68/20@1']=='metal 1' # preserve trusted PDK-authored display name
    for pair,name in {'64/5':'nwell.label','65/20':'diff.drawing','66/44':'licon1.drawing','69/44':'via2.drawing'}.items():
        assert names[pair+'@1']==name
    assert '250/200' in info['unmapped_pairs']
    assert '250/200@1' not in names
    assert len(info['verified_pairs'])==5
    assert 'sky130_gds' not in output.read_text()
    assert klayout_open_argv('klayout.exe',gds,palette=output)[-1]=='-lx'
    assert (tmp_path/'build/latest/klayout_layer_mapping.json').exists()

def test_missing_palette_does_not_create_fake_map(tmp_path):
    gds=tmp_path/'x.gds';demo_gds(gds)
    result,info=named_sky130_palette(None,gds)
    assert result is None and len(info['verified_pairs'])==5

def test_layer_scanner_rejects_corrupt_stream(tmp_path):
    x=tmp_path/'bad.gds'; x.write_bytes(b'\x00\x00\x0d\x02garbage')
    assert gds_layer_pairs(x)==set()
