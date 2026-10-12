"""Persistent, explicit external-tool selection for PICADS.

A registered path is never substituted with a different executable on PATH:
invalid selections are reported as unavailable so the user can correct them.
This module does not execute tools or install packages.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import subprocess
from functools import lru_cache
from pathlib import Path

# A single registry shared by all projects. Avoid storing software installation
# paths inside project archives or overriding the user's existing project YAML.
TOOLS = {
    'kicad': ('kicad', 'kicad.exe'),
    'kicad-cli': ('kicad-cli', 'kicad-cli.exe'),
    'pcbnew': ('pcbnew', 'pcbnew.exe'),
    'yosys': ('yosys', 'yosys.exe'),
    'iverilog': ('iverilog', 'iverilog.exe'),
    'vvp': ('vvp', 'vvp.exe'),
    'librelane': ('librelane', 'librelane.exe', 'librelane.cmd'),
    'openroad': ('openroad', 'openroad.exe'),
    'klayout': ('klayout', 'klayout.exe', 'klayout_app.exe'),
    'magic': ('magic', 'magic.exe'),
    'netgen': ('netgen', 'netgen.exe'),
    'sby': ('sby', 'sby.exe'),
    'z3': ('z3', 'z3.exe'),
    'verilator': ('verilator', 'verilator.exe'),
    'gcc': ('gcc', 'gcc.exe'),
    'g++': ('g++', 'g++.exe'),
    'wsl.exe': ('wsl.exe', 'wsl'),
}
# Common bundled locations, rather than a recursive filesystem search.
SEARCH_SUBDIRS = ('', 'bin', 'bin64', 'usr/bin', 'mingw64/bin', 'mingw/bin',
                  'tools/bin', 'KiCad/bin', 'KiCad/9.0/bin', 'KiCad/8.0/bin',
                  'KiCad/10.0/bin', 'oss-cad-suite/bin', 'oss-cad-suite/iverilog/bin',
                  'oss-cad-suite/py3bin')

class DependencyConfigurationError(ValueError):
    pass


def settings_file() -> Path:
    override = os.environ.get('PICADS_SETTINGS_DIR')
    base = (Path(override).expanduser() if override else
            Path(os.environ['APPDATA']) / 'PICADS' if sys.platform == 'win32' and os.environ.get('APPDATA') else
            Path.home() / '.config' / 'picads')
    return base / 'dependencies.json'


def read_settings() -> dict:
    path = settings_file()
    if not path.is_file():
        return {'schema': 1, 'tools': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise DependencyConfigurationError(f'Cannot read {path}: {exc}') from exc
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('tools'), dict):
        raise DependencyConfigurationError(f'Invalid PICADS dependency registry: {path}')
    for key, value in data['tools'].items():
        if key not in TOOLS or not isinstance(value, dict) or value.get('kind') not in ('app', 'folder') or not isinstance(value.get('path'), str):
            raise DependencyConfigurationError(f'Invalid dependency registration for {key!r}')
    return data


def _atomic_save(data: dict) -> None:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    import os as _os
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.dependencies-', suffix='.tmp', delete=False) as file:
            tmp = Path(file.name)
            json.dump(data, file, indent=2)
            file.write('\n')
        _os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def _executable(path: Path) -> bool:
    # Windows has no meaningful POSIX execute bits. Reject arbitrary data files
    # there; on Unix require the executable permission bit.
    return (path.is_file() and (path.suffix.lower() in ('.exe', '.cmd', '.bat', '.com')
            if sys.platform == 'win32' else os.access(path, os.X_OK)))


def _locate(tool: str, path: Path, kind: str) -> Path | None:
    if kind == 'app':
        return path if _executable(path) and path.name.lower() in {name.lower() for name in TOOLS[tool]} else None
    if kind != 'folder' or not path.is_dir():
        return None
    for subdir in SEARCH_SUBDIRS:
        for name in TOOLS[tool]:
            candidate = path / subdir / name
            if _executable(candidate):
                return candidate
    return None


def register_tool(tool: str, path: str | Path, kind: str = 'app') -> dict:
    if tool not in TOOLS:
        raise DependencyConfigurationError(f'Unknown dependency {tool!r}; known: {", ".join(TOOLS)}')
    if kind not in ('app', 'folder'):
        raise DependencyConfigurationError('Selection kind must be app or folder')
    chosen = Path(path).expanduser().resolve()
    found = _locate(tool, chosen, kind)
    if not found:
        hint = 'Select the application executable' if kind == 'app' else 'Select its installation folder or bin folder'
        raise DependencyConfigurationError(f'{tool} was not found at {chosen}. {hint}. No setting was changed.')
    data = read_settings()
    data['tools'][tool] = {'kind': kind, 'path': str(chosen)}
    _atomic_save(data)
    return tool_status(tool)


def unregister_tool(tool: str) -> dict:
    if tool not in TOOLS:
        raise DependencyConfigurationError(f'Unknown dependency {tool!r}')
    data = read_settings()
    data['tools'].pop(tool, None)
    _atomic_save(data)
    return tool_status(tool)


def tool_status(tool: str) -> dict:
    if tool not in TOOLS:
        raise DependencyConfigurationError(f'Unknown dependency {tool!r}')
    registered = read_settings()['tools'].get(tool)
    if registered:
        found = _locate(tool, Path(registered['path']), registered['kind'])
        return {'available': bool(found), 'path': str(found) if found else None,
                'source': 'registered', 'selection': registered['path'],
                'kind': registered['kind'],
                'error': None if found else 'Registered location is missing or no longer contains the executable.'}
    # PATH lookup is still available by default when nothing has been selected.
    found = next((shutil.which(name) for name in TOOLS[tool] if shutil.which(name)), None)
    return {'available': bool(found), 'path': str(Path(found).resolve()) if found else None,
            'source': 'PATH' if found else 'unavailable', 'selection': None,
            'kind': None, 'error': None if found else 'Not found on PATH or in registered settings.'}


def resolve_tool(tool: str) -> str | None:
    return tool_status(tool)['path']


def probe_tools() -> dict:
    return {name: tool_status(name) for name in TOOLS}


@lru_cache(maxsize=4)
def _portable_windows_environment(activation: str) -> dict:
    """Read OSS CAD Suite's official environment.bat into a child-only environment.

    This is invoked only for a portable suite explicitly installed in PICADS's
    managed dependency directory. A failed activation is surfaced as an error.
    """
    try:
        p = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c',
                            'call "' + activation + '" >nul && set'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DependencyConfigurationError(f'OSS CAD Suite activation failed: {exc}') from exc
    if p.returncode != 0:
        raise DependencyConfigurationError(f'OSS CAD Suite environment.bat exited {p.returncode}: {p.stderr[-500:]}')
    environment = {}
    for line in p.stdout.splitlines():
        if '=' in line and not line.startswith('='):
            name,value = line.split('=', 1)
            environment[name] = value
    if not environment.get('PATH'):
        raise DependencyConfigurationError('OSS CAD Suite activation did not provide PATH')
    return environment


def managed_cad_activation() -> Path | None:
    """Detect managed OSS suite; don't execute arbitrary user-registered scripts."""
    if sys.platform != 'win32':return None
    from .windows_installer import dependency_root
    root = dependency_root() / 'oss-cad-suite'
    for relative in ('oss-cad-suite/environment.bat', 'environment.bat'):
        file = root / relative
        if file.is_file():return file
    for file in root.glob('*/oss-cad-suite/environment.bat'):
        if file.is_file():return file
    return None


def dependency_environment(base: dict | None = None) -> dict:
    """Expose registered program directories to child processes.

    Required by wrappers such as SymbiYosys/LibreLane that launch Yosys,
    OpenROAD, SMT solvers, etc. Does not modify the parent process PATH.
    """
    env = dict(os.environ if base is None else base)
    activation = managed_cad_activation()
    if activation is not None:
        activated = _portable_windows_environment(str(activation))
        # Keep caller custom variables and PICADS configuration unchanged.
        for key in ('PATH', 'PYTHONPATH', 'TCL_LIBRARY', 'PERL5LIB', 'QT_PLUGIN_PATH'):
            if key in activated:env[key] = activated[key]
    folders = []
    seen = set()
    for name in TOOLS:
        executable = resolve_tool(name)
        if executable:
            folder = str(Path(executable).parent)
            if os.path.normcase(folder) not in seen:
                seen.add(os.path.normcase(folder)); folders.append(folder)
    if folders:
        env['PATH'] = os.pathsep.join([*folders, env.get('PATH', '')])
    return env


def auto_detect_tool(tool: str, roots: list[Path] | None = None) -> dict:
    """Conservatively search PATH and common Windows install locations.

    Does not overwrite an explicitly saved selection, including a broken one.
    ``roots`` is injectable so the discovery behavior is tested without a
    particular host installation. Does not launch unknown binaries.
    """
    if tool not in TOOLS:
        raise DependencyConfigurationError(f'Unknown dependency {tool!r}')
    existing = read_settings()['tools'].get(tool)
    if existing:
        return {**tool_status(tool), 'auto_detect_action': 'PRESERVED_MANUAL_SELECTION'}
    detected = tool_status(tool)
    if detected['available']:
        return {**detected, 'auto_detect_action': 'FOUND_ON_PATH'}
    if roots is None:
        roots = []
        for var in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            if os.environ.get(var):roots.append(Path(os.environ[var]))
        if sys.platform == 'win32':
            systemdrive = os.environ.get('SystemDrive','C:')
            roots += [Path(systemdrive+'/oss-cad-suite'), Path(systemdrive+'/tools'),
                      Path(systemdrive+'/msys64')]
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():continue
        # Versioned install folders (KiCad/9.0, KLayout/...) are checked only
        # down to two levels, without unbounded recursive walking.
        prefixes = [root]
        for pattern in ('KiCad/*','KiCad','KLayout','OSS CAD Suite','oss-cad-suite',
                        'LibreLane','OpenROAD','Yosys','iverilog','Icarus Verilog'):
            prefixes.extend(sorted(root.glob(pattern),reverse=True)[:12])
        for prefix in prefixes:
            found = _locate(tool, prefix, 'folder')
            if found:
                status = register_tool(tool, prefix, 'folder')
                return {**status, 'auto_detect_action': 'FOUND_IN_INSTALLATION'}
    return {**tool_status(tool), 'auto_detect_action': 'NOT_FOUND'}


def auto_detect_all() -> dict:
    return {name: auto_detect_tool(name) for name in TOOLS}
