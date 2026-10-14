"""Local structural checks for the fictional 2003-era CPU design (no RTL simulator)."""
import shutil
from pathlib import Path
import yaml
from chipcompiler.pipeline import BuildSession
from chipcompiler.co_macros import read_macro_constraints,allocate_macro_rectangles,check_macro_placement_zones

SOURCE=Path(__file__).parents[1]/'examples'/'helios16_2003'


def test_helios16_native_picads_project_compiles_without_gui(tmp_path):
    project=tmp_path/'Helios16'
    shutil.copytree(SOURCE,project)
    build=BuildSession(project,'compile').run()
    assert build.stages['export']['status']=='PASS', build.as_dict()
    assert build.stages['generate']['stats']['primitive_gates']>1000


def test_six_real_modules_and_bounded_macro_packing():
    co=yaml.safe_load((SOURCE/'architecture.co').read_text())['physical_macros']
    physical=yaml.safe_load((SOURCE/'chip.yaml').read_text())['physical']
    spec=read_macro_constraints(co,SOURCE,physical)
    assert len(spec['blocks'])==6
    assert {b['instance'] for b in spec['blocks']}=={
        'u_program','u_data','u_control','u_registers','u_alu','u_io'}
    rects=[{**b,'size_um':[b['width'],b['height']]} for b in spec['blocks']]
    rows,_=allocate_macro_rectangles(rects,spec['spacing'],mode=spec['placement_mode'],
         region_um=spec['placement_region_um'],stayouts_um=spec['placement_stayouts_um'],halo_um=spec['halo_um'])
    assert check_macro_placement_zones(rows,region_um=spec['placement_region_um'],
        stayouts_um=spec['placement_stayouts_um'],halo_um=spec['halo_um'])


def test_demo_cpu_rtl_is_separately_disclosed():
    text=(SOURCE/'README.md').read_text()
    assert 'not a taped-out' in text.lower()
    assert 'not the cpu source' in text.lower()
    assert (SOURCE/'rtl/helios16_tb.v').is_file()
    assert (SOURCE/'LAUNCH_ANNOUNCEMENT_FICTION.md').read_text().startswith('# Fictional')
