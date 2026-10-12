"""Fail-closed LibreLane handoff, target constraints and project-specific preflight.

A preflight is *not* a PDK qualification or a tool execution result. Only the
actual native flow can establish whether physical design artifacts were made.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import math
import os
import re
from typing import Any

IDENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


@dataclass
class PhysicalPreflight:
    status: str
    checks: dict[str, dict]
    physical_config: dict
    librelane_config: dict
    notes: list[str]

    def as_dict(self):
        return asdict(self)


def _number(value: Any, minimum: float, maximum: float, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"PHYSICAL.CONFIG_{key.upper()}: must be a finite number in [{minimum}, {maximum}]")
    return float(value)


def normalize_physical_settings(settings: dict, clocked: bool) -> tuple[dict, dict]:
    """Strictly translate PICADS physical YAML to LibreLane-compatible JSON.

    Only documented, explicitly supported physical knobs are accepted. Avoid
    blindly copying arbitrary YAML into a tool configuration with side effects.
    """
    if not isinstance(settings, dict):
        raise ValueError('PHYSICAL.CONFIG_FORMAT: physical must be a YAML mapping')
    allowed = {'enabled', 'pdk', 'pdk_root', 'std_cell_library', 'dockerized', 'timeout_s',
               'clock_period_ns', 'core_utilization', 'die_area_um', 'placement_density'}
    unknown = set(settings) - allowed
    if unknown:
        raise ValueError('PHYSICAL.CONFIG_UNKNOWN: unsupported physical key(s): ' + ', '.join(sorted(unknown)))
    for flag in ('enabled', 'dockerized'):
        if flag in settings and type(settings[flag]) is not bool:
            raise ValueError(f'PHYSICAL.CONFIG_{flag.upper()}: expected true/false')
    for label in ('pdk', 'std_cell_library'):
        if label in settings and (not isinstance(settings[label], str) or not IDENT.fullmatch(settings[label])):
            raise ValueError(f'PHYSICAL.CONFIG_{label.upper()}: expected a PDK/library identifier, not a path')
    if 'timeout_s' in settings and (type(settings['timeout_s']) is not int or not 60 <= settings['timeout_s'] <= 86400):
        raise ValueError('PHYSICAL.CONFIG_TIMEOUT: timeout_s must be an integer between 60 and 86400')
    if 'pdk_root' in settings and (not isinstance(settings['pdk_root'], str) or not settings['pdk_root'].strip()):
        raise ValueError('PHYSICAL.CONFIG_PDK_ROOT: expected a nonempty directory path')
    if clocked and 'clock_period_ns' not in settings:
        raise ValueError('PHYSICAL.CONFIG_CLOCK_PERIOD: clocked designs require explicit clock_period_ns')
    ll: dict[str, Any] = {}
    if 'clock_period_ns' in settings:
        ll['CLOCK_PERIOD'] = _number(settings['clock_period_ns'], 0.001, 1000000, 'clock_period_ns')
        if clocked:
            ll['CLOCK_PORT'] = 'clk'
    if 'core_utilization' in settings:
        ll['FP_CORE_UTIL'] = _number(settings['core_utilization'], 1, 90, 'core_utilization')
    if 'placement_density' in settings:
        ll['PL_TARGET_DENSITY_PCT'] = _number(settings['placement_density'], 1, 95, 'placement_density')
    if 'die_area_um' in settings:
        d = settings['die_area_um']
        if not isinstance(d, (tuple, list)) or len(d) != 4:
            raise ValueError('PHYSICAL.CONFIG_DIE_AREA: die_area_um must have four coordinates [x0,y0,x1,y1]')
        coords = [_number(v, 0, 1000000, 'die_area_um') for v in d]
        if coords[0] >= coords[2] or coords[1] >= coords[3]:
            raise ValueError('PHYSICAL.CONFIG_DIE_AREA: expected x0<x1 and y0<y1')
        ll['DIE_AREA'] = coords
        ll['FP_SIZING'] = 'absolute'
    if 'std_cell_library' in settings:
        ll['STD_CELL_LIBRARY'] = settings['std_cell_library']
    # PDK is selected by the command line; don't confuse it with PDK_ROOT.
    return dict(settings), ll


def physical_preflight(settings: dict, clocked: bool, *, check_tools: bool = True) -> PhysicalPreflight:
    checks: dict[str, dict] = {}
    notes: list[str] = []
    try:
        physical, ll = normalize_physical_settings(settings, clocked)
        checks['settings'] = {'status': 'PASS'}
    except ValueError as exc:
        checks['settings'] = {'status': 'FAIL', 'reason': str(exc)}
        return PhysicalPreflight('BLOCKED', checks, dict(settings) if isinstance(settings, dict) else {}, {}, notes)
    if not physical.get('enabled'):
        checks['enabled'] = {'status': 'BLOCKED', 'reason': 'physical.enabled must be true'}
    else:
        checks['enabled'] = {'status': 'PASS'}
    pdk = physical.get('pdk')
    if not pdk:
        checks['pdk'] = {'status': 'BLOCKED', 'reason': 'Set physical.pdk to an installed LibreLane PDK name'}
    else:
        checks['pdk'] = {'status': 'PASS', 'selected': pdk}
    root = physical.get('pdk_root') or os.environ.get('PDK_ROOT')
    if root:
        root_path = Path(root).expanduser().resolve()
        # Some PDK_ROOTs use versions/<hash>/<pdk>; leave that to LibreLane.
        checks['pdk_root'] = ({'status': 'PASS' if root_path.is_dir() else 'BLOCKED', 'path': str(root_path),
                               'reason': 'Directory does not exist' if not root_path.is_dir() else None})
        if root_path.is_dir() and pdk and not (root_path / pdk).is_dir():
            notes.append('PDK_ROOT does not have a direct PDK subdirectory; version-managed PDK installations may use another layout. LibreLane must resolve it.')
    else:
        checks['pdk_root'] = {'status': 'UNVERIFIED', 'reason': 'LibreLane may resolve its default PDK root; none selected explicitly'}
    if check_tools:
        from .dependencies import tool_status
        for name in ('yosys', 'librelane'):
            status = tool_status(name)
            checks[name] = {'status': 'PASS' if status['available'] else 'UNAVAILABLE',
                            'path': status['path'], 'reason': status['error']}
    if not clocked:
        notes.append('Combinational design: clock-based STA alone does not qualify input/output delay constraints')
    if any(v['status'] in ('FAIL', 'BLOCKED') for v in checks.values()):
        overall = 'BLOCKED'
    elif any(v['status'] in ('UNAVAILABLE', 'UNVERIFIED') for v in checks.values()):
        overall = 'PARTIAL'
    else:
        overall = 'READY_TO_ATTEMPT'
    notes.append('Preflight does not run synthesis, qualify the PDK, validate TFT behavior, or establish DRC/LVS/timing signoff.')
    return PhysicalPreflight(overall, checks, physical, ll, notes)


def artifact_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def make_physical_handoff(rtl: Path, config: Path, target: Path, *, pdk: str,
                          run_tag: str, tool_path: str | None = None) -> dict:
    """Provenance manifest for the exact RTL/config that a physical job consumes."""
    if not rtl.is_file() or not config.is_file():
        raise FileNotFoundError('Cannot record physical handoff before RTL and config exist')
    result = {'schema': 1, 'status': 'INPUTS_FROZEN', 'pdk': pdk, 'run_tag': run_tag,
              'qualified_for_manufacturing': False,
              'inputs': {
                  'rtl': {'path': str(rtl.resolve()), 'sha256': artifact_hash(rtl), 'bytes': rtl.stat().st_size},
                  'config': {'path': str(config.resolve()), 'sha256': artifact_hash(config), 'bytes': config.stat().st_size},
              }, 'librelane_executable': tool_path,
              'meaning': 'Input provenance only; no physical or electrical signoff implied'}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def verify_handoff_inputs(manifest: dict) -> bool:
    """Detect edits after a run was prepared (including identical-size edits)."""
    return all(Path(info['path']).is_file() and artifact_hash(info['path']) == info['sha256']
               for info in manifest['inputs'].values())
