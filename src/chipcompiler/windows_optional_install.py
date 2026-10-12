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
            for tool, file in (('kicad', 'kicad.exe'), ('kicad-cli', 'kicad-cli.exe'), ('pcbnew', 'pcbnew.exe')):
                exe = folder / file
                if exe.is_file():
                    found[tool] = exe
            if len(found) == 3:
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
    # Repair an existing KiCad install first. This registers pcbnew.exe for
    # users who already installed KiCad with PICADS 0.16.1/0.16.2, without
    # downloading or invoking WinGet a second time.
    existing = _find_kicad_binaries(root)
    if len(existing) == 3:
        from .dependencies import register_tool
        registered = {name: register_tool(name, path, 'app')['path'] for name, path in existing.items()}
        dest = root / 'kicad'
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'picads_install_receipt.json').write_text(json.dumps({
            'package': 'kicad', 'method': 'found-existing', 'registered_tools': registered,
        }, indent=2) + '\n', encoding='utf-8')
        progress('Existing KiCad found. Registered kicad, kicad-cli and pcbnew; no download')
        return {'status': 'INSTALLED', 'package': 'kicad', 'tools': registered,
                'directory': str(dest), 'repaired': True}
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
    return {'status': 'INSTALLED' if len(registered) == 3 else 'PARTIAL',
            'package': 'kicad', 'tools': registered, 'directory': str(dest),
            'install_log': str(dest / 'winget_install.log')}


# The script is staged as a local file only when the user selects LibreLane.
# Docker's official EXE supports --user; do not use WinGet machine-wide install.
# No ACL resets, system-directory deletion, Docker-data cleanup or privilege bypass.
DOCKER_PER_USER_INSTALL = r'''param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Write-Host 'PICADS Docker Desktop repair: official PER-USER installation, WSL2 backend'
Write-Host 'Existing WSL, Docker data and C:\ProgramData security settings will not be modified.'

function Test-DockerInstallerSignature([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $Path
        if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate) { return $false }
        if ($signature.SignerCertificate.Subject -notmatch '(?i)Docker') { return $false }
        return $true
    } catch { return $false }
}

try {
    $cache = Join-Path $InstallRoot 'docker-installer-cache'
    New-Item -Path $cache -ItemType Directory -Force | Out-Null
    $installer = Join-Path $cache 'Docker Desktop Installer.exe'
    $verified = $null
    if (Test-DockerInstallerSignature $installer) {
        $verified = $installer
        Write-Host 'Reusing signed installer from PICADS cache.'
    }
    if (-not $verified) {
        # Previous WinGet attempts may have already downloaded ~600 MB here.
        # Only two levels of this known directory are searched; no arbitrary
        # executables are trusted merely because they have the right name.
        $prior = Join-Path $env:LOCALAPPDATA 'Temp\DockerDesktopInstallers'
        if (Test-Path -LiteralPath $prior -PathType Container) {
            $folders = @(Get-ChildItem -LiteralPath $prior -Directory -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 30)
            foreach ($folder in $folders) {
                $candidate = Join-Path $folder.FullName 'Docker Desktop Installer.exe'
                if (Test-DockerInstallerSignature $candidate) {
                    $verified = $candidate
                    Write-Host 'Reusing Windows-signed installer cached from previous attempt.'
                    break
                }
            }
        }
    }
    if (-not $verified) {
        $url = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
        $partial = Join-Path $cache 'Docker Desktop Installer.download'
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        Write-Host 'Downloading Docker Desktop from the official Docker website...'
        Invoke-WebRequest -Uri $url -OutFile $partial -UseBasicParsing
        if (-not (Test-DockerInstallerSignature $partial)) {
            throw 'Official download failed Windows Authenticode validation. Nothing was executed.'
        }
        Move-Item -LiteralPath $partial -Destination $installer -Force
        $verified = $installer
    }
    if (-not (Test-DockerInstallerSignature $verified)) {
        throw 'Docker installer signature verification failed. Nothing was executed.'
    }
    Write-Host ('Signed installer: ' + $verified)
    Write-Host ('SHA-256: ' + (Get-FileHash -LiteralPath $verified -Algorithm SHA256).Hash)
    Write-Host 'Starting per-user installer (no machine-wide elevation requested)...'
    $proc = Start-Process -FilePath $verified -ArgumentList @('install', '--user', '--backend=wsl-2') -Wait -PassThru
    if ($null -eq $proc -or $proc.ExitCode -ne 0) {
        $code = if ($null -eq $proc) { 'unknown' } else { $proc.ExitCode }
        throw ('Docker installer exited with code ' + $code + '. Check Docker installation logs.')
    }
    Write-Host 'Docker Desktop per-user installation finished.'
    Write-Host 'Start Docker Desktop and enable Settings > Resources > WSL Integration.'
    exit 0
} catch {
    Write-Host ('Docker per-user setup FAILED: ' + $_.Exception.Message)
    Write-Host 'If a previous all-users install was interrupted, reboot and retry.'
    Write-Host 'Do not manually change system-folder owners or delete Docker data.'
    Write-Host 'Official instructions: https://docs.docker.com/desktop/setup/install/windows-install/'
    exit 1
}
'''

# Standalone console by design: WSL distro setup and sudo can request input,
# while Docker Desktop may require first-run configuration and a reboot.
# The installer must never incorrectly report a background setup as success.
LIBRELANE_SETUP = r'''@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "READY=%~dp0backend_smoke_passed.txt"
set "DISTRO_FILE=%~dp0wsl_distribution.txt"
set "PICADS_PYTHON=__PICADS_PYTHON__"
echo.
echo PICADS - Optional LibreLane backend setup for Windows
echo This uses an existing WSL2 Linux distribution when one is installed.
echo Only if NONE is installed will PICADS request an Ubuntu installation.
echo Docker Desktop integration, Linux sudo, or a restart may still be required.
echo.
echo [1/5] Discovering installed WSL2 distributions...
where wsl.exe >nul 2>nul
if errorlevel 1 (
 echo WSL executable is not available. Enable WSL first, then rerun this launcher.
 goto :pending
)
if not exist "%PICADS_PYTHON%" (
 echo PICADS Python executable is missing: %PICADS_PYTHON%
 echo Launch LibreLane setup again from PICADS Settings to refresh this path.
 goto :pending
)
"%PICADS_PYTHON%" "%~dp0DISCOVER_WSL_DISTRO.py" "%DISTRO_FILE%"
set "DISCOVERY_RC=%ERRORLEVEL%"
if "%DISCOVERY_RC%"=="0" goto :distro_found
if "%DISCOVERY_RC%"=="2" goto :install_ubuntu
rem Code 3 means Ubuntu/Debian already exists but is not initialized.
rem Code 4 means WSL discovery itself failed. NEVER try a duplicate install.
goto :pending
:install_ubuntu
echo No installed interactive Linux distribution was found.
echo Requesting Ubuntu from Microsoft. This may need a restart.
wsl.exe --install -d Ubuntu
if errorlevel 1 goto :pending
echo Launch Ubuntu once to initialize your user account, then rerun this file.
goto :pending
:distro_found
for /f "usebackq delims=" %%G in ("%DISTRO_FILE%") do set "PICADS_DISTRO=%%G"
if not defined PICADS_DISTRO goto :pending
echo Reusing WSL distribution: %PICADS_DISTRO%
wsl.exe --distribution "%PICADS_DISTRO%" --exec sh -c "printf 'PICADS_WSL_READY'"
if errorlevel 1 goto :pending
:docker
echo [2/5] Checking Docker Desktop...
rem Docker Desktop 4.8x+ offers an official per-user install. WinGet's
rem machine-wide installer can fail when ProgramData\DockerDesktop has the
rem wrong owner. PICADS must not change system ACLs or delete Docker data.
where docker.exe >nul 2>nul
if not errorlevel 1 goto :dockercheck
rem The per-user installer does not necessarily update this cmd process PATH.
if exist "%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe" (
 set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%PATH%"
 goto :dockercheck
)
if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" (
 set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
 goto :dockercheck
)
if exist "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe" goto :docker_installed
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" goto :docker_installed
if not exist "%~dp0INSTALL_DOCKER_PER_USER.ps1" (
 echo Per-user Docker setup helper is missing. Reinstall the PICADS hotfix.
 goto :pending
)
echo Docker Desktop is not detected. Starting the official per-user WSL2 installer.
echo PICADS will not change ownership or delete C:\ProgramData\DockerDesktop.
where powershell.exe >nul 2>nul
if errorlevel 1 (
 echo Windows PowerShell is not available to download/verify the official installer.
 goto :pending
)
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0INSTALL_DOCKER_PER_USER.ps1" -InstallRoot "%CD%"
if errorlevel 1 goto :pending
:docker_installed
echo Start Docker Desktop and enable WSL2 integration for %PICADS_DISTRO%.
echo Then rerun this setup from PICADS. Installation alone does not prove Docker works.
goto :pending
:dockercheck
echo [3/5] Checking Docker daemon and WSL integration...
docker info >nul 2>nul
if errorlevel 1 (
 echo Start Docker Desktop, then rerun.
 goto :pending
)
wsl.exe --distribution "%PICADS_DISTRO%" --exec bash -lc "docker info >/dev/null 2>&1"
if errorlevel 1 (
 echo Enable Docker Desktop - Settings - Resources - WSL Integration for %PICADS_DISTRO%.
 goto :pending
)
:python
echo [4/5] Installing LibreLane into a virtual environment in %PICADS_DISTRO%...
wsl.exe --distribution "%PICADS_DISTRO%" --exec bash -lc "sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip python3-tk curl make git build-essential"
if errorlevel 1 goto :failed
wsl.exe --distribution "%PICADS_DISTRO%" --exec bash -lc "python3 -m venv $HOME/.local/share/picads-librelane/venv && $HOME/.local/share/picads-librelane/venv/bin/python -m pip install --upgrade pip librelane"
if errorlevel 1 goto :failed
echo [5/5] Running LibreLane Docker smoke test...
wsl.exe --distribution "%PICADS_DISTRO%" --exec bash -lc "sudo ln -sfn $HOME/.local/share/picads-librelane/venv/bin/librelane /usr/local/bin/librelane"
if errorlevel 1 goto :failed
wsl.exe --distribution "%PICADS_DISTRO%" --exec bash -lc "command -v librelane && librelane --dockerized --smoke-test"
if errorlevel 1 goto :failed
echo LIBRELANE_SMOKE_TEST_PASS>"%READY%"
echo LibreLane smoke test PASSED in WSL distribution %PICADS_DISTRO%.
echo Set tools.execution: wsl and tools.wsl_distribution: %PICADS_DISTRO% in PICADS chip.yaml.
goto :end
:pending
echo Setup incomplete. Resolve the message above and rerun this launcher.
goto :end
:failed
echo LibreLane setup failed. Inspect the first error above; no successful smoke test was recorded.
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
    helper = folder / 'DISCOVER_WSL_DISTRO.py'
    helper.write_text(Path(__file__).with_name('wsl_backend_discovery.py').read_text(encoding='utf-8'),
                      encoding='utf-8')
    docker_helper = folder / 'INSTALL_DOCKER_PER_USER.ps1'
    docker_helper.write_text(DOCKER_PER_USER_INSTALL, encoding='utf-8-sig')
    # Use the same Windows interpreter that is currently running PICADS.
    # The distribution discovery runs before any Linux/Docker installation.
    launch_script = LIBRELANE_SETUP.replace('__PICADS_PYTHON__', str(Path(sys.executable).resolve()))
    launcher.write_text(launch_script, encoding='utf-8', newline='\r\n')
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
            'package': 'librelane', 'directory': str(folder), 'launcher': str(launcher), 'discovery_helper': str(helper), 'docker_installer_helper': str(docker_helper),
            'message': 'WSL2, Docker Desktop and Ubuntu initialization may need approval/restart. Rerun the launcher after reboot; smoke-test evidence is required.'}


# MSYS2 is the supported native Windows toolchain for GCC, G++ and Verilator.
# Keep install and status distinct: WinGet success is NOT proof that pacman
# installed its packages or that a Verilator Perl wrapper runs correctly.
_MSYS_PACKAGES = (
    'mingw-w64-ucrt-x86_64-gcc',
    'mingw-w64-ucrt-x86_64-verilator',
    'mingw-w64-ucrt-x86_64-make',
    'make',
    'perl',
)


def _msys_locations(root: Path) -> list[Path]:
    install = root / 'msys2-toolchain' / 'application'
    # MSYS2 has historically refused install locations containing spaces.
    # Preserve PICADS's managed receipt in dependencies/ even when WinGet
    # needs a simple no-space installation path.
    paths = [install, Path(os.environ.get('SystemDrive', 'C:') + '/msys64')]
    if os.environ.get('MSYS2_ROOT'):
        paths.insert(0, Path(os.environ['MSYS2_ROOT']))
    if os.environ.get('LOCALAPPDATA'):
        paths.append(Path(os.environ['LOCALAPPDATA']) / 'msys64')
    return paths


def _msys_install_path(root: Path) -> Path:
    preferred = root / 'msys2-toolchain' / 'application'
    if not any(char.isspace() for char in str(preferred)):
        return preferred
    return Path(os.environ.get('SystemDrive', 'C:') + '/msys64')


def _msys_ready(path: Path) -> bool:
    return all((path / sub).is_file() for sub in (
        'usr/bin/bash.exe', 'usr/bin/pacman.exe',
        'ucrt64/bin/gcc.exe', 'ucrt64/bin/g++.exe',
        'ucrt64/bin/verilator_bin.exe', 'usr/bin/perl.exe',
    ))


def _msys_wrapper(root: Path, binary_root: Path) -> Path:
    """Create a CMD entry point to the upstream Perl Verilator frontend.

    The Verilator package ships a Perl script called `verilator` and a native
    `verilator_bin.exe`. Registering the latter as `verilator` alone is wrong:
    the Perl frontend assembles the proper command and environment.
    """
    import re
    value = str(binary_root.resolve())
    if any(ch in value for ch in '\r\n%"!'):
        raise GuidedSetupError('Unsupported characters in MSYS2 install directory')
    target = root / 'msys2-toolchain' / 'verilator.cmd'
    target.parent.mkdir(parents=True, exist_ok=True)
    script = ('@echo off\r\n'
              'setlocal DisableDelayedExpansion\r\n'
              f'set "PATH={value}\\ucrt64\\bin;{value}\\usr\\bin;%PATH%"\r\n'
              'set "MSYSTEM=UCRT64"\r\n'
              f'"{value}\\usr\\bin\\perl.exe" "{value}\\ucrt64\\bin\\verilator" %*\r\n'
              'exit /b %ERRORLEVEL%\r\n')
    target.write_bytes(script.encode('utf-8'))
    return target


def install_msys2_toolchain(root: Path, progress: Callable[[str], None], *,
                            run=None, which=None) -> dict:
    """Install native GCC/G++ and Verilator via WinGet+official MSYS2 pacman.

    The environment is real Windows; no WSL/Docker dependency. pacman is run
    with fixed package identifiers, never commands obtained from downloads.
    When a location already has the requested binaries, this operation only
    re-registers the executables, avoiding unnecessary network traffic.
    """
    _require_windows()
    run = run or subprocess.run
    which = which or shutil.which
    managed = root / 'msys2-toolchain'
    previously_managed = (managed/'picads_install_receipt.json').is_file()
    managed.mkdir(parents=True, exist_ok=True)
    selected = next((candidate for candidate in _msys_locations(root)
                     if _msys_ready(candidate)), None)
    if selected is not None:
        progress('Existing MSYS2 UCRT64 GCC/G++/Verilator located: '+str(selected))
    else:
        selected = next((candidate for candidate in _msys_locations(root)
                         if (candidate/'usr/bin/pacman.exe').is_file()), None)
        if selected is None:
            winget = which('winget')
            if not winget:
                raise GuidedSetupError('MSYS2 installation requires WinGet. Install Microsoft App Installer first.')
            selected = _msys_install_path(root)
            if any(char.isspace() for char in str(root)):
                progress('MSYS2 disallows space-containing install paths. Using '+str(selected)+
                         '; PICADS keeps its receipt under dependencies/msys2-toolchain.')
            command = [winget, 'install', '--id', 'MSYS2.MSYS2', '--exact', '--source', 'winget',
                       '--location', str(selected), '--silent',
                       '--accept-package-agreements', '--accept-source-agreements',
                       '--disable-interactivity']
            progress('Installing official MSYS2 via WinGet (one-time operation).')
            try:
                result = run(command, capture_output=True, text=True, errors='replace', timeout=1800, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GuidedSetupError('MSYS2 WinGet installation could not complete: '+str(exc)) from exc
            (managed/'winget_install.log').write_text((result.stdout or '')+'\n'+(result.stderr or ''),encoding='utf-8')
            if result.returncode:
                raise GuidedSetupError(f'MSYS2 WinGet exited {result.returncode}; see {managed / "winget_install.log"}')
        if not (selected/'usr/bin/bash.exe').is_file():
            return {'status':'SETUP_REQUIRED','package':'msys2-toolchain','directory':str(selected),
                    'message':'WinGet completed, but MSYS2 bash.exe was not found; inspect installation and retry.'}
        env = os.environ.copy()
        env['MSYSTEM']='UCRT64'; env['CHERE_INVOKING']='1'
        env['PATH']=str(selected/'usr/bin')+os.pathsep+env.get('PATH','')
        # A full update may need a second invocation. Never run arbitrary
        # package installer scripts or ignore a failed pacman exit status.
        for phase, args in (
            ('base upgrade', ['-Syu','--noconfirm']),
            ('toolchain packages', ['-S','--needed','--noconfirm',*_MSYS_PACKAGES]),
        ):
            progress('MSYS2 pacman: '+phase)
            try:
                result = run([str(selected/'usr/bin/pacman.exe'), *args],
                             capture_output=True, text=True, errors='replace',
                             timeout=1800, check=False, env=env, cwd=selected)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GuidedSetupError('MSYS2 '+phase+' failed to launch: '+str(exc)) from exc
            (managed / ('pacman_'+phase.replace(' ','_')+'.log')).write_text(
                (result.stdout or '')+'\n'+(result.stderr or ''),encoding='utf-8')
            if result.returncode:
                return {'status':'SETUP_REQUIRED','package':'msys2-toolchain',
                        'directory':str(selected), 'message': f'pacman {phase} returned {result.returncode}; '
                        'review dependencies/msys2-toolchain logs, then select install again.'}
    if not _msys_ready(selected):
        return {'status':'SETUP_REQUIRED','package':'msys2-toolchain', 'directory':str(selected),
                'message':'Expected native compilers, Verilator binary or Perl frontend missing; retry package installation.'}
    if not (selected/'ucrt64/bin/verilator').is_file():
        return {'status':'SETUP_REQUIRED','package':'msys2-toolchain','directory':str(selected),
                'message':'Verilator Perl frontend missing; the native binary alone is insufficient.'}
    from .dependencies import register_tool
    wrappers = {'gcc': selected/'ucrt64/bin/gcc.exe',
                'g++': selected/'ucrt64/bin/g++.exe',
                'verilator': _msys_wrapper(root,selected)}
    registered = {key: register_tool(key, file, 'app')['path'] for key,file in wrappers.items()}
    receipt = {'package':'msys2-toolchain','method':'winget+pacman',
               'upstream':'https://www.msys2.org/', 'root':str(selected),
               'registered_tools':registered, 'packages':list(_MSYS_PACKAGES),
               'note':'Native UCRT64 programs. Verilator uses the upstream Perl frontend via a Windows CMD wrapper.'}
    (managed/'picads_install_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    progress('Native GCC, G++ and Verilator registered from MSYS2 UCRT64.')
    return {'status':'INSTALLED','package':'msys2-toolchain','directory':str(selected),
            'tools':registered, 'repaired':previously_managed}
