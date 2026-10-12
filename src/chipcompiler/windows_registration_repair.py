"""Offline, read-only-for-packages registration repair on Windows.

Scans existing PICADS-managed OSS CAD Suite and existing KiCad installation
binaries without invoking WinGet, downloading archives or changing tool files.
"""
from __future__ import annotations

import json
from pathlib import Path

from .dependencies import register_tool
from .windows_installer import dependency_root, repair_package, PackageInstallError
from .windows_optional_install import _find_kicad_binaries


def repair_native_registration(root: Path | None = None) -> dict:
    root = root or dependency_root()
    output = {}
    try:
        result = repair_package('oss-cad-suite')
        output['oss-cad-suite']={'status':result['status'], 'tools':sorted(result['tools'])}
    except (OSError, ValueError, PackageInstallError) as exc:
        output['oss-cad-suite']={'status':'NOT_REPAIRED','reason':str(exc)}
    found = _find_kicad_binaries(root)
    registered={}
    for name, path in found.items():
        try:
            registered[name]=register_tool(name, path, 'app')['path']
        except (OSError,ValueError) as exc:
            output.setdefault('warnings',[]).append(f'{name}: {exc}')
    output['kicad']={'status':'REGISTERED' if len(registered)==3 else 'PARTIAL',
                     'tools':registered,
                     'not_found':[name for name in ('kicad','kicad-cli','pcbnew') if name not in registered],
                     'note':'No KiCad or OSS CAD Suite files were downloaded or reinstalled.'}
    return output


def main() -> int:
    result = repair_native_registration()
    print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
