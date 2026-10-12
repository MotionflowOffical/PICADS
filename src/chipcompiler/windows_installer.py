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
        'tools': ('yosys', 'iverilog', 'vvp', 'verilator', 'sby', 'z3'),
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
        'purpose': 'Install KiCad through WinGet; PCB editing only, not IC physical signoff',
        'mode': 'winget',
        'tools': ('kicad', 'kicad-cli'),
        'required': False,
        'source': 'https://www.kicad.org/download/windows/',
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
            managed = managed or bool((package_dir / 'picads_install_receipt.json').is_file() and states['kicad']['available'])
        if key == 'librelane':
            managed = (package_dir / 'backend_smoke_passed.txt').is_file()
        can_install = ((spec['mode'] == 'portable' and not package_dir.exists()) or
                       spec['mode'] in ('winget', 'guided-wsl'))
        rows.append({'id': key, 'name': spec['label'], 'purpose': spec['purpose'],
                     'mode': spec['mode'], 'required': spec['required'],
                     'source': spec['source'],
                     'available': all(s['available'] for s in states.values()),
                     'installed': managed,
                     'managed_path_exists': package_dir.exists(),
                     'can_install': can_install,
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


def _find_binary(root: Path, name: str) -> Path | None:
    preferred = (root / 'oss-cad-suite' / 'bin', root / 'bin', root)
    for folder in preferred:
        for alias in TOOLS[name]:
            candidate = folder / alias
            if candidate.is_file():return candidate
    # Extracted bundles may add a top-level wrapper directory.
    for candidate in root.glob('*/oss-cad-suite/bin/*'):
        if candidate.name.lower() in {a.lower() for a in TOOLS[name]} and candidate.is_file():return candidate
    if name == 'klayout':
        for candidate in root.rglob('klayout_app.exe'):
            if candidate.is_file():return candidate
    return None


def install_package(package: str, *, progress: Callable[[str], None] | None = None,
                    asset_override: dict | None = None) -> dict:
    """Install an explicitly selected Windows portable package. No execution of downloaded binaries.

    asset_override is reserved for offline tests; caller must provide expected
    source URL and archive and is not exposed in GUI/CLI.
    """
    progress = progress or (lambda msg: None)
    if package not in PACKAGES:raise PackageInstallError('Unknown package: '+package)
    if package in ('kicad', 'librelane'):
        from .windows_optional_install import install_kicad, stage_librelane
        root = dependency_root()
        return install_kicad(root, progress) if package == 'kicad' else stage_librelane(root, progress)
    if PACKAGES[package]['mode'] != 'portable':
        raise PackageInstallError(f'{package} has no approved native portable Windows package. See {PACKAGES[package]["source"]}')
    if sys.platform != 'win32' and asset_override is None:
        raise PackageInstallError('Native Windows packages can only be installed on Windows')
    asset = asset_override or (_oss_asset() if package == 'oss-cad-suite' else _klayout_asset())
    root = dependency_root()
    root.mkdir(parents=True, exist_ok=True)
    final = root / package
    if final.exists():
        raise PackageInstallError(f'{final} already exists. Existing installations are preserved. Remove it deliberately before reinstalling.')
    progress(f'Selected {package} ({asset["name"]}) from {asset["url"]}')
    with tempfile.TemporaryDirectory(prefix='.picads-install-', dir=root) as scratch:
        temp = Path(scratch)
        archive = temp / ('download.zip' if asset['name'].lower().endswith('.zip') else 'download.tar.gz')
        sha256 = _download(asset, archive, progress)
        extracted = temp / 'extracted';extracted.mkdir()
        count = _extract(archive, extracted, progress)
        found = {}
        # Essential binaries are mandatory; optional binaries remain discoverable.
        necessary = ('yosys', 'iverilog', 'vvp') if package == 'oss-cad-suite' else ('klayout',)
        for tool in PACKAGES[package]['tools']:
            executable = _find_binary(extracted, tool)
            if executable:found[tool] = executable.relative_to(extracted)
        missing = set(necessary) - set(found)
        if missing:raise PackageInstallError('Archive lacks required Windows executables: '+', '.join(sorted(missing)))
        receipt = {'package': package, 'upstream_url': asset['url'], 'release': asset['version'],
                   'sha256': sha256, 'upstream_digest_checked': bool(asset.get('digest')),
                   'files': count, 'resolved_tools': {t: str(v) for t,v in found.items()},
                   'note': 'Native Windows installer; no Linux runtime or installer scripts executed.'}
        (extracted / 'picads_install_receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
        extracted.replace(final)
    registered = {}
    for tool, relative in found.items():
        status = register_tool(tool, final / relative, 'app')
        registered[tool] = status['path']
    progress(f'Installed {package} in {final}, registered {len(registered)} executables')
    return {'status':'INSTALLED','package':package, 'directory':str(final), 'tools':registered, 'sha256':sha256,
            'upstream_digest_checked':bool(asset.get('digest'))}


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
