"""Discover PDK-authored KLayout layer properties for genuine named GDS layers.

GDS layer numbers are not self-describing. Never label arbitrary numeric layers
using a guessed mapping: load the selected PDK's .lyp file in KLayout instead.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import shutil
import xml.etree.ElementTree as ET


def valid_lyp(path: Path) -> bool:
    try:
        root=ET.parse(path).getroot()
        return root.tag in ('layer-properties','layer-properties-tabs')
    except (ET.ParseError,OSError):
        return False


def _local_candidates(project:Path, pdk_root:str|None, pdk:str):
    root=Path(project).resolve()
    candidates=[root/'build'/'latest'/'klayout_layers.lyp']
    if pdk_root and Path(pdk_root).is_dir():
        base=Path(pdk_root)/pdk/'libs.tech'/'klayout'
        candidates.extend([base/'tech'/f'{pdk}.lyp',base/'tech'/'sky130'/f'{pdk}.lyp',base/'tech'/'sky130'/'sky130.lyp',base/f'{pdk}.lyp'])
    return candidates


def acquire_lyp(project:Path, *, pdk='sky130A', pdk_root=None, distribution='Ubuntu', runner=None)->Path|None:
    """Use a local or WSL installed PDK palette, without downloading new dependencies.

    A WSL copy is stored under build/latest and is purely a viewer setting:
    it never modifies the GDS or technology/layout data.
    """
    root=Path(project).resolve()
    for path in _local_candidates(root,pdk_root,pdk):
        if path.is_file() and valid_lyp(path):return path
    if not pdk.lower().startswith('sky130') or not shutil.which('wsl.exe'):
        return None
    runner=runner or subprocess.run
    script=('for root in "$HOME/.ciel" "$HOME/.volare" "$HOME/.openlane"; do '
            '[ -d "$root" ] || continue; '
            'find "$root" -type f -name "sky130*.lyp" -print -quit 2>/dev/null; '
            'done')
    base=['wsl.exe','--distribution',distribution,'--exec']
    try:
        search=runner(base+['sh','-c',script],capture_output=True,timeout=20,check=False)
        if search.returncode!=0:return None
        paths=[x.strip() for x in search.stdout.decode('utf-8',errors='replace').splitlines() if x.strip()]
        if not paths:return None
        path=next((x for x in paths if x.lower().endswith('/'+pdk.lower()+'.lyp')),paths[0])
        contents=runner(base+['cat',path],capture_output=True,timeout=20,check=False)
        if contents.returncode!=0 or len(contents.stdout)>3_000_000 or len(contents.stdout)<100:return None
        try:
            doc=ET.fromstring(contents.stdout)
            if doc.tag not in ('layer-properties','layer-properties-tabs'):return None
        except ET.ParseError:return None
        output=root/'build'/'latest'/'klayout_layers.lyp'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(contents.stdout)
        return output
    except (OSError,subprocess.TimeoutExpired,UnicodeError):
        return None


def klayout_open_argv(executable:str, gds:Path, *, palette:Path|None=None)->list[str]:
    """Open real geometry even when a PDK palette covers only some layers.

    KLayout's ``-l`` option REPLACES the layer display list.  Without ``-lx``
    all GDS layers missing from the selected .lyp are silently hidden, which
    can produce an apparently empty layout despite a valid nonempty GDS file.
    ``-lx`` retains those missing layers with automatic display properties.
    The GDS is passed first as in the KLayout command-line documentation.
    """
    argv=[str(executable),str(gds)]
    if palette and valid_lyp(palette):
        argv.extend(['-l',str(palette),'-lx'])
    return argv
