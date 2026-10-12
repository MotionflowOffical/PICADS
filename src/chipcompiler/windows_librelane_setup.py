"""PICADS guided LibreLane installer for Windows + an existing WSL distribution.

Staged standalone next to DISCOVER_WSL_DISTRO.py. No imports from the PICADS
package are necessary on the target machine. Do not confuse 'installed'
with 'Docker daemon available' or a passing LibreLane smoke test.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# This file runs either within the chipcompiler package or copied into
# dependencies/librelane/ as a standalone script.  v0.16.8 staged the helper
# as DISCOVER_WSL_DISTRO.py but imported wsl_backend_discovery: accept both
# layouts so an already-generated launcher keeps working after this repair.
if __package__:
    from .wsl_backend_discovery import discover_distro
else:
    try:
        from wsl_backend_discovery import discover_distro
    except ModuleNotFoundError as exc:
        if exc.name != 'wsl_backend_discovery':
            raise
        from DISCOVER_WSL_DISTRO import discover_distro

HERE = Path(__file__).resolve().parent
MARKER = HERE / 'backend_smoke_passed.txt'
DISTRO_FILE = HERE / 'wsl_distribution.txt'
RECEIPT = HERE / 'backend_smoke_receipt.json'


def execute(argv, *, timeout=30, quiet=False, runner=None):
    """argv-based execution prevents CMD quoting/encoding of a WSL distro name."""
    runner = runner or subprocess.run
    try:
        opts = {'check': False, 'timeout': timeout}
        if quiet:
            opts.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        encoding='utf-8', errors='replace')
        return runner([str(v) for v in argv], **opts)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'Command failed to launch/complete: {argv[0]}: {exc}')
        return None


def wsl_command(distro, shell_script, *, timeout=60, quiet=False, runner=None):
    return execute(['wsl.exe', '--distribution', distro, '--exec', 'bash', '-lc',
                    shell_script], timeout=timeout, quiet=quiet, runner=runner)


def worked(result):
    return result is not None and result.returncode == 0


def _candidate_docker_paths(env):
    for key, subdirs in (
        ('LOCALAPPDATA', ('Programs/DockerDesktop/resources/bin/docker.exe',
                          'Programs/Docker Desktop/resources/bin/docker.exe')),
        ('ProgramFiles', ('Docker/Docker/resources/bin/docker.exe',)),
        ('ProgramW6432', ('Docker/Docker/resources/bin/docker.exe',)),
    ):
        if env.get(key):
            for rel in subdirs:
                yield Path(env[key]) / rel


def _candidate_desktop_paths(env):
    for key, rels in (
        ('LOCALAPPDATA', ('Programs/DockerDesktop/Docker Desktop.exe',
                          'Programs/Docker Desktop/Docker Desktop.exe')),
        ('ProgramFiles', ('Docker/Docker/Docker Desktop.exe',)),
        ('ProgramW6432', ('Docker/Docker/Docker Desktop.exe',)),
    ):
        if env.get(key):
            for rel in rels:
                yield Path(env[key]) / rel


def docker_windows_status(*, env=None, which=None, exists=None, runner=None):
    """Never reinstall Docker just because a stale GUI PATH lacks docker.exe."""
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    exists = (lambda path: path.is_file()) if exists is None else exists
    choices = []
    for name in ('docker.exe', 'docker'):
        found = which(name)
        if found and found not in choices:
            choices.append(found)
    for path in _candidate_docker_paths(env):
        if exists(path) and str(path) not in choices:
            choices.append(str(path))
    desktop_installed = any(exists(path) for path in _candidate_desktop_paths(env))
    failures = []
    for exe in choices:
        result = execute([exe, 'info', '--format', '{{.ServerVersion}}'], quiet=True,
                         timeout=35, runner=runner)
        if worked(result) and (result.stdout or '').strip():
            return {'status': 'READY', 'executable': exe, 'server': result.stdout.strip()}
        if result is not None:
            failures.append((result.stderr or result.stdout or '').strip()[-500:])
    if choices:
        return {'status': 'ENGINE_NOT_READY', 'executable': choices[0],
                'detail': next((x for x in failures if x), '')}
    if desktop_installed:
        return {'status': 'INSTALLED_CLI_NOT_FOUND',
                'detail': 'Docker Desktop exists but docker.exe was not found via PATH or known install directories.'}
    return {'status': 'ABSENT'}


def setup(*, probe_only=False, runner=None, environ=None, which=None, exists=None):
    env = os.environ if environ is None else environ
    print('PICADS - LibreLane WSL2/Docker setup (environment-aware)')
    print('No WSL distributions, Docker installations, or container data will be removed.')
    print('\n[1/5] Identifying a runnable WSL distribution...')
    distro_info = discover_distro(run=runner)
    if distro_info['status'] == 'NONE':
        print('No user Linux distribution is installed. Ubuntu setup is needed.')
        if not probe_only:
            execute(['wsl.exe', '--install', '-d', 'Ubuntu'], timeout=1800, runner=runner)
        print('Initialize Ubuntu and rerun setup. Nothing else was installed.')
        return 2
    if distro_info['status'] != 'READY':
        print('WSL is not usable:', distro_info)
        return 2
    distro = distro_info['distribution']
    print('Runnable WSL distro:', repr(distro))
    if not probe_only:
        DISTRO_FILE.write_text(distro + '\n', encoding='ascii')
    print('\n[2/5] Looking for an existing, RUNNING Docker Desktop engine...')
    docker_status = docker_windows_status(env=env, which=which, exists=exists, runner=runner)
    print('Windows Docker status:', docker_status['status'])
    if docker_status['status'] != 'READY':
        if docker_status['status'] == 'ABSENT' and not probe_only:
            ps = HERE / 'INSTALL_DOCKER_PER_USER.ps1'
            if not ps.is_file():
                print('Missing PowerShell installer helper:', ps)
                return 3
            print('No Docker CLI or Desktop found. Launching signed per-user installer.')
            result = execute(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'RemoteSigned',
                              '-File', str(ps), '-InstallRoot', str(HERE)],
                             timeout=3600, runner=runner)
            if worked(result):
                print('Installation completed; start Docker Desktop, then rerun PICADS.')
            return 3
        if docker_status['status'] == 'ENGINE_NOT_READY':
            print('Docker is installed, but its ENGINE did not answer. Start Docker Desktop.')
            if docker_status.get('detail'):
                print('Docker detail:', docker_status['detail'])
        elif docker_status['status'] == 'INSTALLED_CLI_NOT_FOUND':
            print('Docker Desktop is installed. Start/restart it and refresh the Windows PATH.')
            print('No reinstallation will be attempted.')
        elif docker_status['status'] == 'ABSENT':
            print('Docker is absent. Run normal setup to install it.')
        return 3
    print('Connected to Windows Docker engine', docker_status['server'],
          'using', docker_status['executable'])
    print('\n[3/5] Checking Docker INSIDE the selected Ubuntu/WSL distro...')
    probe = wsl_command(distro, 'docker info --format "{{.ServerVersion}}"',
                        timeout=60, quiet=True, runner=runner)
    if not worked(probe) or not (probe.stdout or '').strip():
        print('Docker is not yet usable from', distro + '.')
        detail = ((probe.stderr or probe.stdout or '').strip() if probe else '')[-800:]
        if detail:
            print('WSL detail:', detail)
        print('Open Docker Desktop > Settings > Resources > WSL Integration.')
        print('Enable', distro, ', Apply & Restart, then rerun this setup.')
        print('The Windows engine being healthy does not prove WSL integration.')
        return 4
    print('WSL Docker daemon available:', probe.stdout.strip())
    if probe_only:
        print('PROBE PASS: WSL, Windows Docker, and WSL Docker work; no installations performed.')
        return 0
    print('\n[4/5] Ensuring Linux Python/venv prerequisites and LibreLane...')
    prerequisites = 'command -v python3 >/dev/null && python3 -c "import sys; assert sys.version_info >= (3, 10)" && python3 -m venv --help >/dev/null 2>&1'
    result = wsl_command(distro, prerequisites, timeout=60, quiet=True, runner=runner)
    if not worked(result):
        print('Installing Python3 venv prerequisites through Ubuntu/Debian apt (sudo may prompt).')
        apt = 'command -v apt-get >/dev/null && sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip python3-tk curl make git build-essential'
        if not worked(wsl_command(distro, apt, timeout=1800, runner=runner)):
            print('Linux prerequisites failed. Inspect apt/sudo output above.')
            return 5
        if not worked(wsl_command(distro, prerequisites, timeout=60, runner=runner)):
            print('LibreLane requires Python >=3.10, including venv support.')
            return 5
    yosys = wsl_command(distro, 'command -v yosys >/dev/null 2>&1',
                        timeout=30, quiet=True, runner=runner)
    if not worked(yosys):
        print('PICADS also runs Yosys directly in WSL. Installing Ubuntu/Debian yosys...')
        apt_yosys = 'command -v apt-get >/dev/null && sudo apt-get update && sudo apt-get install -y yosys'
        if not worked(wsl_command(distro, apt_yosys, timeout=1800, runner=runner)):
            print('Could not install WSL Yosys; PICADS synthesis will not work yet.')
            return 5
    setup_cmd = ('mkdir -p "$HOME/.local/share/picads-librelane" && '
                 'python3 -m venv "$HOME/.local/share/picads-librelane/venv" && '
                 'PIP_CACHE_DIR="$HOME/.cache/picads-librelane-pip" '
                 '"$HOME/.local/share/picads-librelane/venv/bin/python" -m pip install --upgrade pip librelane')
    if not worked(wsl_command(distro, setup_cmd, timeout=2400, runner=runner)):
        print('Python venv/LibreLane installation failed; inspect pip output above.')
        return 5
    # Both setup and PICADS WSL runner address this venv directly; no system
    # symlinks or additional sudo operations are required.
    print('\n[5/5] Running official Dockerized LibreLane smoke test...')
    smoke = ('"$HOME/.local/share/picads-librelane/venv/bin/python" '
             '-m librelane --dockerized --smoke-test')
    success = wsl_command(distro, smoke, timeout=3600, runner=runner)
    if not worked(success):
        print('LibreLane smoke test FAILED. PICADS has NOT marked backend ready.')
        return 6
    RECEIPT.write_text(json.dumps({'status': 'PASS', 'distro': distro,
        'docker_server_version': docker_status['server'],
        'smoke_test': 'python -m librelane --dockerized --smoke-test',
        'checked_at_utc': datetime.now(timezone.utc).isoformat()}, indent=2) + '\n',
        encoding='utf-8')
    MARKER.write_text('LIBRELANE_SMOKE_TEST_PASS\n', encoding='ascii')
    print('LibreLane smoke-test PASS. Backend setup is complete.')
    print('PICADS project needs tools.execution: wsl and tools.wsl_distribution:', distro)
    print('Physical flow still requires a compatible PDK and correct WSL build integration.')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description='PICADS opt-in LibreLane setup for Windows')
    p.add_argument('--probe-only', action='store_true', help='Only inspect existing WSL/Docker; install nothing')
    args = p.parse_args(argv)
    try:
        return setup(probe_only=args.probe_only)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('SETUP ERROR:', exc)
        return 10


if __name__ == '__main__':
    sys.exit(main())
