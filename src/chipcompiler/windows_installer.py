"""Opt-in, Windows-first installer for portable external EDA tools.

PICADS itself never needs Linux for its GUI, DLS simulation or RTL generation.
Only native Windows archives are installed here. The LibreLane ASIC backend is
explicitly optional and requires a separately configured runtime on Windows.

Network/download operations occur only in response to an explicit install call.
All downloads are HTTPS, only approved upstream hosts are accepted, and archives
are extracted with traversal/size limits. No downloaded scripts are executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Callable

from .dependencies import TOOLS, register_tool, tool_status

MAX_DOWNLOAD_BYTES = 4 * 1024**3
MAX_EXTRACT_BYTES = 10 * 1024**3
MAX_FILES = 150_000
APP_ROOT = Path(__file__).resolve().parents[2]

# Upstream defaults. KLayout's ZIP comes from its official Windows downloads,
# not GitHub source releases, which do not contain Windows application binaries.
PACKAGES = {
    'oss-cad-suite': {
        'label': 'OSS CAD Suite — Yosys, Icarus, Verilator, formal tools',
        'purpose': 'Native Windows RTL synthesis, simulation and formal checks',
        'mode': 'portable',
        'tools': ('yosys', 'iverilog', 'vvp', 'verilator', 'sby', 'z3', 'gcc', 'g++'),
        'required': False,
        'source': 'https://github.com/YosysHQ/oss-cad-suite-build/releases',
    },
    'klayout': {
        'label': 'KLayout — layout viewer and GDS inspection',
        'purpose': 'Native Windows layout inspection and manual DRC tools',
        'mode': 'portable',
        'tools': ('klayout',),
        'required': False,
        'source': 'https://www.klayout.de/build.html',
    },
    'librelane': {
        'label': 'LibreLane — complete ASIC physical design',
        'purpose': 'Guided WSL2 + Docker Desktop setup (optional; may require restart)',
        'mode': 'guided-wsl',
        'tools': ('librelane',),
        'required': False,
        'source': 'https://librelane.readthedocs.io/en/stable/installation/index.html',
    },
    'kicad': {
        'label': 'KiCad — optional PCB design companion',
        'purpose': 'WinGet installation and offline repair; registers KiCad, pcbnew PCB editor and KiCad CLI',
        'mode': 'winget',
        'tools': ('kicad', 'kicad-cli', 'pcbnew'),
        'required': False,
        'source': 'https://www.kicad.org/download/windows/',
    },
    'msys2-toolchain': {
        'label': 'MSYS2 UCRT64 — native GCC, G++ and Verilator',
        'purpose': 'Official WinGet + MSYS2 pacman toolchain; no Linux runtime needed',
        'mode': 'winget-msys2',
        'tools': ('gcc', 'g++', 'verilator'),
        'required': False,
        'source': 'https://www.msys2.org/',
    },
}

class PackageInstallError(RuntimeError):
    pass


def dependency_root() -> Path:
    configured = os.environ.get('PICADS_DEPENDENCY_ROOT')
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'dependencies'
    return APP_ROOT / 'dependencies'


def install_catalog() -> list[dict]:
    """Report managed installs separately from unrelated copies on PATH.

    A bundled suite may not contain all optional formal tools, so checking
    every registry entry would incorrectly mark a successful install as
    missing. Never offer an overwrite of an existing managed directory.
    """
    rows = []
    root = dependency_root()
    for key, spec in PACKAGES.items():
        states = {tool: tool_status(tool) for tool in spec['tools']}
        package_dir = root / key
        receipt_path = package_dir / 'picads_install_receipt.json'
        managed, receipt = False, None
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                essential = ('yosys', 'iverilog', 'vvp') if key == 'oss-cad-suite' else ('klayout',)
                files = receipt.get('resolved_tools', {})
                managed = receipt.get('package') == key and all(
                    isinstance(files.get(t), str) and
                    (package_dir / files[t]).is_file() for t in essential)
            except (OSError, ValueError, TypeError, KeyError):
                managed = False
        if key == 'kicad':
            managed = managed or bool(receipt_path.is_file() and
                                      all(states[t]['available'] for t in ('kicad','kicad-cli','pcbnew')))
        if key == 'msys2-toolchain':
            managed = bool(receipt_path.is_file() and all(s['available'] for s in states.values()))
        if key == 'librelane':
            managed = (package_dir / 'backend_smoke_passed.txt').is_file()
        # A valid managed receipt makes an installation safely re-registrable
        # without downloading or touching the already extracted toolchain.
        can_repair = (spec['mode'] == 'portable' and
                      receipt_path.is_file() and
                      isinstance(receipt, dict) and receipt.get('package') == key)
        can_install = ((spec['mode'] == 'portable' and (not package_dir.exists() or can_repair)) or
                       spec['mode'] in ('winget', 'guided-wsl', 'winget-msys2'))
        rows.append({'id': key, 'name': spec['label'], 'purpose': spec['purpose'],
                     'mode': spec['mode'], 'required': spec['required'],
                     'source': spec['source'],
                     'available': all(s['available'] for s in states.values()),
                     'installed': managed,
                     'managed_path_exists': package_dir.exists(),
                     'can_repair': can_repair, 'can_install': can_install,
                     'receipt': str(receipt_path) if managed else None,
                     'tools': states})
    return rows


def _ensure_allowed_url(url: str, allowed: set[str]) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname.lower() not in allowed:
        raise PackageInstallError(f'Unexpected download origin: {url}')
    if parsed.username or parsed.password:
        raise PackageInstallError('Credential-bearing download URL refused')


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: set[str]):
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ensure_allowed_url(newurl, self.allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, allowed: set[str], timeout: int = 45):
    _ensure_allowed_url(url, allowed)
    opener = urllib.request.build_opener(_CheckedRedirect(allowed))
    return opener.open(urllib.request.Request(url, headers={'User-Agent': 'PICADS-Windows-Installer/0.16',
                                                             'Accept': 'application/vnd.github+json'}), timeout=timeout)


_GITHUB_HOSTS = {'api.github.com', 'github.com', 'objects.githubusercontent.com',
                 'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com'}
_KLAYOUT_HOSTS = {'www.klayout.de', 'klayout.de', 'www.klayout.org', 'klayout.org'}


def _oss_asset() -> dict:
    url = 'https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest'
    with _open(url, _GITHUB_HOSTS) as response:
        data = json.loads(response.read(3 * 1024**2))
    matches = [a for a in data.get('assets', ()) if
               re.search(r'windows[-_]x64', str(a.get('name', '')), re.I) and
               str(a.get('name', '')).lower().endswith(('.tgz', '.tar.gz', '.zip'))]
    if len(matches) != 1:
        raise PackageInstallError('Could not identify a unique Windows x64 OSS CAD Suite release archive.')
    a = matches[0]
    return {'name': a['name'], 'url': a['browser_download_url'],
            'version': data.get('tag_name', ''), 'digest': a.get('digest'), 'bytes': a.get('size', 0),
            'allowed_hosts': _GITHUB_HOSTS}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.hrefs = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for k, value in attrs if k == 'href' and value)


def _klayout_asset() -> dict:
    base = 'https://www.klayout.de/build.html'
    with _open(base, _KLAYOUT_HOSTS) as response:
        html = response.read(3 * 1024**2).decode('utf-8', errors='replace')
    links = _Links(); links.feed(html)
    candidates = []
    for href in links.hrefs:
        url = urllib.parse.urljoin(base, href)
        path = urllib.parse.urlsplit(url).path
        name = urllib.parse.unquote(PurePosixPath(path).name)
        if (re.search(r'klayout.*win64.*\.zip$', name, re.I) and
                'master' not in name.lower()):
            try: _ensure_allowed_url(url, _KLAYOUT_HOSTS)
            except PackageInstallError: continue
            candidates.append((name, url))
    if not candidates:
        raise PackageInstallError('No official Windows portable KLayout ZIP found; use Choose App/Folder from the official download page.')
    # Prefer the most recent stable version, then UCRT among same versions.
    def stable_rank(item):
        match = re.search(r'klayout[-_](\d+)\.(\d+)\.(\d+)',item[0],re.I)
        version = tuple(int(v) for v in match.groups()) if match else (0,0,0)
        return (version, 'ucrt' in item[0].lower(), item[0])
    candidates.sort(key=stable_rank,reverse=True)
    name, url = candidates[0]
    return {'name': name, 'url': url, 'version': name, 'digest': None,
            'allowed_hosts': _KLAYOUT_HOSTS}


def _safe_name(name: str) -> Path:
    normalized = name.replace('\\', '/')
    if normalized.startswith('/') or '\x00' in normalized or re.match(r'^[a-zA-Z]:', normalized):
        raise PackageInstallError(f'Unsafe archive member: {name!r}')
    pure = PurePosixPath(normalized)
    if '..' in pure.parts:
        raise PackageInstallError(f'Archive path traversal rejected: {name!r}')
    return Path(*[p for p in pure.parts if p not in ('.', '')])


def _extract(archive: Path, dest: Path, progress: Callable[[str], None]) -> int:
    total = 0; count = 0
    is_zip = zipfile.is_zipfile(archive)
    if is_zip:
        with zipfile.ZipFile(archive) as f:
            members = f.infolist()
            for m in members:
                target = dest / _safe_name(m.filename)
                if m.is_dir():target.mkdir(parents=True, exist_ok=True); continue
                # Reject Unix symlinks or device entries embedded in ZIP files.
                mode = (m.external_attr >> 16) & 0o170000
                if mode not in (0, 0o100000):
                    raise PackageInstallError('Unsafe ZIP member type: ' + m.filename)
                count += 1; total += m.file_size
                if count > MAX_FILES or total > MAX_EXTRACT_BYTES:raise PackageInstallError('Extracted archive exceeds safety limits')
                target.parent.mkdir(parents=True, exist_ok=True)
                with f.open(m) as src, target.open('wb') as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
    else:
        links = []
        with tarfile.open(archive, mode='r:*') as f:
            for m in f:
                target = dest / _safe_name(m.name)
                if m.isdir():target.mkdir(parents=True, exist_ok=True);continue
                if m.issym() or m.islnk():
                    links.append(m);continue
                if not m.isfile():
                    raise PackageInstallError('Unexpected archive entry type: '+m.name)
                count += 1;total += m.size
                if count > MAX_FILES or total > MAX_EXTRACT_BYTES:raise PackageInstallError('Extracted archive exceeds safety limits')
                target.parent.mkdir(parents=True, exist_ok=True)
                src = f.extractfile(m)
                if src is None:raise PackageInstallError('Missing tar member data')
                with src, target.open('wb') as out:shutil.copyfileobj(src, out, 1024 * 1024)
            # Windows cannot reliably create symlinks without elevated privileges:
            # materialize only internal file links as copies, without external targets.
            for m in links:
                target = dest / _safe_name(m.name)
                if m.issym():
                    if m.linkname.startswith('/') or re.match(r'^[a-zA-Z]:',m.linkname):
                        raise PackageInstallError('Absolute archive symlink refused')
                    referent = _safe_name(posixpath.normpath(posixpath.join(
                        str(PurePosixPath(m.name).parent), m.linkname)))
                else:
                    referent = _safe_name(m.linkname)
                source = dest / referent
                if source.is_dir():
                    # Reject loops; materialize directory symlinks as copies
                    # because ordinary Windows users cannot create symlinks.
                    if source == target or source in target.parents or target in source.parents:
                        raise PackageInstallError('Recursive archive directory link refused')
                    shutil.copytree(source,target,symlinks=False)
                    for item in target.rglob('*'):
                        if item.is_file():count += 1;total += item.stat().st_size
                        if count > MAX_FILES or total > MAX_EXTRACT_BYTES:
                            raise PackageInstallError('Extracted archive exceeds safety limits')
                elif source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    count += 1; total += target.stat().st_size
                else:
                    raise PackageInstallError(f'Unsupported internal archive link: {m.name!r}')
                if count > MAX_FILES or total > MAX_EXTRACT_BYTES:
                    raise PackageInstallError('Extracted archive exceeds safety limits')
    progress(f'Extracted {count} files ({total // (1024**2)} MiB)')
    return count


def _download(asset: dict, path: Path, progress: Callable[[str], None]) -> str:
    n = 0; digest = hashlib.sha256()
    if isinstance(asset.get('bytes'), int) and asset['bytes'] > MAX_DOWNLOAD_BYTES:
        raise PackageInstallError('Upstream asset is too large for safe installation')
    with _open(asset['url'], asset['allowed_hosts'], timeout=60) as response, path.open('wb') as out:
        while True:
            block = response.read(1024**2)
            if not block: break
            n += len(block)
            if n > MAX_DOWNLOAD_BYTES:raise PackageInstallError('Download exceeded configured size limit')
            out.write(block);digest.update(block)
            if n % (32 * 1024**2) < len(block):progress(f'Downloaded {n // (1024**2)} MiB')
    value = digest.hexdigest()
    upstream = asset.get('digest')
    if upstream:
        if not str(upstream).startswith('sha256:') or value.lower() != str(upstream)[7:].lower():
            raise PackageInstallError('Upstream SHA-256 digest mismatch')
    progress(f'Download SHA-256: {value} ({"upstream-verified" if upstream else "locally recorded; upstream digest unavailable"})')
    return value


_WINDOWS_LAUNCHER_SUFFIXES = frozenset(('.exe', '.com', '.cmd', '.bat'))


def _supported_windows_launcher(path: Path) -> bool:
    """Reject extensionless POSIX scripts in mixed-platform Windows bundles.

    OSS CAD Suite includes shell/Python entry points named e.g. ``verilator``.
    A file with that name isn't directly registerable using PICADS's Windows
    app registry. Only register a native executable or Windows launcher.
    """
    return path.is_file() and path.suffix.lower() in _WINDOWS_LAUNCHER_SUFFIXES


def _find_binary(root: Path, name: str) -> Path | None:
    preferred = (root / 'oss-cad-suite' / 'bin', root / 'bin', root)
    aliases = [alias for alias in TOOLS[name] if
               Path(alias).suffix.lower() in _WINDOWS_LAUNCHER_SUFFIXES]
    # A Windows release can include an extensionless shell script and an EXE
    # with the same stem. Always prefer launchable Windows executables.
    for folder in preferred:
        for alias in aliases:
            candidate = folder / alias
            if _supported_windows_launcher(candidate):
                return candidate
    # A release archive may contain an extra outer directory.
    for folder in root.glob('*/oss-cad-suite/bin'):
        if not folder.is_dir():
            continue
        for alias in aliases:
            candidate = folder / alias
            if _supported_windows_launcher(candidate):
                return candidate
    if name == 'klayout':
        for candidate in root.rglob('klayout_app.exe'):
            if _supported_windows_launcher(candidate):
                return candidate
    return None


def _oss_verilator_wrapper(root: Path, progress: Callable[[str], None]) -> Path | None:
    """Expose an existing OSS CAD Suite verilator_bin.exe via an actual CMD wrapper.

    Upstream bundles can contain a Perl frontend named `verilator` and a
    native engine named `verilator_bin.exe`. Neither alone is directly usable
    as a PICADS-registered Windows `verilator` command. The launcher passes
    through arguments while setting the upstream VERILATOR_ROOT and PATH.
    It does NOT imply a C++ toolchain for building Verilator simulations.
    """
    roots = [root / 'oss-cad-suite']
    roots.extend(root.glob('*/oss-cad-suite'))
    for suite in roots:
        bin_path = suite / 'bin' / 'verilator_bin.exe'
        data_path = suite / 'share' / 'verilator'
        if not bin_path.is_file() or not data_path.is_dir():
            continue
        # Use a relative path to avoid hardcoding installation drive names or
        # spaces and to survive a user moving the PICADS directory.
        wrapper = root / 'picads-launchers' / 'verilator.cmd'
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        relative_bin = os.path.relpath(bin_path, wrapper.parent).replace('/', '\\')
        relative_data = os.path.relpath(data_path, wrapper.parent).replace('/', '\\')
        activation = suite / 'environment.bat'
        activate_line = ''
        if activation.is_file():
            relative_activation = os.path.relpath(activation, wrapper.parent).replace('/', '\\')
            activate_line = f'call "%~dp0{relative_activation}" >nul\r\n'
        bat = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
               + activate_line
               + f'set "VERILATOR_ROOT=%~dp0{relative_data}"\r\n'
               + f'"%~dp0{relative_bin}" %*\r\n'
               + 'exit /b %ERRORLEVEL%\r\n')
        wrapper.write_bytes(bat.encode('utf-8'))
        progress('Created Windows Verilator launcher for bundled verilator_bin.exe '
                 '(functional smoke test and a C++ toolchain are still required).')
        return wrapper
    return None


def _required_tools(package: str) -> tuple[str, ...]:
    return ('yosys', 'iverilog', 'vvp') if package == 'oss-cad-suite' else ('klayout',)


def _scan_native_tools(root: Path, package: str, progress: Callable[[str], None]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for tool in PACKAGES[package]['tools']:
        path = _find_binary(root, tool)
        if path is not None:
            found[tool] = path.relative_to(root)
        elif tool not in _required_tools(package):
            progress(f'Optional {tool}: no directly launchable Windows binary found; skipped registration')
    missing = set(_required_tools(package)) - set(found)
    if missing:
        raise PackageInstallError('Managed archive lacks required Windows executables: '+', '.join(sorted(missing)))
    return found


def _register_managed(package: str, directory: Path, progress: Callable[[str], None], *,
                      repaired: bool) -> dict:
    """Register Windows executables in-place; never use bare shell scripts.

    Also handles a v0.16.1 installation where extraction succeeded but optional
    Verilator registration failed. The managed content is not re-downloaded.
    """
    from .dependencies import DependencyConfigurationError
    found = _scan_native_tools(directory, package, progress)
    if package == 'oss-cad-suite' and 'verilator' not in found:
        wrapper = _oss_verilator_wrapper(directory, progress)
        if wrapper is not None:
            found['verilator'] = wrapper.relative_to(directory)
    receipt_path = directory / 'picads_install_receipt.json'
    try:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError) as exc:
        raise PackageInstallError(f'Missing/corrupt managed install receipt: {receipt_path}') from exc
    if not isinstance(receipt, dict) or receipt.get('package') != package:
        raise PackageInstallError('Managed installation receipt is not for '+package)
    registered = {}
    # Essential tools first: don't claim success unless every core tool can be
    # registered in the actual platform registry.
    for tool in (*_required_tools(package), *(t for t in found if t not in _required_tools(package))):
        if tool not in found:
            continue
        try:
            status = register_tool(tool, directory / found[tool], 'app')
        except (DependencyConfigurationError, OSError) as exc:
            if tool in _required_tools(package):
                raise PackageInstallError(f'Cannot register required Windows tool {tool}: {exc}') from exc
            progress(f'Optional {tool}: registration unavailable ({exc}); skipped')
            continue
        registered[tool] = status['path']
    receipt['resolved_tools'] = {t: str(found[t]) for t in registered}
    receipt['registration_schema'] = 2
    temp_receipt = receipt_path.with_suffix('.json.tmp')
    try:
        temp_receipt.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
        temp_receipt.replace(receipt_path)
    finally:
        temp_receipt.unlink(missing_ok=True)
    verb = 'Recovered existing' if repaired else 'Installed'
    progress(f'{verb} {package} at {directory}; registered {len(registered)} Windows launchers (no download during recovery)')
    return {'status': 'INSTALLED', 'package': package, 'directory': str(directory),
            'tools': registered, 'repaired': repaired,
            'sha256': receipt.get('sha256'),
            'upstream_digest_checked': receipt.get('upstream_digest_checked', False)}


def install_package(package: str, *, progress: Callable[[str], None] | None = None,
                    asset_override: dict | None = None) -> dict:
    """Install an explicitly selected tool or safely repair a managed package.

    Repair is entirely offline and never executes a downloaded shell script.
    asset_override is used only by offline tests.
    """
    progress = progress or (lambda msg: None)
    if package not in PACKAGES:
        raise PackageInstallError('Unknown package: '+package)
    if package in ('kicad', 'librelane', 'msys2-toolchain'):
        from .windows_optional_install import install_kicad, stage_librelane, install_msys2_toolchain
        root = dependency_root()
        if package == 'kicad':
            return install_kicad(root, progress)
        if package == 'librelane':
            return stage_librelane(root, progress)
        return install_msys2_toolchain(root, progress)
    if PACKAGES[package]['mode'] != 'portable':
        raise PackageInstallError(f'{package} has no approved portable package')
    root = dependency_root()
    root.mkdir(parents=True, exist_ok=True)
    final = root / package
    if final.exists():
        receipt = final / 'picads_install_receipt.json'
        if not receipt.is_file():
            raise PackageInstallError(f'{final} already exists without a valid PICADS receipt. '
                                      'Preserved without modification; choose an app/folder manually or inspect it.')
        progress(f'Reusing existing extracted {package} at {final}; skipping download and extraction')
        return _register_managed(package, final, progress, repaired=True)
    if sys.platform != 'win32' and asset_override is None:
        raise PackageInstallError('Native Windows packages can only be installed on Windows')
    asset = asset_override or (_oss_asset() if package == 'oss-cad-suite' else _klayout_asset())
    progress(f'Selected {package} ({asset["name"]}) from {asset["url"]}')
    with tempfile.TemporaryDirectory(prefix='.picads-install-', dir=root) as scratch:
        temp = Path(scratch)
        archive = temp / ('download.zip' if asset['name'].lower().endswith('.zip') else 'download.tar.gz')
        sha256 = _download(asset, archive, progress)
        extracted = temp / 'extracted'; extracted.mkdir()
        count = _extract(archive, extracted, progress)
        found = _scan_native_tools(extracted, package, progress)
        receipt = {'package': package, 'upstream_url': asset['url'], 'release': asset['version'],
                   'sha256': sha256, 'upstream_digest_checked': bool(asset.get('digest')),
                   'files': count, 'resolved_tools': {t: str(v) for t, v in found.items()},
                   'note': 'Native Windows installer; no Linux runtime or installer scripts executed.'}
        (extracted / 'picads_install_receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
        extracted.replace(final)
    # In the unlikely event that registration fails, the archive remains
    # intact with a receipt: the user can retry offline, avoiding a 2GB loss.
    return _register_managed(package, final, progress, repaired=False)


def repair_package(package: str, *, progress: Callable[[str], None] | None = None) -> dict:
    """Offline-only managed Windows package recovery; never downloads anything.

    Intended for reinstalling registry paths when a prior installation has
    already downloaded/extracted OSS CAD Suite or KLayout. No existing files
    are deleted, overwritten (except PICADS's receipt), or executed.
    """
    if package not in PACKAGES or PACKAGES[package]['mode'] != 'portable':
        raise PackageInstallError('Offline repair is supported for portable OSS CAD Suite and KLayout only')
    directory = dependency_root() / package
    if not directory.is_dir() or not (directory / 'picads_install_receipt.json').is_file():
        raise PackageInstallError(f'No PICADS-managed extracted {package} found at {directory}; offline repair cannot proceed')
    progress = progress or (lambda msg: None)
    progress(f'Offline repair: reusing {directory}; no network access or extraction')
    return _register_managed(package, directory, progress, repaired=True)


def install_selected(packages: list[str], *, progress: Callable[[str], None] | None = None) -> dict:
    if not packages:
        raise PackageInstallError('Select at least one package')
    seen = set();results = {}
    for package in packages:
        if package in seen:continue
        seen.add(package)
        try:
            results[package] = install_package(package, progress=progress)
        except Exception as exc:
            results[package] = {'status':'FAILED','error':f'{type(exc).__name__}: {exc}'}
            if progress:progress(f'ERROR {package}: {exc}')
    return {'status':'PASS' if all(v['status']=='INSTALLED' for v in results.values()) else 'PARTIAL',
            'install_root':str(dependency_root()), 'packages':results}
