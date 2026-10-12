"""Regression for v0.16.8 standalone module-name mismatch.

The v0.16.8 installer staged DISCOVER_WSL_DISTRO.py but tried to import
wsl_backend_discovery from an unrelated Python process. A pure unit test of
stage_librelane did not detect that because it never EXECUTED the staged file.
These tests deliberately run that generated script in a fresh Python process.
"""
import os
import subprocess
import sys
from pathlib import Path

from chipcompiler import windows_optional_install as opt


def stage(tmp_path, monkeypatch):
    monkeypatch.setattr(opt.sys, 'platform', 'win32')
    return opt.stage_librelane(tmp_path / 'dependencies', lambda _: None, launch=False)


def test_staged_python_script_imports_its_sibling_from_a_new_process(tmp_path, monkeypatch):
    report = stage(tmp_path, monkeypatch)
    canonical = Path(report['directory']) / 'wsl_backend_discovery.py'
    assert canonical.is_file(), 'standalone Python importer needs this exact filename'
    assert Path(report['discovery_helper']) == canonical
    process = subprocess.run([sys.executable, report['setup_helper'], '--help'],
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert '--probe-only' in process.stdout


def test_staged_python_falls_back_to_legacy_discovery_filename(tmp_path, monkeypatch):
    report = stage(tmp_path, monkeypatch)
    canonical = Path(report['discovery_helper'])
    legacy = canonical.with_name('DISCOVER_WSL_DISTRO.py')
    assert legacy.is_file()
    canonical.unlink()  # Simulate the exact pre-fix v0.16.8 staged layout.
    process = subprocess.run([sys.executable, report['setup_helper'], '--help'],
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr


def test_standalone_probe_executes_against_fake_wsl_docker(tmp_path, monkeypatch):
    if os.name == 'nt':
        import pytest
        pytest.skip('Simulated POSIX launchers; native Windows uses the real WSL/Docker checks')
    report = stage(tmp_path, monkeypatch)
    bin_dir = tmp_path / 'fake_system_bin'
    bin_dir.mkdir()
    wsl = bin_dir / 'wsl.exe'
    wsl.write_text('''#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args == ['--list', '--quiet']:
    sys.stdout.buffer.write('Ubuntu\\r\\n'.encode('utf-16-le'))
elif args[:4] == ['--distribution', 'Ubuntu', '--exec', 'sh']:
    print('PICADS_WSL_SHELL_READY')
elif args[:4] == ['--distribution', 'Ubuntu', '--exec', 'bash']:
    print('29.8.2')
else:
    sys.exit(9)
''', encoding='utf-8')
    wsl.chmod(0o755)
    docker = bin_dir / 'docker.exe'
    docker.write_text('#!/usr/bin/env python3\nprint("29.8.2")\n', encoding='utf-8')
    docker.chmod(0o755)
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
    p = subprocess.run([sys.executable, report['setup_helper'], '--probe-only'],
                       capture_output=True, text=True, env=env, timeout=20)
    assert p.returncode == 0, p.stdout + '\n' + p.stderr
    assert 'PROBE PASS' in p.stdout
    assert not (Path(report['directory']) / 'backend_smoke_passed.txt').exists()


def test_restaging_heals_missing_canonical_module(tmp_path, monkeypatch):
    report = stage(tmp_path, monkeypatch)
    helper = Path(report['discovery_helper'])
    helper.unlink()
    stage(tmp_path, monkeypatch)
    assert helper.is_file()
