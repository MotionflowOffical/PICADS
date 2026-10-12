"""Read-only PDK inventory and explicitly selected technology root.

Does not infer process validity, correct layer maps or foundry authorization.
It is a configuration preflight, not physical signoff.
"""
from __future__ import annotations
from pathlib import Path
import os
from .dependencies import read_settings, _atomic_save


def inspect_pdk(path: str | Path, max_files: int = 20000) -> dict:
    root = Path(path).expanduser().resolve()
    result = {'path': str(root), 'status': 'UNAVAILABLE', 'files_scanned': 0,
              'lef': [], 'liberty': [], 'gds': [], 'drc_candidates': [],
              'lvs_candidates': [], 'layer_map_candidates': [],
              'qualified_for_manufacturing': False}
    if not root.is_dir():
        result['reason'] = 'Directory does not exist.'
        return result
    if not 1 <= max_files <= 100000:
        raise ValueError('max_files must be within 1..100000')
    # Prevent traversing arbitrarily deep directory trees or expensive symlink cycles.
    for parent, dirs, files in os.walk(root, followlinks=False):
        depth = len(Path(parent).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and depth < 7)[:300]
        for name in sorted(files):
            result['files_scanned'] += 1
            if result['files_scanned'] > max_files:
                result['scan_truncated'] = True
                break
            relative = str((Path(parent) / name).relative_to(root))
            low = name.lower()
            if low.endswith(('.lef', '.lef.gz')):bucket = 'lef'
            elif low.endswith(('.lib', '.lib.gz')):bucket = 'liberty'
            elif low.endswith(('.gds', '.gdsii', '.gds.gz')):bucket = 'gds'
            elif low.endswith(('.lydrc', '.drc')) or ('drc' in low and low.endswith(('.tcl', '.yaml', '.json'))):bucket = 'drc_candidates'
            elif 'lvs' in low and low.endswith(('.tcl', '.setup', '.spice', '.yaml', '.json')):bucket = 'lvs_candidates'
            elif low.endswith(('.lyp', '.lym', '.map')):bucket = 'layer_map_candidates'
            else:continue
            if len(result[bucket]) < 20:result[bucket].append(relative)
        if result.get('scan_truncated'):break
    result['status'] = 'INVENTORIED' if result['lef'] and result['liberty'] else 'INCOMPLETE'
    result['reason'] = ('LEF and Liberty candidates detected; tool/PDK integration still unverified.'
                        if result['status'] == 'INVENTORIED' else
                        'No complete LEF+Liberty candidate set found within scan limits; analog-only PDKs may differ.')
    return result


def pdk_status() -> dict:
    path = read_settings().get('pdk_directory')
    return inspect_pdk(path) if path else {'status':'NOT_CONFIGURED','path':None,
        'qualified_for_manufacturing': False, 'reason':'No custom PDK folder selected.'}


def register_pdk(path: str | Path) -> dict:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'PDK directory does not exist: {root}')
    data = read_settings()
    data['pdk_directory'] = str(root)
    _atomic_save(data)
    return pdk_status()


def clear_pdk() -> dict:
    data=read_settings()
    data.pop('pdk_directory',None)
    _atomic_save(data)
    return pdk_status()
