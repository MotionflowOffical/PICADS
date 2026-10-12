"""Contracts for Docker WSL setup; never download/install tools during tests."""
from pathlib import Path
from chipcompiler import windows_optional_install as opt


def _stage(tmp_path, monkeypatch):
    monkeypatch.setattr(opt.sys, 'platform', 'win32')
    report = opt.stage_librelane(tmp_path / 'dependencies', lambda _: None, launch=False)
    return report, Path(report['launcher']).read_text('utf-8'), Path(report['docker_installer_helper']).read_text('utf-8-sig')


def test_official_per_user_install_replaces_failing_winget(tmp_path, monkeypatch):
    report, batch, ps = _stage(tmp_path, monkeypatch)
    assert 'INSTALL_DOCKER_PER_USER.ps1' in batch
    assert "'install', '--user', '--backend=wsl-2'" in ps
    assert 'winget install --id Docker.DockerDesktop' not in batch
    assert 'https://desktop.docker.com/win/main/amd64/' in ps
    assert report['status'] == 'SETUP_REQUIRED'


def test_docker_install_reuses_cached_signed_installer(tmp_path, monkeypatch):
    _, batch, ps = _stage(tmp_path, monkeypatch)
    assert 'DockerDesktopInstallers' in ps
    assert 'Test-DockerInstallerSignature $candidate' in ps
    assert 'Get-AuthenticodeSignature' in ps
    assert "-ne 'Valid'" in ps
    assert 'Get-FileHash' in ps
    assert 'Invoke-WebRequest' in ps


def test_no_destructive_owner_acl_or_automatic_erase(tmp_path, monkeypatch):
    _, batch, ps = _stage(tmp_path, monkeypatch)
    combined = batch.lower() + '\n' + ps.lower()
    for forbidden in ('takeown ', 'icacls ', 'set-acl ', 'remove-item -literalpath c:\\programdata',
                      'wsl.exe --unregister', 'docker system prune', 'format c:'):
        assert forbidden not in combined
    assert 'will not be modified' in ps
    assert ':pending' in batch
    assert 'LIBRELANE_SMOKE_TEST_PASS' in batch


def test_docker_cli_detection_with_per_user_windows_path(tmp_path, monkeypatch):
    _, batch, _ = _stage(tmp_path, monkeypatch)
    assert r'%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe' in batch
    assert r'%ProgramFiles%\Docker\Docker\resources\bin\docker.exe' in batch
    assert 'docker info >nul' in batch
    assert 'wsl.exe --distribution "%PICADS_DISTRO%" --exec bash -lc "docker info' in batch
    assert 'goto :dockercheck' in batch


def test_distro_detection_is_retained(tmp_path, monkeypatch):
    report, batch, _ = _stage(tmp_path, monkeypatch)
    assert Path(report['discovery_helper']).exists()
    assert 'wsl.exe --install -d Ubuntu' in batch
    assert 'if "%DISCOVERY_RC%"=="2" goto :install_ubuntu' in batch
    assert 'wsl.exe --distribution "%PICADS_DISTRO%"' in batch
