"""No Windows/WSL setup actions. Test the exact failure and installer contract."""
from pathlib import Path
from types import SimpleNamespace

from chipcompiler import wsl_backend_discovery as wd
from chipcompiler import windows_optional_install as opt


def fake_run_for(list_bytes, okay=('Ubuntu-24.04',), error='not initialized'):
    calls = []
    def run(args, **kw):
        calls.append(args)
        if args[:3] == ['wsl.exe', '--list', '--quiet']:
            return SimpleNamespace(returncode=0, stdout=list_bytes, stderr=b'')
        assert args[0] == 'wsl.exe' and args[1] == '--distribution'
        name = args[2]
        if name in okay:
            return SimpleNamespace(returncode=0, stdout=b'PICADS_WSL_SHELL_READY', stderr=b'')
        return SimpleNamespace(returncode=1, stdout=b'', stderr=error.encode())
    return run, calls


def test_wsl_utf16_without_bom_existing_ubuntu_2404():
    data = 'Ubuntu-24.04\r\ndocker-desktop\r\n'.encode('utf-16-le')
    run, calls = fake_run_for(data)
    result = wd.discover_distro(run=run)
    assert result['status'] == 'READY'
    assert result['distribution'] == 'Ubuntu-24.04'
    assert calls[1][2] == 'Ubuntu-24.04'


def test_existing_ubuntu_not_ready_is_not_mistaken_for_missing():
    run, calls = fake_run_for('Ubuntu\r\n'.encode('utf-16-le'), okay=())
    result = wd.discover_distro(run=run)
    assert result['status'] == 'PRESENT_NOT_READY'
    assert result['installed'] == ['Ubuntu']
    assert len(calls) == 2


def test_distro_priority_existing_preferred():
    run, calls = fake_run_for('Debian\nUbuntu-22.04\nUbuntu\n'.encode('utf-8'))
    assert wd.discover_distro(run=run)['status'] == 'PRESENT_NOT_READY'
    assert calls[1][2] == 'Ubuntu'  # exact Ubuntu first


def test_fallback_to_other_installed_distro():
    run, calls = fake_run_for('Ubuntu\nDebian\n'.encode(), okay=('Debian',))
    result = wd.discover_distro(run=run)
    assert result['status'] == 'READY' and result['distribution'] == 'Debian'
    assert [c[2] for c in calls[1:]] == ['Ubuntu', 'Debian']


def test_no_installed_linux_distro():
    run, calls = fake_run_for('docker-desktop\r\n'.encode('utf-16-le'))
    assert wd.discover_distro(run=run)['status'] == 'NONE'
    assert len(calls) == 1


def test_decode_wsl_utf16_bom_and_whitespace():
    assert wd.distro_names('\ufeffUbuntu-24.04\r\n'.encode('utf-16')) == ['Ubuntu-24.04']
    assert wd.distro_names('Ubuntu-24.04\x00\r\n'.encode('utf-8')) == ['Ubuntu-24.04']


def test_standalone_installer_contains_dynamic_wsl_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(opt.sys, 'platform', 'win32')
    report = opt.stage_librelane(tmp_path, lambda _:None, launch=False)
    batch = Path(report['launcher']).read_text(encoding='utf-8')
    assert Path(report['discovery_helper']).is_file()
    assert 'wsl.exe --list --quiet | findstr' not in batch
    assert '"%PICADS_PYTHON%" "%~dp0DISCOVER_WSL_DISTRO.py"' in batch
    assert ':distro_found' in batch
    assert 'if "%DISCOVERY_RC%"=="2" goto :install_ubuntu' in batch
    assert 'wsl.exe --distribution "%PICADS_DISTRO%"' in batch
    assert 'wsl.exe --install -d Ubuntu' in batch
    assert str(Path(opt.sys.executable).resolve()) in batch
    assert 'LIBRELANE_SMOKE_TEST_PASS' in batch
    assert not Path(report['directory'], 'backend_smoke_passed.txt').exists()


def test_do_not_overwrite_success_marker_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(opt.sys, 'platform', 'win32')
    marker = tmp_path / 'librelane' / 'backend_smoke_passed.txt'
    marker.parent.mkdir(parents=True)
    marker.write_text('LIBRELANE_SMOKE_TEST_PASS\n')
    opt.stage_librelane(tmp_path, lambda _:None, launch=False)
    assert marker.exists()


def test_existing_distro_override(monkeypatch):
    run, calls = fake_run_for('Ubuntu-24.04\nDebian\n'.encode(), okay=('Ubuntu-24.04', 'Debian'))
    result = wd.discover_distro(run=run, override='Debian')
    assert result['status'] == 'READY' and result['distribution'] == 'Debian'
    assert len(calls) == 2 and calls[1][2] == 'Debian'


def test_overridden_nonexistent_distro_is_not_auto_installed():
    run, calls = fake_run_for('Ubuntu-24.04\n'.encode())
    result = wd.discover_distro(run=run, override='Ubuntu')
    assert result['status'] == 'PRESENT_NOT_READY'
    assert len(calls) == 1


def test_discovery_cli_saves_name_and_clears_stale_file(tmp_path, monkeypatch, capsys):
    dest = tmp_path / 'wsl_distribution.txt'
    dest.write_text('stale distro\n')
    monkeypatch.setattr(wd, 'discover_distro', lambda: {'status':'READY', 'distribution':'Ubuntu-24.04'})
    assert wd.main([str(dest)]) == 0
    assert dest.read_text() == 'Ubuntu-24.04\n'
    monkeypatch.setattr(wd, 'discover_distro', lambda: {'status':'PRESENT_NOT_READY', 'installed':['Ubuntu']})
    assert wd.main([str(dest)]) == 3
    assert not dest.exists()
    assert 'will NOT reinstall Ubuntu' in capsys.readouterr().out


def test_discovery_bad_wsl_command_is_unavailable():
    def fail_run(*args, **kwargs):
        raise OSError('could not launch WSL')
    assert wd.discover_distro(run=fail_run)['status'] == 'WSL_UNAVAILABLE'
