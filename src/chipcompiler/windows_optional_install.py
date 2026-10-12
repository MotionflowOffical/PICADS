"""Windows-specific, opt-in installation paths for non-portable applications.

KiCad: use the verified WinGet catalogue, requesting a managed directory.
LibreLane: launch a *visible* staged WSL2/Docker setup terminal. WSL can
require an administrator, Linux first-run account setup, and a reboot; no
backend is marked functional until a smoke test genuinely succeeds.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


class GuidedSetupError(RuntimeError):
    pass


def _require_windows():
    if sys.platform != 'win32':
        raise GuidedSetupError('Windows setup is only available on Windows 10/11')


def _find_kicad_binaries(root: Path) -> dict[str, Path]:
    """Bounded search for KiCad's known Windows folder layouts.

    Search only managed and known KiCad directories, never whole drives.
    KiCad's installer can create KiCad/<version>/bin or a nested wrapper.
    """
    dirs = [root / 'kicad' / 'application', root / 'kicad']
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(env):
            base = Path(os.environ[env])
            dirs.append(base / 'KiCad')
            if env == 'LOCALAPPDATA':
                dirs.append(base / 'Programs' / 'KiCad')
    found: dict[str, Path] = {}
    for base in dirs:
        if not base.is_dir():
            continue
        queue = [(base, 0)]
        while queue:
            folder, depth = queue.pop(0)
            for tool, file in (('kicad', 'kicad.exe'), ('kicad-cli', 'kicad-cli.exe')):
                exe = folder / file
                if exe.is_file():
                    found[tool] = exe
            if len(found) == 2:
                return found
            if depth < 3:
                try:
                    queue.extend((child, depth + 1) for child in folder.iterdir() if child.is_dir())
                except OSError:
                    continue
    return found


def install_kicad(root: Path, progress: Callable[[str], None], *, run=None,
                  which=None) -> dict:
    """Ask WinGet to install KiCad, without bypassing signing or UAC.

    --location is best-effort with WinGet; the upstream installer can ignore it.
    Register real binaries wherever the trusted installer placed them.
    """
    _require_windows()
    run = run or subprocess.run
    which = which or shutil.which
    winget = which('winget')
    if not winget:
        raise GuidedSetupError('Windows Package Manager (winget) is missing. Install Microsoft App Installer, or use Choose App/Folder for KiCad.')
    dest = root / 'kicad'
    dest.mkdir(parents=True, exist_ok=True)
    command = [winget, 'install', '--id', 'KiCad.KiCad', '--exact', '--source', 'winget',
               '--location', str((dest / 'application').resolve()), '--silent',
               '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity']
    progress('Running official WinGet package KiCad.KiCad; installation may request Windows administrator approval.')
    progress('Preferred directory: ' + str(dest / 'application') + ' (WinGet location is installer-dependent).')
    try:
        response = run(command, capture_output=True, text=True, errors='replace', timeout=1800,
                       check=False)
    except subprocess.TimeoutExpired as exc:
        raise GuidedSetupError('KiCad installer timed out; check Windows installer prompts and WinGet logs.') from exc
    except OSError as exc:
        raise GuidedSetupError('Could not start WinGet: ' + str(exc)) from exc
    out = ((response.stdout or '') + '\n' + (response.stderr or ''))[-12000:]
    (dest / 'winget_install.log').write_text(out, encoding='utf-8')
    progress('WinGet exit code: ' + str(response.returncode))
    if response.returncode:
        raise GuidedSetupError('WinGet returned ' + str(response.returncode) + '. Review dependencies/kicad/winget_install.log; you can also install KiCad and select its folder manually.')
    files = _find_kicad_binaries(root)
    if not files:
        progress('WinGet returned success, but KiCad executables were not found in the managed or usual installation folders.')
        return {'status': 'SETUP_REQUIRED', 'package': 'kicad',
                'message': 'Select KiCad with Choose Folder after locating its installation.',
                'install_log': str(dest / 'winget_install.log')}
    from .dependencies import register_tool
    registered = {}
    for name, path in files.items():
        registered[name] = register_tool(name, path, 'app')['path']
    receipt = {'package': 'kicad', 'method': 'winget', 'package_id': 'KiCad.KiCad',
               'requested_path': str(dest / 'application'), 'registered_tools': registered,
               'note': 'KiCad is optional PCB software, not IC place-and-route or DRC/LVS.'}
    (dest / 'picads_install_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    progress('KiCad registered: ' + ', '.join(registered))
    return {'status': 'INSTALLED' if len(registered) == 2 else 'PARTIAL',
            'package': 'kicad', 'tools': registered, 'directory': str(dest),
            'install_log': str(dest / 'winget_install.log')}


# Standalone console by design: WSL distro setup and sudo can request input,
# while Docker Desktop may require first-run configuration and a reboot.
# The installer must never incorrectly report a background setup as success.
LIBRELANE_SETUP = r'''@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "READY=%~dp0backend_smoke_passed.txt"
if exist "%READY%" del "%READY%"
echo.
echo PICADS - Optional LibreLane backend setup for Windows
 echo This installs/configures WSL2 Ubuntu and Docker Desktop, then LibreLane inside Ubuntu.
echo Administrator approval, a restart, Ubuntu first-run setup, or Docker WSL integration may be needed.
echo PICADS editor, DLS and native RTL synthesis do NOT require this backend.
echo.
echo [1/5] Checking Windows Subsystem for Linux...
where wsl.exe >nul 2>nul
if errorlevel 1 goto :needwsl
wsl.exe --list --quiet >nul 2>nul
if errorlevel 1 goto :needwsl
wsl.exe --list --quiet | findstr /i "Ubuntu" >nul
if errorlevel 1 goto :needwsl
goto :docker
:needwsl
echo Ubuntu for WSL2 was not found. Requesting official Microsoft installation.
wsl.exe --install -d Ubuntu
if errorlevel 1 goto :failed
echo If a restart or initial Ubuntu username/password is required, complete it and rerun this file.
goto :pending
:docker
echo [2/5] Checking Docker Desktop...
where docker.exe >nul 2>nul
if not errorlevel 1 goto :dockercheck
where winget.exe >nul 2>nul
if errorlevel 1 (
 echo Install Docker Desktop from https://docs.docker.com/desktop/setup/install/windows-install/
 goto :pending
)
echo Installing Docker Desktop using the official WinGet package...
winget install --id Docker.DockerDesktop --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :pending
echo Start Docker Desktop, accept its first-run configuration, and enable WSL2 integration for Ubuntu.
goto :pending
:dockercheck
echo [3/5] Checking the Docker daemon and WSL2 integration...
docker info >nul 2>nul
if errorlevel 1 (
 echo Start Docker Desktop and enable the WSL2 engine. Then rerun this file.
 goto :pending
)
wsl.exe -d Ubuntu --exec bash -lc "docker info >/dev/null 2>&1"
if errorlevel 1 (
 echo Enable Docker Desktop Settings - Resources - WSL Integration - Ubuntu, then rerun.
 goto :pending
)
:python
echo [4/5] Installing LibreLane into an Ubuntu virtual environment...
echo Ubuntu may prompt for your sudo password.
wsl.exe -d Ubuntu --exec bash -lc "sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip python3-tk curl make git build-essential"
if errorlevel 1 goto :failed
wsl.exe -d Ubuntu --exec bash -lc "python3 -m venv \$HOME/.local/share/picads-librelane/venv && \$HOME/.local/share/picads-librelane/venv/bin/python -m pip install --upgrade pip librelane"
if errorlevel 1 goto :failed
echo [5/5] Running the official dockerized LibreLane smoke test...
wsl.exe -d Ubuntu --exec bash -lc "sudo ln -sfn \$HOME/.local/share/picads-librelane/venv/bin/librelane /usr/local/bin/librelane"
if errorlevel 1 goto :failed
wsl.exe -d Ubuntu --exec bash -lc "command -v librelane && librelane --dockerized --smoke-test"
if errorlevel 1 goto :failed
echo LIBRELANE_SMOKE_TEST_PASS>"%READY%"
echo LibreLane WSL2/Docker smoke test PASSED.
echo For PICADS physical runs, set tools.execution: wsl and tools.wsl_distribution: Ubuntu in chip.yaml.
echo The WSL environment must have the librelane command on its PATH (see setup guide).
goto :end
:pending
echo Setup is incomplete. Complete the steps above, then launch this file again.
goto :end
:failed
echo A required step failed. Check the displayed error and rerun after correcting it.
:end
echo.
pause
'''

# The console bootstrap uses the venv's Python explicitly. Installing a
# registered *Windows* librelane.exe would be incorrect.

def stage_librelane(root: Path, progress: Callable[[str], None], *, launch=True,
                   popen=None) -> dict:
    _require_windows()
    folder = root / 'librelane'
    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / 'SETUP_LIBRELANE_WINDOWS.bat'
    launcher.write_text(LIBRELANE_SETUP.replace('\\$HOME', '$HOME'), encoding='utf-8', newline='\r\n')
    progress('Prepared guided Windows WSL2/Docker setup at ' + str(launcher))
    if launch:
        popen = popen or subprocess.Popen
        try:
            # Separate interactive console is intentional; no silent admin or
            # Linux password prompts and no GUI freeze during first-run setup.
            popen([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(launcher)],
                  cwd=folder, creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        except OSError as exc:
            raise GuidedSetupError('Setup script saved, but could not open the Windows console: ' + str(exc)) from exc
        progress('LibreLane setup console opened. Complete its prompts; the GUI does not wait for or claim success.')
    return {'status': 'SETUP_STARTED' if launch else 'SETUP_REQUIRED',
            'package': 'librelane', 'directory': str(folder), 'launcher': str(launcher),
            'message': 'WSL2, Docker Desktop and Ubuntu initialization may need approval/restart. Rerun the launcher after reboot; smoke-test evidence is required.'}
