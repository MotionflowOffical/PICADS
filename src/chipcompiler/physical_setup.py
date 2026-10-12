"""Explicit project-side enablement for PICADS to LibreLane SKY130 flows.

Unlike the dependency installer, this changes ONLY the selected project's
chip.yaml.  It never installs system software or edits the PDK.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from .project import atomic_write

_IDENT = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')


def configure_physical_project(root: Path, *, distribution: str = 'Ubuntu',
                               pdk: str = 'sky130A', period_ns: float = 20,
                               utilization: float = 35) -> dict:
    """Apply a user-requested WSL layout configuration, retaining a backup.

    The opt-in operation is not a physical-flow test; a PDK and working Docker
    daemon are required at execution time. Existing unrelated YAML settings
    remain in place. Original comments survive in the timestamped backup.
    """
    root = Path(root).resolve()
    source = root / 'chip.yaml'
    if not source.is_file() or source.is_symlink():
        raise ValueError('The selected project must contain a normal chip.yaml file')
    if not isinstance(distribution, str) or not distribution.strip() or any(c in distribution for c in '\r\n\0'):
        raise ValueError('Expected the exact, nonempty WSL distribution name')
    if not isinstance(pdk, str) or not _IDENT.fullmatch(pdk):
        raise ValueError('PDK name must be a simple PDK identifier')
    if type(period_ns) not in (int, float) or not 0.001 <= period_ns <= 1e6:
        raise ValueError('clock period must be between 0.001 and 1000000 ns')
    if type(utilization) not in (int, float) or not 1 <= utilization <= 90:
        raise ValueError('utilization must be between 1 and 90 percent')
    original = source.read_text(encoding='utf-8')
    data = yaml.safe_load(original)
    if not isinstance(data, dict):
        raise ValueError('chip.yaml must contain a YAML mapping')
    for field in ('physical', 'tools'):
        if field in data and not isinstance(data[field], dict):
            raise ValueError(f'Existing {field} settings must be a YAML mapping')
    physical = dict(data.get('physical') or {})
    # Preserve explicit user choices for advanced knobs; only set the minimum
    # parameters that the user requested to configure through the wizard.
    physical.update(enabled=True, pdk=pdk, clock_period_ns=float(period_ns),
                    core_utilization=float(utilization))
    tools = dict(data.get('tools') or {})
    tools.update(execution='wsl', wsl_distribution=distribution.strip())
    data['physical'] = physical
    data['tools'] = tools
    backup_dir = root / '.chipcompiler' / 'physical_config_backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_dir / f'chip_{stamp}_{uuid.uuid4().hex[:8]}.yaml'
    atomic_write(backup, original)
    try:
        atomic_write(source, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    except OSError:
        # Backup is intentionally retained for manual recovery if the target
        # write fails. atomic_write itself never truncates the old target.
        raise
    return {'status': 'CONFIGURED_NOT_VERIFIED', 'project': str(root),
            'configuration': str(source), 'original_backup': str(backup),
            'execution': 'wsl', 'wsl_distribution': distribution.strip(),
            'pdk': pdk,
            'next': 'Run picads physical-preflight PROJECT, then picads physical PROJECT; check build/latest/report.json.'}
