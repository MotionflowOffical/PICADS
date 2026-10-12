"""Read-only discovery of the *WSL* LibreLane backend, distinct from Windows tools.

A recorded successful smoke test is historical evidence, not proof that today's
Docker daemon or WSL distribution is running.  Live checks never install or
alter software.  They use argv-based wsl.exe calls and the PICADS-managed venv.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


def backend_status(distribution: str | None = None, *, root: Path | None = None,
                   live: bool = False, run=None, which=None) -> dict:
    if root is None:
        from .windows_installer import dependency_root
        root = dependency_root() / 'librelane'
    root = Path(root)
    marker = root / 'backend_smoke_passed.txt'
    receipt = root / 'backend_smoke_receipt.json'
    distro_file = root / 'wsl_distribution.txt'
    data = {}
    if receipt.is_file():
        try:
            data = json.loads(receipt.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
    saved_distro = data.get('distro')
    if not isinstance(saved_distro, str) or not saved_distro.strip():
        try:
            saved_distro = distro_file.read_text(encoding='utf-8').strip()
        except OSError:
            saved_distro = None
    distro = distribution or saved_distro
    recorded = (marker.is_file() and
                marker.read_text(encoding='ascii', errors='replace').strip() == 'LIBRELANE_SMOKE_TEST_PASS' and
                data.get('status') == 'PASS' and data.get('distro') == distro)
    output = {'status': 'SMOKE_PASSED' if recorded else 'NOT_VERIFIED',
              'available': False, 'distribution': distro, 'recorded_smoke_pass': recorded,
              'receipt': str(receipt) if receipt.is_file() else None,
              'detail': ('Successful LibreLane smoke test recorded; runtime not checked.' if recorded else
                         'No matching successful LibreLane smoke-test receipt for selected distribution.')}
    if not live:
        return output
    if not distro:
        return {**output, 'status': 'NOT_CONFIGURED', 'detail': 'No WSL distribution selected or recorded.'}
    which = shutil.which if which is None else which
    wsl = which('wsl.exe') or which('wsl')
    if not wsl:
        return {**output, 'status': 'UNAVAILABLE', 'detail': 'wsl.exe not found by PICADS process.'}
    checks = {
        'yosys': 'command -v yosys >/dev/null && yosys -V >/dev/null',
        'docker': 'docker info --format "{{.ServerVersion}}" >/dev/null',
        'librelane': ('test -x "$HOME/.local/share/picads-librelane/venv/bin/python" && '
                      '"$HOME/.local/share/picads-librelane/venv/bin/python" -c "import librelane"'),
    }
    run = subprocess.run if run is None else run
    results = {}
    for name, shell in checks.items():
        args = [wsl, '--distribution', distro, '--exec', 'bash', '-lc', shell]
        try:
            done = run(args, check=False, capture_output=True, text=True, timeout=35)
            passed = done.returncode == 0
            detail = ((done.stderr or done.stdout or '').strip())[-600:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            passed, detail = False, str(exc)
        results[name] = {'status': 'PASS' if passed else 'UNAVAILABLE', 'detail': detail}
    good = all(check['status'] == 'PASS' for check in results.values())
    return {**output, 'status': 'READY' if good else 'UNAVAILABLE',
            'available': good, 'checks': results,
            'detail': ('WSL Yosys, Docker and PICADS LibreLane Python environment are reachable.'
                       if good else 'One or more required tools are not reachable inside the selected WSL distribution.')}


def probe_wsl_commands(distribution: str | None, commands: list[str], *, run=None, which=None) -> dict[str, bool]:
    """Inspect extra WSL CLI prerequisites (Icarus), without touching Windows registrations."""
    which = shutil.which if which is None else which
    wsl = which('wsl.exe') or which('wsl')
    if not distribution or not wsl:
        return {command: False for command in commands}
    run = subprocess.run if run is None else run
    results = {}
    for command in commands:
        try:
            result = run([wsl, '--distribution', distribution, '--exec',
                          'sh', '-c', 'command -v "$1" >/dev/null', 'picads', command],
                         check=False, capture_output=True, timeout=25)
            results[command] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            results[command] = False
    return results
