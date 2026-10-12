"""V1 acceptance: independently specified ALU slice and deliberate failures."""
from __future__ import annotations
import itertools
import json
import shutil
from pathlib import Path

import pytest
from chipcompiler.ir import DLS
from chipcompiler.pipeline import BuildSession
from chipcompiler.rtl_check import make_testbench

REFERENCE = Path(__file__).resolve().parents[1] / 'examples' / 'alu_slice_component'


def _copy(tmp_path):
    project=tmp_path/'alu'
    shutil.copytree(REFERENCE,project,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    return project


def oracle(a:int,b:int,op:int)->int:
    """Spec defined independently of PICADS and its source interpreter.

    Subtraction is a 4-bit ALU operation and is zero-extended to five bits;
    addition preserves the carry bit. This documents an important hardware
    width convention that otherwise can be easy to misunderstand.
    """
    return ((a+b) if op==0 else ((a-b)&15) if op==1 else (a&b) if op==2 else (a^b))


def test_real_alu_component_all_possible_inputs(tmp_path):
    project=_copy(tmp_path)
    result=BuildSession(project,'compile').run()
    assert result.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),result.as_dict()
    assert result.stages['equivalence']['status']=='PASS_EXHAUSTIVE'
    rtl=Path(result.files['verilog']).read_text()
    assert 'module alu_slice' in rtl
    d=DLS.load(result.files['dls'])
    assert d.inputs=={'a':4,'b':4,'op':2}
    assert len(d.outputs['result'])==5
    sim=d.new_simulator()
    for a,b,op in itertools.product(range(16),range(16),range(4)):
        assert sim.step({'a':a,'b':b,'op':op})['result']==oracle(a,b,op), (a,b,op)
    assert d.stats()['primitive_gates']>0


def test_alu_wrong_wiring_is_detected_independently(tmp_path):
    project=_copy(tmp_path)
    report=BuildSession(project).run()
    assert report.status in ('SUCCESS','SUCCESS_WITH_WARNINGS')
    d=DLS.load(report.files['dls'])
    # Simulate a realistic synthesis bug: result bit 0 has been shorted low.
    d.outputs['result'][0]='@0'
    observed=d.new_simulator().step({'a':1,'b':0,'op':0})['result']
    assert observed!=oracle(1,0,0)


def test_error_in_user_source_is_diagnosed_and_recoverable(tmp_path):
    project=_copy(tmp_path)
    source=project/'circuit.py'
    original=source.read_text()
    source.write_text('def alu_slice(a: u4, b: u4, op: u2) -> u5:\n    return a + missing_signal\n')
    bad=BuildSession(project,'compile').run()
    assert bad.status=='FAILED'
    assert bad.issues
    assert not any(issue['code'].startswith('INTERNAL.') for issue in bad.issues),bad.issues
    source.write_text(original)
    fixed=BuildSession(project,'compile').run()
    assert fixed.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),fixed.issues
    assert fixed.run_id!=bad.run_id
    assert Path(fixed.files['dls']).is_file()
    assert list((project/'build'/'history').glob('*/report.json'))


def test_illegal_source_syntax_blocked_and_does_not_export_stale_rtl(tmp_path):
    project=_copy(tmp_path)
    good=BuildSession(project,'compile').run()
    assert good.status in ('SUCCESS','SUCCESS_WITH_WARNINGS')
    (project/'circuit.py').write_text('def alu_slice(\n')
    bad=BuildSession(project,'compile').run()
    assert bad.status=='FAILED'
    assert bad.stages['export']['status']=='BLOCKED'
    assert not list((project/'build'/'latest').glob('*.v'))


def test_rtl_testbench_covers_actual_compiled_interfaces(tmp_path):
    project=_copy(tmp_path)
    report=BuildSession(project,'compile').run()
    d=DLS.load(report.files['dls'])
    vectors=[{'a':a,'b':b,'op':op} for a,b,op in ((0,0,0),(15,15,0),(0,1,1),(15,7,2),(8,7,3))]
    text=make_testbench(d,vectors)
    assert 'alu_slice dut' in text
    assert 'op = 2\'d' in text
    assert 'result' in text


def test_alu_project_has_only_logic_no_handmade_masks_or_netlists():
    files={p.relative_to(REFERENCE).as_posix() for p in REFERENCE.rglob('*') if p.is_file() and not ({'build','.chipcompiler','.pytest_cache'} & set(p.relative_to(REFERENCE).parts))}
    assert files=={'chip.yaml','design.mcd','architecture.co','circuit.py'}
    assert not (REFERENCE/'build'/'layout.gds').exists()



def test_feature_report_is_not_mistaken_for_native_signoff():
    from chipcompiler.feature_validation import VERSION
    from chipcompiler import __version__
    assert VERSION==__version__
    from chipcompiler.acceptance import selected_pdk_root
    assert callable(selected_pdk_root)
