"""Discover PDK-authored KLayout layer properties for genuine named GDS layers.

GDS layer numbers are not self-describing. Never label arbitrary numeric layers
using a guessed mapping: load the selected PDK's .lyp file in KLayout instead.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import shutil
import re
import json
import struct
from .sky130_gds_catalog import sky130_known_layers
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


# Display-only palette augmentation. The older -lx fix prevents missing
# geometry, but does not name missing layer/datatype pairs. Use only numbers
# verified in the SkyWater PDK CSV, and preserve original PDK display rules.
def gds_layer_pairs(gds: Path) -> set[tuple[int,int]]:
    """Read layer/datatype identifiers, not shapes, with bounded memory."""
    result: set[tuple[int,int]] = set()
    path = Path(gds)
    if not path.is_file():
        return result
    try:
        length = path.stat().st_size
        if length < 8:
            return result
        with path.open('rb') as f:
            current_layer = current_type = None
            in_element = False
            count = 0
            while f.tell() < length:
                record = f.read(4)
                if len(record) != 4:
                    return set()
                size, rtype, _ = struct.unpack('>HBB',record)
                if size < 4 or (size & 1) or size > length - f.tell() + 4:
                    return set()
                count += 1
                if count > 20_000_000:
                    return set()
                if rtype in (8,9,10,11,12,21,45):
                    in_element=True
                    current_layer=current_type=None
                elif in_element and rtype == 13 and size == 6:
                    current_layer = struct.unpack('>H',f.read(2))[0]
                    continue
                elif in_element and rtype in (14,22,42,46) and size == 6:
                    current_type = struct.unpack('>H',f.read(2))[0]
                    continue
                elif rtype == 17:
                    if current_layer is not None and current_type is not None:
                        result.add((current_layer,current_type))
                    in_element=False
                f.seek(size-4,1)
        return result
    except OSError:
        return set()


def named_sky130_palette(palette: Path|None, gds: Path, *, project: Path|None=None) -> tuple[Path|None, dict]:
    """Augment an installed PDK palette with verified missing SKY130 names.

    Generates a SIDE-CAR .lyp and a name-coverage report, never modifies
    the original PDK palette, GDS geometry, or manufacturer mask layers.
    """
    present = gds_layer_pairs(gds)
    known = sky130_known_layers()
    evidence = {'scheme':'SkyWater SKY130 official GDS layer/datatype names',
                'source':'https://github.com/google/skywater-pdk/blob/main/docs/rules/gds_layers.csv',
                'observed_pairs':len(present),
                'verified_pairs':{f'{a}/{b}':known[(a,b)] for (a,b) in sorted(present) if (a,b) in known},
                'unmapped_pairs':[f'{a}/{b}' for a,b in sorted(present) if (a,b) not in known],
                'geometry_unchanged':True}
    if not palette or not valid_lyp(palette):
        return palette,evidence
    tree = ET.parse(palette)
    root = tree.getroot()
    # Unsupported multi-tab views are left intact instead of flattening user
    # layer groups and changing their meaning or visibility.
    if root.tag != 'layer-properties':
        evidence['augmentation']='SKIPPED_MULTITAB_PALETTE'
        return palette,evidence
    existing = {}
    for node in root.iter('properties'):
        source = node.findtext('source') or ''
        match = re.match(r'^\s*(\d+)/(\d+)(?:@\S+)?\s*$', source)
        if match:
            existing[(int(match[1]),int(match[2]))] = node
    added=[]; renamed=[]
    for pair in sorted(present):
        if pair not in known:
            continue
        name=known[pair]
        if pair in existing:
            node=existing[pair]
            old=node.findtext('name') or ''
            if old.strip()=='' or old.strip() in (f'{pair[0]}/{pair[1]}',f'{pair[0]}/{pair[1]}@1'):
                child=node.find('name')
                if child is None:child=ET.SubElement(node,'name')
                child.text=name
                renamed.append(name)
            continue
        node=ET.SubElement(root,'properties')
        ET.SubElement(node,'name').text=name
        ET.SubElement(node,'source').text=f'{pair[0]}/{pair[1]}@1'
        ET.SubElement(node,'frame-color').text='#6489a7'
        ET.SubElement(node,'fill-color').text='#6489a7'
        ET.SubElement(node,'dither-pattern').text='I5'
        ET.SubElement(node,'visible').text='false' if name.endswith(('.label','.net','.pin')) else 'true'
        ET.SubElement(node,'width').text='1'
        added.append(name)
    output_dir = (Path(project)/'build'/'latest') if project else Path(palette).parent
    output_dir.mkdir(parents=True,exist_ok=True)
    output = output_dir/'klayout_layers_picads_named.lyp'
    tree.write(output,encoding='utf-8',xml_declaration=True)
    evidence.update({'augmentation':'COMPLETE','source_palette':str(palette),
                     'generated_palette':str(output),'added':added,'renamed':renamed})
    (output_dir/'klayout_layer_mapping.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    return output,evidence
