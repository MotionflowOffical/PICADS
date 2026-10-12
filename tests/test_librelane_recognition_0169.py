"""Read-only WSL backend recognition; never talks to host WSL or Docker."""
from pathlib import Path
from types import SimpleNamespace
import json

from chipcompiler import wsl_backend
from chipcompiler import physical_flow


def receipt(root, *, distro='Ubuntu'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'backend_smoke_passed.txt').write_text('LIBRELANE_SMOKE_TEST_PASS\n', encoding='ascii')
    (root/'backend_smoke_receipt.json').write_text(json.dumps({'status':'PASS','distro':distro}), encoding='utf-8')


def mock_runner(args, **kwargs):
    assert args[:4] == ['C:/Windows/System32/wsl.exe', '--distribution', 'Ubuntu', '--exec']
    return SimpleNamespace(returncode=0, stdout='', stderr='')


def test_recorded_smoke_does_not_claim_live_ready(tmp_path):
    receipt(tmp_path)
    found = wsl_backend.backend_status(root=tmp_path)
    assert found['status'] == 'SMOKE_PASSED'
    assert found['recorded_smoke_pass']
    assert not found['available']
    assert found['distribution'] == 'Ubuntu'


def test_live_docker_yosys_librelane_tools_in_wsl(tmp_path):
    receipt(tmp_path)
    commands=[]
    def run(args, **kwargs):
        commands.append(args)
        return mock_runner(args, **kwargs)
    found = wsl_backend.backend_status(root=tmp_path, live=True, run=run,
                                     which=lambda x: 'C:/Windows/System32/wsl.exe')
    assert found['status'] == 'READY' and found['available']
    assert set(found['checks']) == {'docker','yosys','librelane'}
    assert any('picads-librelane/venv/bin/python' in cmd[-1] for cmd in commands)
    assert all(cmd[2] == 'Ubuntu' for cmd in commands)


def test_mismatched_distribution_never_inherits_smoke_receipt(tmp_path):
    receipt(tmp_path)
    found = wsl_backend.backend_status('Debian', root=tmp_path)
    assert not found['recorded_smoke_pass']
    assert found['status'] == 'NOT_VERIFIED'


def test_engine_fails_not_ready_despite_smoke_pass(tmp_path):
    receipt(tmp_path)
    def runner(args, **kwargs):
        if 'docker info' in args[-1]:
            return SimpleNamespace(returncode=1, stdout='', stderr='docker daemon offline')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    found = wsl_backend.backend_status(root=tmp_path, live=True, run=runner,
                                     which=lambda x: 'wsl.exe')
    assert not found['available']
    assert found['checks']['docker']['status'] == 'UNAVAILABLE'
    assert found['recorded_smoke_pass']


def test_no_marker_even_if_receipt_claims_pass(tmp_path):
    receipt(tmp_path)
    (tmp_path/'backend_smoke_passed.txt').unlink()
    found = wsl_backend.backend_status(root=tmp_path)
    assert not found['recorded_smoke_pass']


def test_preflight_selected_wsl_does_not_require_native_windows_exe(monkeypatch):
    monkeypatch.setattr(wsl_backend, 'backend_status', lambda *a, **kw: {
        'status':'READY', 'available':True, 'distribution':'Ubuntu', 'recorded_smoke_pass':True,
        'detail':'ok', 'checks':{x:{'status':'PASS','detail':''} for x in ('docker','yosys','librelane')}
    })
    p = physical_flow.physical_preflight({'enabled':True, 'pdk':'sky130A'}, False,
                                         execution='wsl', wsl_distribution='Ubuntu')
    assert p.checks['librelane']['status'] == 'PASS'
    assert p.checks['yosys']['status'] == 'PASS'
    assert p.checks['docker_wsl']['status'] == 'PASS'
    assert p.status == 'PARTIAL'  # PDK_ROOT not selected; not fake signoff


def test_missing_backend_preflight_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(wsl_backend, 'backend_status', lambda *a, **kw: {
        'status':'UNAVAILABLE', 'available':False, 'distribution':'Ubuntu', 'recorded_smoke_pass':True,
        'detail':'Docker not reachable', 'checks':{
            'docker':{'status':'UNAVAILABLE','detail':'Docker not reachable'},
            'librelane':{'status':'PASS','detail':''},'yosys':{'status':'PASS','detail':''}}
    })
    p = physical_flow.physical_preflight({'enabled':True, 'pdk':'sky130A'}, False,
                                         execution='wsl', wsl_distribution='Ubuntu')
    assert p.checks['docker_wsl']['status'] == 'UNAVAILABLE'
    assert p.status == 'PARTIAL'


def test_optional_icarus_probed_inside_wsl():
    calls=[]
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0 if args[-1] == 'iverilog' else 127)
    statuses=wsl_backend.probe_wsl_commands('Ubuntu',['iverilog','vvp'],run=run,which=lambda x:'wsl.exe')
    assert statuses == {'iverilog':True,'vvp':False}
    assert len(calls) == 2
