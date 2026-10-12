"""Audited, opt-in disk reclamation for PICADS-managed dependency files.

Safety boundaries:
- No deletion is performed during discovery, ordinary CLI invocation, or GUI startup.
- All filesystem removal targets have fixed, package-specific names, under the
  chosen PICADS dependency directory; no user-supplied deletion paths or globs.
- Windows/WinGet installs, WSL distributions, Docker images and volumes, PDKs,
  projects, and third-party caches are never deleted by this module.
- LibreLane removal is limited to the PICADS-created Linux virtualenv, inside
  the distribution named in its successful installation receipt.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Callable

from .windows_installer import APP_ROOT, PACKAGES, dependency_root
from .dependencies import read_settings, unregister_tool

_MIN_STAGING_AGE = 24 * 60 * 60
_PORTABLE = ('oss-cad-suite', 'klayout')
_WSL_DIRECTORY = '$HOME/.local/share/picads-librelane/venv'


class StorageSafetyError(ValueError):
    """Unsafe target or unapproved/changed deletion plan."""


def readable_bytes(size: int | None) -> str:
    if size is None:
        return 'unknown'
    if size < 1024:
        return f'{size} B'
    for unit, scale in (('TiB', 1024**4), ('GiB', 1024**3),
                        ('MiB', 1024**2), ('KiB', 1024)):
        if size >= scale:
            return f'{size / scale:.1f} {unit}'
    return f'{size} B'


def _has_symlink_component(root: Path, target: Path) -> bool:
    """Do not select symlinked components even if they point back inside root."""
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        return True
    current = root
    if current.is_symlink():
        return True
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _checked_target(root: Path, target: Path) -> Path:
    root, target = Path(os.path.abspath(root)), Path(os.path.abspath(target))
    # Refuse risky roots, including drive roots and a user's home folder.
    if root == Path(root.anchor) or root == Path.home() or root.parent == root:
        raise StorageSafetyError('The dependency root is too broad for automatic removal')
    if target == root or not target.is_relative_to(root):
        raise StorageSafetyError('Refusing to delete outside the PICADS dependency root')
    if _has_symlink_component(root, target):
        raise StorageSafetyError('Refusing a symlinked target or parent')
    return target


def _bytes(path: Path) -> int:
    """Conservative allocated-file size estimate; never follows symlinks."""
    size = 0
    todo = [path]
    while todo:
        item = todo.pop()
        try:
            info = item.lstat()
        except (FileNotFoundError, PermissionError):
            continue
        if stat.S_ISLNK(info.st_mode):
            continue
        if stat.S_ISREG(info.st_mode):
            size += info.st_size
        elif stat.S_ISDIR(info.st_mode):
            try:
                todo.extend(item.iterdir())
            except OSError:
                continue
    return size


def _receipt(directory: Path, package: str) -> dict | None:
    if directory.is_symlink():
        return None
    file = directory / 'picads_install_receipt.json'
    if file.is_symlink() or not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and data.get('package') == package else None
    except (OSError, ValueError):
        return None


def _wsl_receipt(root: Path) -> dict | None:
    if (root/'librelane').is_symlink():
        return None
    file = root / 'librelane' / 'backend_smoke_receipt.json'
    if file.is_symlink() or not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
        distro = data.get('distro')
        if (data.get('status') == 'PASS' and isinstance(distro, str)
                and distro.strip() == distro and distro
                and not any(ch in distro for ch in '\r\n\0')):
            return data
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None


def _wsl_distribution(root: Path) -> str | None:
    """Persisted distro choice survives removing the PICADS WSL virtualenv."""
    marker = root / 'librelane' / 'wsl_distribution.txt'
    if (root/'librelane').is_symlink() or marker.is_symlink() or not marker.is_file():
        return None
    try:
        name = marker.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return name if name and not any(c in name for c in '\r\n\0') else None


def _entry(key: str, label: str, category: str, location: str, size: int | None,
           *, detail: str) -> dict:
    return dict(id=key, name=label, category=category, path=location,
                bytes=size, size=readable_bytes(size), detail=detail)


def _wsl_venv_size(distro: str, *, run=None) -> int | None:
    run = run or subprocess.run
    cmd = ('if [ -d "$HOME/.local/share/picads-librelane/venv" ]; then '
           'du -sk -- "$HOME/.local/share/picads-librelane/venv" | cut -f1; '
           'else echo 0; fi')
    try:
        proc = run(['wsl.exe', '--distribution', distro, '--exec', 'sh', '-c', cmd],
                   capture_output=True, text=True, timeout=25, check=False)
        if proc.returncode == 0:
            return int(proc.stdout.strip()) * 1024
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        pass
    return None


def _wsl_directory_size(distro: str, relative_name: str, *, run=None) -> int | None:
    """Return zero for absent managed caches; never follow symlinked paths."""
    if relative_name != '.cache/picads-librelane-pip':
        raise StorageSafetyError('Unknown managed WSL cache')
    run = run or subprocess.run
    shell = ('base="$HOME/.cache/picads-librelane-pip"; '
             'if [ -d "$base" ] && [ ! -L "$base" ]; then '
             'du -sk -- "$base" | cut -f1; else echo 0; fi')
    try:
        done = run(['wsl.exe','--distribution',distro,'--exec','sh','-c',shell],
                   capture_output=True,text=True,timeout=25,check=False)
        if done.returncode == 0:
            return int(done.stdout.strip())*1024
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        pass
    return None


def _delete_wsl_cache(root: Path, *, run=None) -> dict:
    distro = _wsl_distribution(root)
    if not distro:
        raise StorageSafetyError('A recorded PICADS WSL distribution is required for cleanup')
    run = run or subprocess.run
    shell = ('set -eu; test -d "$HOME"; '
             'test ! -L "$HOME/.cache"; '
             'test ! -L "$HOME/.cache/picads-librelane-pip"; '
             'if [ -d "$HOME/.cache/picads-librelane-pip" ]; then '
             'rm -rf -- "$HOME/.cache/picads-librelane-pip"; fi')
    try:
        completed = run(['wsl.exe','--distribution',distro,'--exec','sh','-c',shell],
                        capture_output=True,text=True,timeout=180,check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StorageSafetyError(str(exc)) from exc
    if completed.returncode:
        raise StorageSafetyError('Could not clear scoped WSL pip cache: '+
                                 ((completed.stderr or completed.stdout or '').strip())[-500:])
    return {'id':'wsl:picads-pip-cache','status':'REMOVED',
            'detail':'Only the PICADS-owned pip download cache in the selected WSL distro'}


def storage_inventory(*, root: Path | None = None, now: float | None = None,
                      include_wsl=True, run=None, project: Path | None = None) -> dict:
    """Read-only, stable IDs. `bytes` is an estimate, not guaranteed recovered disk space."""
    root = Path(os.path.abspath(root or dependency_root()))
    now = time.time() if now is None else now
    entries = []
    for package in _PORTABLE:
        folder = root / package
        if (folder.is_dir() and not folder.is_symlink()
                and _receipt(folder, package) is not None
                and not _has_symlink_component(root, folder)):
            entries.append(_entry('package:' + package, PACKAGES[package]['label'],
                                  'uninstall', str(folder), _bytes(folder),
                                  detail='PICADS portable install; reinstall with the normal package installer.'))
    # System packages are NOT deletable by folder removal. Only an install
    # actually initiated through PICADS's WinGet path is eligible for an
    # explicit package-manager uninstall; an adopted pre-existing KiCad is not.
    kicad_receipt = _receipt(root/'kicad', 'kicad')
    if kicad_receipt and kicad_receipt.get('method') == 'winget' and kicad_receipt.get('package_id') == 'KiCad.KiCad':
        entries.append(_entry('package:kicad-winget','KiCad application (WinGet uninstall)',
            'uninstall', 'WinGet package KiCad.KiCad', None,
            detail='UNINSTALLS KiCad for this Windows installation, potentially affecting OTHER projects. Only offered for a PICADS-initiated WinGet install.'))
    cache = root / 'librelane' / 'docker-installer-cache'
    if (cache.is_dir() and not _has_symlink_component(root, cache)):
        entries.append(_entry('cache:docker-installer', 'Docker Desktop installer download cache',
                              'cleanup', str(cache), _bytes(cache),
                              detail='Only PICADS cached installer files; Docker Desktop and all Docker data stay installed.'))
    if root.is_dir() and not root.is_symlink():
        for folder in sorted(root.iterdir()):
            if (folder.name.startswith('.picads-install-') and folder.is_dir()
                    and not folder.is_symlink() and not _has_symlink_component(root, folder)):
                try:
                    age = now - folder.stat().st_mtime
                except OSError:
                    continue
                if age >= _MIN_STAGING_AGE:
                    entries.append(_entry('cache:staging:' + folder.name,
                                          'Abandoned install staging: ' + folder.name,
                                          'cleanup', str(folder), _bytes(folder),
                                          detail='Temporary PICADS install directory older than 24 hours.'))
    for folder in (APP_ROOT / 'src' / 'chipcompiler' / '__pycache__',
                   APP_ROOT / 'src' / 'picads' / '__pycache__'):
        if folder.is_dir() and not folder.is_symlink():
            entries.append(_entry('cache:bytecode:' + folder.parent.name,
                                  'Python bytecode cache: ' + folder.parent.name,
                                  'cleanup', str(folder), _bytes(folder),
                                  detail='Recreated automatically when needed.'))
    if include_wsl:
        # Scoped cache for installs performed by PICADS after this release;
        # ~/.cache/pip is shared, and must NOT be cleaned automatically.
        distro_cache = _wsl_distribution(root)
        if distro_cache:
            cache_bytes = _wsl_directory_size(distro_cache, '.cache/picads-librelane-pip', run=run)
            if cache_bytes is not None and cache_bytes > 0:
                entries.append(_entry('wsl:picads-pip-cache', 'PICADS LibreLane pip download cache',
                    'cleanup', f'{distro_cache}: $HOME/.cache/picads-librelane-pip', cache_bytes,
                    detail='Only the PICADS-scoped pip cache. The shared ~/.cache/pip and other programs are untouched.'))
        receipt = _wsl_receipt(root)
        if receipt is not None:
            distro = receipt['distro']
            entries.append(_entry('wsl:librelane-venv', 'LibreLane Python virtual environment in WSL',
                                  'uninstall', f'{distro}: {_WSL_DIRECTORY}',
                                  _wsl_venv_size(distro, run=run),
                                  detail='Only PICADS LibreLane venv. Ubuntu, Docker images, Yosys, '
                                         'Ciel PDKs and other Linux software are preserved.'))
    # Explicitly selected project's *regenerable* outputs, never project
    # sources/configuration. Unknown/manual directories inside history are
    # excluded to avoid deleting user-placed data by mistake.
    if project is not None:
        project = Path(os.path.abspath(project))
        if project.is_dir() and not project.is_symlink() and (project/'chip.yaml').is_file() and not (project/'chip.yaml').is_symlink():
            base = project/'build'
            if not _has_symlink_component(project, base):
                latest = base/'latest'
                if (latest.is_dir() and not _has_symlink_component(project, latest)
                        and (latest/'report.json').is_file()):
                    entries.append(_entry('project:build-latest', 'Current generated build artifacts',
                        'cleanup', str(latest), _bytes(latest),
                        detail='Generated build/latest output, including possible GDS. Compiling again recreates it. Project sources are preserved.'))
                history = base/'history'
                if history.is_dir() and not _has_symlink_component(project, history):
                    try:
                        items = list(history.iterdir())
                        managed = bool(items) and all(
                            p.is_dir() and not p.is_symlink() and
                            re.fullmatch(r'[0-9]{8}T[0-9]{12}Z-[a-z0-9]{6}', p.name) and
                            (p/'report.json').is_file() and not (p/'report.json').is_symlink()
                            for p in items)
                    except OSError:
                        managed = False
                    if managed:
                        entries.append(_entry('project:build-history', 'Historical generated build artifacts',
                            'cleanup', str(history), _bytes(history),
                            detail='Only PICADS timestamped previous builds. Does not touch source, latest build, or backups.'))
    return {'root': str(root), 'entries': entries,
            'estimated_bytes': sum(row['bytes'] or 0 for row in entries),
            'safety': 'Inventory only. No files removed. Untracked or externally managed installs are excluded.',
            'excluded': ['Docker Desktop/engine/images/volumes', 'WSL distributions',
                         'shared PDKs (~/.ciel)', 'KiCad/MSYS2 system installations',
                         'project source/configuration and backup snapshots', 'unrecognized folders']}


def _clear_registrations_under(folder: Path) -> list[str]:
    """Forget registrations only if their selected path was inside the removed bundle."""
    removed = []
    data = read_settings()
    for tool, selection in data['tools'].items():
        try:
            path = Path(selection['path'])
            if path.is_relative_to(folder) or path.resolve().is_relative_to(folder):
                unregister_tool(tool)
                removed.append(tool)
        except (OSError, ValueError):
            continue
    return removed


def _uninstall_managed_kicad(root: Path, *, run=None, which=None) -> dict:
    receipt_file = root/'kicad'/'picads_install_receipt.json'
    receipt = _receipt(root/'kicad', 'kicad')
    if (receipt is None or receipt.get('method') != 'winget' or
            receipt.get('package_id') != 'KiCad.KiCad'):
        raise StorageSafetyError('KiCad does not have a PICADS-initiated WinGet install receipt')
    which = which or shutil.which
    exe = which('winget')
    if not exe:
        raise StorageSafetyError('WinGet was not found; cannot safely uninstall system KiCad')
    run = run or subprocess.run
    argv = [exe,'uninstall','--id','KiCad.KiCad','--exact','--source','winget',
            '--disable-interactivity']
    try:
        result = run(argv,capture_output=True,text=True,timeout=1800,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise StorageSafetyError('KiCad WinGet uninstall failed: '+str(exc)) from exc
    if result.returncode:
        raise StorageSafetyError('KiCad WinGet uninstall returned '+str(result.returncode)+': '+
                                 ((result.stderr or result.stdout or '').strip())[-500:])
    # Clear only registrations *exactly* matching the paths recorded at
    # installation, not paths adopted or manually reconfigured afterwards.
    from .dependencies import read_settings, unregister_tool
    current = read_settings()['tools']
    cleared=[]
    for name, installed in (receipt.get('registered_tools') or {}).items():
        if (name in ('kicad','kicad-cli','pcbnew') and isinstance(installed,str)
                and current.get(name,{}).get('path') == installed):
            unregister_tool(name);cleared.append(name)
    receipt_file.unlink(missing_ok=True)
    return {'id':'package:kicad-winget','status':'REMOVED','cleared_tools':cleared,
            'detail':'KiCad removed using WinGet. PICADS kept other installations and the old install log.'}


def _delete_wsl_venv(root: Path, *, run=None) -> dict:
    receipt = _wsl_receipt(root)
    if not receipt:
        raise StorageSafetyError('A matching LibreLane smoke-test receipt is required')
    distro = receipt['distro']
    run = run or subprocess.run
    # No interpolation of filesystem paths, arbitrary bash snippets or caller
    # input. The only WSL target is this installer's own exact venv directory.
    shell = ('set -eu; base="$HOME/.local/share/picads-librelane"; '
             'test -d "$HOME"; test ! -L "$HOME/.local"; '
             'test ! -L "$HOME/.local/share"; test ! -L "$base"; '
             'test ! -L "$base/venv"; '
             'if [ -e "$base/venv" ]; then rm -rf -- "$base/venv"; fi')
    try:
        finished = run(['wsl.exe', '--distribution', distro, '--exec', 'sh', '-c', shell],
                       capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StorageSafetyError(f'WSL environment removal failed: {exc}') from exc
    if finished.returncode:
        raise StorageSafetyError('WSL refused venv removal; receipt left intact: '
                                 + ((finished.stderr or finished.stdout or '').strip())[-800:])
    managed = root / 'librelane'
    for name in ('backend_smoke_receipt.json', 'backend_smoke_passed.txt'):
        item = _checked_target(root, managed / name)
        item.unlink(missing_ok=True)
    return {'id': 'wsl:librelane-venv', 'status': 'REMOVED',
            'detail': 'PICADS WSL virtual environment and verification marker removed; Docker/Ubuntu/PDKs preserved.'}


def apply_storage_cleanup(ids: list[str], *, confirmed: bool = False,
                          root: Path | None = None, now: float | None = None,
                          run=None, include_wsl=True, project: Path | None = None) -> dict:
    """Perform only explicitly selected inventory entries, after a separate confirmation.

    Each entry is rediscovered and revalidated just before removal. A failed
    item is reported, never silently counted as success.
    """
    if not confirmed:
        raise StorageSafetyError('Removal requires explicit confirmation (--apply or GUI confirmation)')
    if not ids or len(ids) != len(set(ids)):
        raise StorageSafetyError('Select one or more unique inventory IDs')
    root = Path(os.path.abspath(root or dependency_root()))
    inventory = storage_inventory(root=root, now=now, run=run, include_wsl=include_wsl, project=project)
    allowed = {row['id']: row for row in inventory['entries']}
    unknown = [key for key in ids if key not in allowed]
    if unknown:
        raise StorageSafetyError('Not found or not safely managed: ' + ', '.join(unknown))
    results = []
    for key in ids:
        row = allowed[key]
        try:
            if key.startswith('project:'):
                if project is None:
                    raise StorageSafetyError('No project was explicitly selected')
                project = Path(os.path.abspath(project))
                expected = project/'build'/('latest' if key == 'project:build-latest' else 'history')
                if key not in ('project:build-latest','project:build-history') or str(expected) != row['path']:
                    raise StorageSafetyError('Generated build target changed')
                folder = _checked_target(project, expected)
                # Re-inventory immediately before destructive action.
                fresh = {e['id']: e for e in storage_inventory(root=root, include_wsl=False, project=project)['entries']}
                if key not in fresh or fresh[key]['path'] != str(folder):
                    raise StorageSafetyError('Generated build structure changed since inspection')
            elif key == 'package:kicad-winget':
                results.append(_uninstall_managed_kicad(root,run=run))
                continue
            elif key == 'wsl:picads-pip-cache':
                results.append(_delete_wsl_cache(root, run=run))
                continue
            elif key == 'wsl:librelane-venv':
                results.append(_delete_wsl_venv(root, run=run))
                continue
            if key.startswith('cache:bytecode:'):
                folder = APP_ROOT / 'src' / key.rsplit(':', 1)[-1] / '__pycache__'
                if folder.parent.name not in ('chipcompiler', 'picads'):
                    raise StorageSafetyError('Invalid bytecode cache directory')
                # Do not permit guessed relative target locations.
                if str(folder) != row['path']:
                    raise StorageSafetyError('Bytecode cache target changed')
                if _has_symlink_component(APP_ROOT, folder):
                    raise StorageSafetyError('Bytecode target is symlinked')
            elif not key.startswith('project:'):
                folder = _checked_target(root, Path(row['path']))
            if key.startswith('package:'):
                package = key.split(':', 1)[1]
                if _receipt(folder, package) is None:
                    raise StorageSafetyError('Package receipt changed')
            if key.startswith('cache:staging:') and (
                    (now or time.time()) - folder.stat().st_mtime < _MIN_STAGING_AGE):
                raise StorageSafetyError('Staging folder is currently too new')
            if folder.is_dir() and not folder.is_symlink():
                shutil.rmtree(folder)
            elif folder.is_file() and not folder.is_symlink():
                folder.unlink()
            else:
                raise StorageSafetyError('Target disappeared or is now a symlink')
            cleared = (_clear_registrations_under(folder) if key.startswith('package:') else [])
            results.append({'id': key, 'status': 'REMOVED', 'estimated_bytes': row['bytes'],
                            'cleared_tools': cleared})
        except (OSError, StorageSafetyError, ValueError) as exc:
            results.append({'id': key, 'status': 'FAILED', 'error': str(exc)})
    return {'status': 'PASS' if all(r['status'] == 'REMOVED' for r in results) else 'PARTIAL',
            'results': results, 'estimated_bytes_removed': sum((allowed[r['id']]['bytes'] or 0)
                                                        for r in results if r['status'] == 'REMOVED'),
            'note': 'Reclaimed disk space may differ due to filesystem allocation and shared files.'}
