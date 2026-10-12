"""v0.16.8 runtime state-machine tests: no subprocesses or downloads on host."""
import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler import windows_librelane_setup as setup


def ok(stdout='', stderr='', rc=0):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def fake_windows(which_docker=True, linux_docker=True, smoke=True, yosys=True):
    calls = []
    def which(name):
        return 'C:/Docker/docker.exe' if which_docker and name in ('docker', 'docker.exe') else None
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ['wsl.exe', '--list', '--quiet']:
            return ok('Ubuntu\r\ndocker-desktop\r\n'.encode('utf-16-le'), b'')
        if argv[:2] == ['wsl.exe', '--distribution'] and argv[4:7] == ['sh', '-c', 'printf PICADS_WSL_SHELL_READY']:
            return ok(b'PICADS_WSL_SHELL_READY', b'')
        if argv[0] == 'C:/Docker/docker.exe':
            return ok('29.8.2\n')
        if argv[:2] == ['wsl.exe', '--distribution'] and argv[4:6] == ['bash', '-lc']:
            shell = argv[-1]
            if shell.startswith('docker info'):
                return ok('29.8.2\n') if linux_docker else ok('', 'docker command not found', 127)
            if shell.startswith('command -v yosys'):
                return ok() if yosys else ok('', 'not installed', 1)
            if '--smoke-test' in shell:
                return ok() if smoke else ok('', 'smoke failed', 1)
            return ok()
        if argv[0] == 'powershell.exe':
            raise AssertionError('must not reinstall working Docker')
        raise AssertionError('Unexpected: ' + repr(argv))
    return run, which, calls


def test_windows_engine_good_even_when_gui_path_is_stale(tmp_path):
    path = tmp_path / 'AppData' / 'Local'
    cli = path / 'Programs' / 'DockerDesktop' / 'resources' / 'bin' / 'docker.exe'
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b'fake')
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return ok('29.8.2\n')
    result = setup.docker_windows_status(env={'LOCALAPPDATA': str(path)},
        which=lambda _: None, runner=fake_run)
    assert result['status'] == 'READY'
    assert result['executable'] == str(cli)
    assert len(calls) == 1


def test_desktop_installed_no_cli_does_not_trigger_reinstall(tmp_path, monkeypatch):
    app = tmp_path / 'Programs' / 'DockerDesktop' / 'Docker Desktop.exe'
    app.parent.mkdir(parents=True)
    app.write_bytes(b'exe')
    result = setup.docker_windows_status(env={'LOCALAPPDATA': str(tmp_path)}, which=lambda _: None)
    assert result['status'] == 'INSTALLED_CLI_NOT_FOUND'


def test_working_docker_but_no_ubuntu_integration_stops_safely(tmp_path, monkeypatch):
    run, which, calls = fake_windows(linux_docker=False)
    monkeypatch.setattr(setup, 'DISTRO_FILE', tmp_path / 'wsl_distribution.txt')
    monkeypatch.setattr(setup, 'MARKER', tmp_path / 'backend_smoke_passed.txt')
    assert setup.setup(runner=run, which=which, environ={}) == 4
    assert not (tmp_path / 'backend_smoke_passed.txt').exists()
    assert not any(c[0] == 'powershell.exe' for c in calls)
    assert not any('pip install' in c[-1] for c in calls)


def test_all_ready_runs_smoke_and_records_pass(tmp_path, monkeypatch):
    run, which, calls = fake_windows()
    monkeypatch.setattr(setup, 'DISTRO_FILE', tmp_path / 'wsl_distribution.txt')
    monkeypatch.setattr(setup, 'MARKER', tmp_path / 'backend_smoke_passed.txt')
    monkeypatch.setattr(setup, 'RECEIPT', tmp_path / 'backend_smoke_receipt.json')
    assert setup.setup(runner=run, which=which, environ={}) == 0
    assert (tmp_path / 'backend_smoke_passed.txt').read_text() == 'LIBRELANE_SMOKE_TEST_PASS\n'
    assert json.loads((tmp_path / 'backend_smoke_receipt.json').read_text())['distro'] == 'Ubuntu'
    assert any('--smoke-test' in c[-1] for c in calls)
    assert not any(c[0] == 'powershell.exe' for c in calls)
    assert not any(c[:4] == ['wsl.exe', '--install', '-d', 'Ubuntu'] for c in calls)


def test_smoke_failed_not_marked_pass(tmp_path, monkeypatch):
    run, which, calls = fake_windows(smoke=False)
    monkeypatch.setattr(setup, 'DISTRO_FILE', tmp_path / 'wsl_distribution.txt')
    monkeypatch.setattr(setup, 'MARKER', tmp_path / 'backend_smoke_passed.txt')
    monkeypatch.setattr(setup, 'RECEIPT', tmp_path / 'backend_smoke_receipt.json')
    assert setup.setup(runner=run, which=which, environ={}) == 6
    assert not (tmp_path / 'backend_smoke_passed.txt').exists()


def test_probe_only_no_side_effects(tmp_path, monkeypatch):
    run, which, calls = fake_windows()
    monkeypatch.setattr(setup, 'DISTRO_FILE', tmp_path / 'wsl_distribution.txt')
    monkeypatch.setattr(setup, 'MARKER', tmp_path / 'backend_smoke_passed.txt')
    assert setup.setup(runner=run, which=which, environ={}, probe_only=True) == 0
    assert not (tmp_path / 'wsl_distribution.txt').exists()
    assert not any('pip install' in c[-1] for c in calls)


def test_installed_yosys_required_for_pip_path(tmp_path, monkeypatch):
    run, which, calls = fake_windows(yosys=False)
    monkeypatch.setattr(setup, 'DISTRO_FILE', tmp_path / 'wsl_distribution.txt')
    monkeypatch.setattr(setup, 'MARKER', tmp_path / 'backend_smoke_passed.txt')
    monkeypatch.setattr(setup, 'RECEIPT', tmp_path / 'backend_smoke_receipt.json')
    assert setup.setup(runner=run, which=which, environ={}) == 0
    assert any('sudo apt-get install -y yosys' in c[-1] for c in calls)


def test_wsl_external_runner_uses_venv_without_global_symlink(tmp_path, monkeypatch):
    import io
    from chipcompiler import tools
    from chipcompiler.diagnostics import IssueCollector, EventLog
    monkeypatch.setattr(tools, 'resolve_tool', lambda name: 'C:/Windows/System32/wsl.exe' if name == 'wsl.exe' else None)
    created = []
    class FakeProcess:
        def __init__(self, argv, **kwargs):
            created.append(argv)
            self.stdout = io.StringIO('ok\n')
            self.stderr = io.StringIO('')
            self.returncode = 0
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(tools.subprocess, 'Popen', FakeProcess)
    result = tools.run_external(['librelane', '--dockerized', '--smoke-test'],
        tmp_path, tmp_path, IssueCollector(), EventLog(tmp_path / 'events.jsonl'),
        'physical', runner='wsl', wsl_distribution='Ubuntu')
    assert result['status'] == 'PASS'
    assert created[0][:3] == ['C:/Windows/System32/wsl.exe', '--distribution', 'Ubuntu']
    assert created[0][-2:] == ['--dockerized', '--smoke-test']
    assert 'picads-librelane/venv/bin/python' in created[0][-4]
    assert 'bash' in created[0]
