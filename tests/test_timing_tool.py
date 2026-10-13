import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('profiler',Path(__file__).resolve().parents[1]/'REPORT_LIBRELANE_TIMES.py')
profiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(profiler)

def test_timing_extraction():
    entries,total=profiler.parse_stage_timings('''[20:00:00] VERBOSE Running 'Yosys.Synthesis' at xyz
[20:00:20] VERBOSE Running 'OpenROAD.GlobalPlacement' at abc
[20:02:00] VERBOSE Running 'OpenROAD.DetailedRouting' at abc
[20:05:05] INFO Flow complete.''')
    assert total==305
    assert entries[0]==('OpenROAD.DetailedRouting',185)
    assert entries[1]==('OpenROAD.GlobalPlacement',100)

def test_no_data():
    entries,total=profiler.parse_stage_timings('No timestamp info')
    assert not entries and total is None
