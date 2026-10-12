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
import tempfile
from contextlib import contextmanager
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
    'sby': ('sby.exe', 'sby.cmd', 'sby.bat', 'sby'),
    'z3': ('z3', 'z3.exe'),
    'verilator': ('verilator.exe', 'verilator.cmd', 'verilator.bat', 'verilator'),
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


def _portable_windows_environment(activation: str) -> dict:
    """Activate the official OSS CAD Suite environment using a temporary CMD file.

    Feeding `call "C:/path with spaces/environment.bat" && set` directly as
    cmd.exe's `/c` argument is *not* reliable: cmd has another quote-removal
    pass that can interpret the opening quote as a program name. The temporary
    file makes the nested batch call unambiguous and keeps it out of the shell
    command line. No environment variables are modified in the GUI process.
    """
    activation_file = Path(activation)
    if not activation_file.is_file():
        raise DependencyConfigurationError(f'OSS CAD Suite activation file missing: {activation_file}')
    # Preserve percent signs in the inserted path. Windows filenames cannot
    # contain double quotes or line terminators; disable delayed expansion to
    # preserve exclamation marks in unusual user directory names.
    safe_path = str(activation_file).replace('%', '%%')
    script = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
              f'call "{safe_path}" >nul\r\n'
              'if errorlevel 1 exit /b %errorlevel%\r\n'
              'set\r\n')
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='',
                                         suffix='.cmd', prefix='picads-cad-',
                                         delete=False) as tmp:
            tmp.write(script)
            temp_name = tmp.name
        cmd = os.environ.get('COMSPEC', 'cmd.exe')
        # Exact documented double-quote form: cmd /d /s /c ""path to .cmd"".
        # Passing a constructed string avoids subprocess.list2cmdline adding
        # a second layer of quotes to the entire `/c` argument on Windows.
        command = f'"{cmd}" /d /s /c ""{temp_name}""'
        try:
            p = subprocess.run(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True,
                               errors='replace', timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DependencyConfigurationError(f'OSS CAD Suite activation failed: {exc}') from exc
        if p.returncode != 0:
            raise DependencyConfigurationError(
                f'OSS CAD Suite environment.bat exited {p.returncode}: '
                f'{p.stderr[-500:]}; activation={activation_file}')
        environment = {}
        for line in p.stdout.splitlines():
            if '=' in line and not line.startswith('='):
                name, value = line.split('=', 1)
                environment[name] = value
        if not environment.get('PATH') and not environment.get('Path'):
            raise DependencyConfigurationError('OSS CAD Suite activation did not provide PATH')
        return environment
    finally:
        if temp_name is not None:
            try: Path(temp_name).unlink(missing_ok=True)
            except OSError: pass


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


_CAD_TOOLS = frozenset(('yosys', 'iverilog', 'vvp', 'z3', 'sby', 'verilator'))
_MINGW_TOOLS = frozenset(('gcc', 'g++'))


def _windows_prepend_path(env: dict, folders: list[str]) -> None:
    """Prepend existing directories once, using Windows semantics on Windows."""
    sep = ';' if sys.platform == 'win32' else os.pathsep
    path_key = next((k for k in env if k.upper() == 'PATH'), 'PATH')
    prior = env.get(path_key, '')
    seen = set()
    selected = []
    # Deduplicate against original PATH as well as the newly added entries.
    for candidate in [*folders, *prior.split(sep)]:
        if not candidate:
            continue
        key = os.path.normcase(os.path.normpath(candidate))
        if sys.platform == 'win32': key = key.casefold()
        if key not in seen:
            seen.add(key)
            selected.append(candidate)
    env[path_key] = sep.join(selected)


def dependency_environment(base: dict | None = None, *, tool: str | None = None) -> dict:
    """Return a child-only, tool-scoped runtime environment.

    On Windows, do NOT prepend KiCad, KLayout, MSYS2 and OSS CAD Suite folders
    together: their conflicting libstdc++/Qt/Tcl/zlib DLLs can cause Windows
    loader 0xC0000135/0xC0000139 failures. Tools in a single family share the
    paths they need; unrelated executable directories never enter the PATH.

    `tool=None` is intentionally neutral on Windows (for GUI/pytest). On Unix,
    retain historical registered-folder discovery for compatibility.
    """
    env = dict(os.environ if base is None else base)
    if tool is not None and tool not in TOOLS:
        raise DependencyConfigurationError(f'Unknown child tool {tool!r}')
    if sys.platform == 'win32':
        if tool in _CAD_TOOLS:
            activation = managed_cad_activation()
            if activation is not None:
                activated = _portable_windows_environment(str(activation))
                # The activation script is trusted only when found inside the
                # managed PICADS package, and only applies to CAD child tools.
                for key in ('PATH', 'Path', 'TCL_LIBRARY', 'PERL5LIB',
                            'VERILATOR_ROOT'):
                    if key in activated:
                        if key.upper() == 'PATH':
                            env[next((k for k in env if k.upper() == 'PATH'), 'PATH')] = activated[key]
                        else:
                            env[key] = activated[key]
            paths = []
            for name in _CAD_TOOLS:
                exe = resolve_tool(name)
                if exe:
                    paths.append(str(Path(exe).parent))
            # Expose the complete managed suite BIN even when some optional
            # tools were not registered. This is where Windows DLLs live.
            if activation is not None:
                paths.insert(0, str(activation.parent / 'bin'))
                paths.append(str(activation.parent / 'py3bin'))
            if tool == 'verilator':
                # Verilator may delegate compilation to a separately installed
                # MSYS2 C++ compiler. Do not add KiCad/KLayout directories.
                for name in _MINGW_TOOLS:
                    exe = resolve_tool(name)
                    if exe: paths.append(str(Path(exe).parent))
            # Keep the executable's own directory first; it contains its
            # matching DLLs, while unrelated installations do not precede it.
            exe = resolve_tool(tool)
            if exe: paths.insert(0, str(Path(exe).parent))
            _windows_prepend_path(env, paths)
        elif tool is not None:
            exe = resolve_tool(tool)
            if exe:
                folders = [str(Path(exe).parent)]
                if tool in _MINGW_TOOLS:
                    for sibling in _MINGW_TOOLS:
                        path = resolve_tool(sibling)
                        if path: folders.append(str(Path(path).parent))
                _windows_prepend_path(env, folders)
        return env

    # Unix legacy: user-selected tool directories help wrappers find related
    # executables (e.g. yosys invoking z3) without changing the parent PATH.
    folders = []
    for name in TOOLS:
        if tool is not None and name not in (tool, 'yosys', 'z3', 'sby', 'iverilog', 'vvp'):
            continue
        exe = resolve_tool(name)
        if exe: folders.append(str(Path(exe).parent))
    _windows_prepend_path(env, folders)
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
