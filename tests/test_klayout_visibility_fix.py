"""Regression for KLayout showing a blank layout when .lyp lacks GDS layers."""
from chipcompiler.klayout_layers import klayout_open_argv

def test_lyp_does_not_hide_unlisted_gds_layers(tmp_path):
    gds = tmp_path / 'tiny8_cpu.gds'
    palette = tmp_path / 'sky130.lyp'
    palette.write_text('<layer-properties><properties><source>68/20@1</source></properties></layer-properties>', encoding='utf-8')
    result = klayout_open_argv('klayout.exe', gds, palette=palette)
    assert result == ['klayout.exe', str(gds), '-l', str(palette), '-lx']

def test_no_palette_preserves_default_layer_discovery(tmp_path):
    gds = tmp_path / 'tiny8_cpu.gds'
    assert klayout_open_argv('klayout.exe', gds) == ['klayout.exe', str(gds)]

def test_invalid_palette_does_not_hide_default_gds_layers(tmp_path):
    gds = tmp_path / 'tiny8_cpu.gds'
    palette = tmp_path / 'bad.lyp'
    palette.write_text('corrupted layer file',encoding='utf-8')
    assert klayout_open_argv('klayout.exe', gds, palette=palette) == ['klayout.exe', str(gds)]
