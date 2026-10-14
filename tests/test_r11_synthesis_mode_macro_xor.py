"""Regression for ASTER-8 2026-10-14: Synthesize must not run macro GDS signoff.

The incident's BuildSession mode was `build`, and the actual failure was the
Classic-flow Magic/KLayout XOR checker for aster8_program. Physical validation
must stay enabled in `physical`, `layout`, and `verify_layout` modes instead.
"""
from pathlib import Path
import shutil
import json
import pytest

from chipcompiler.pipeline import BuildSession
from chipcompiler.co_macros import classify_macro_hardening_failure

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'tiny8_co_native'


def test_synthesize_macros_compiles_dls_yosys_only(tmp_path, monkeypatch):
    from chipcompiler import pipeline, co_macros
    root = tmp_path / 'chip'
    shutil.copytree(EXAMPLE, root)
    stages=[]

    def fake_synthesis(argv, cwd, logs, issues, events, stage, timeout=600, **kw):
        stages.append(stage)
        if stage=='yosys':
            (cwd/'synthesized.v').write_text('module tiny8_cpu; endmodule\n')
        elif stage=='abc_aig':
            (cwd/'abc_optimized.aig').write_bytes(b'aig 0 0 0 0 0\n')
        else:
            raise AssertionError('Unexpected physical tool in synthesis mode: '+stage)
        return {'status':'PASS','returncode':0}

    def forbid_macro(*args, **kwargs):
        raise AssertionError('F7 Synthesize must not harden macros or run LibreLane')

    monkeypatch.setattr(pipeline, 'run_external', fake_synthesis)
    monkeypatch.setattr(co_macros, 'run_native_macro_flow', forbid_macro)
    r=BuildSession(root,mode='build').run()
    assert r.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'), r.as_dict()
    assert stages == ['yosys','abc_aig']
    assert r.stages['co_macro_physical']['status']=='DEFERRED'
    assert r.stages['co_macro_physical']['physical_source_equivalence']=='NOT_ESTABLISHED'
    assert r.stages['yosys']['status']=='PASS'
    assert (root/'build/latest/synthesized.v').is_file()
    assert not (root/'build/co_macro_cache').exists()
    assert not (root/'build/latest/layout_artifacts.json').exists()
    assert 'physical' not in r.stages  # Not a signoff action.


def test_layout_and_legacy_physical_still_dispatch_macros(tmp_path, monkeypatch):
    from chipcompiler import pipeline, co_macros
    from types import SimpleNamespace
    monkeypatch.setattr(pipeline,'physical_preflight',lambda *a,**k:SimpleNamespace(
        status='READY_TO_ATTEMPT',checks={'settings':{'status':'PASS'}},
        librelane_config={'CLOCK_PERIOD':100},
        as_dict=lambda:{'status':'READY_TO_ATTEMPT','checks':{'settings':{'status':'PASS'}}}))
    called=[]
    def failing_macro(session,preflight):
        called.append(session.mode)
        session._done('physical','FAIL',reason='mock macro error; physical mode remains required')
    monkeypatch.setattr(co_macros,'run_native_macro_flow',failing_macro)
    for mode in ('layout','physical'):
        root=tmp_path/mode
        shutil.copytree(EXAMPLE,root)
        r=BuildSession(root,mode=mode).run()
        assert r.stages['physical']['status']=='FAIL',r.as_dict()
        assert r.stages['project']['status']=='PASS'
    assert called == ['layout','physical']


def test_xor_diagnostics_are_failure_not_suppressed(tmp_path):
    log=tmp_path/'macro_aster8_program.log'
    log.write_text('[STDOUT] \x1b[31mERROR\x1b[0m One or more deferred errors were encountered:\n'
                   '[STDOUT] \x1b[31m1 XOR differences found.\x1b[0m\n')
    data=classify_macro_hardening_failure(log,{'status':'FAIL','returncode':2})
    assert data['status']=='MAGIC_KLAYOUT_XOR_MISMATCH'
    assert data['xor_difference_count']==1
    assert 'do not disable' in data['remedy']
    log.write_text('ERROR: OpenROAD.GeneratePDN [PDN-0179] Unable to repair all channels.\n')
    assert classify_macro_hardening_failure(log,{'status':'FAIL'})['status']=='MACRO_HARDENING_FAILED'
