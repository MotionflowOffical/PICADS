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


def gds_layer_pairs(gds: Path) -> set[tuple[int,int]]:
    """Inventory exact layer/datatype pairs from a valid GDS, including labels.

    Process streaming records without loading or modifying any geometry.
    """
    present=set()
    gds=Path(gds)
    try:
        length=gds.stat().st_size
        with gds.open('rb') as handle:
            active=False;layer=None;purpose=None;records=0
            while handle.tell()<length:
                head=handle.read(4)
                if len(head)!=4:return set()
                size,kind,dtype=struct.unpack('>HBB',head)
                if size<4 or size%2 or handle.tell()+size-4>length:return set()
                payload=handle.read(size-4)
                records+=1
                if records>25_000_000:return set()
                if kind in (8,9,10,11,12,21,45):
                    active=True;layer=purpose=None
                elif active and kind==13 and len(payload)==2:
                    layer=struct.unpack('>H',payload)[0]
                elif active and kind in (14,22,42,46) and len(payload)==2:
                    purpose=struct.unpack('>H',payload)[0]
                elif kind==17:
                    if active and layer is not None and purpose is not None:
                        present.add((layer,purpose))
                    active=False
        return present
    except (OSError,struct.error):
        return set()


def _color_hints(palette: Path|None):
    """Extract optional display colors from PDK without trusting incorrect layer sources."""
    colors={}
    if palette and valid_lyp(palette):
        root=ET.parse(palette).getroot()
        for node in root.iter('properties'):
            name=(node.findtext('name') or '').lower().replace(' ','').replace('_','')
            name=name.split('.')[0]
            if name.startswith('metal'):name='met'+name[5:]
            if name in ('localinterconnect','li'):name='li1'
            if name in ('p+sd','p+sdiff'):name='diff'
            frame=node.findtext('frame-color')
            fill=node.findtext('fill-color')
            if frame or fill:colors.setdefault(name,(frame or fill,fill or frame))
    return colors


def exact_gds_palette(project:Path, gds:Path, *, palette:Path|None=None, pdk='sky130A') -> tuple[Path|None,dict]:
    """Create a KLayout layer table matching ONLY actual GDS pairs.

    The original PDK palette sometimes advertises layer entries with missing
    or non-matching datatype IDs. KLayout then shows named empty rows alongside
    active anonymous rows. Rebuilding the *viewer* table from exact observed
    pairs makes name selection and visibility toggles control real geometry.
    No GDS files or PDK data are modified.
    """
    pairs=gds_layer_pairs(gds)
    if not pairs:
        return None,{'status':'NO_GDS_LAYERS','gds':str(gds)}
    known=sky130_known_layers() if pdk.lower().startswith('sky130') else {}
    colors=_color_hints(palette)
    document=ET.Element('layer-properties')
    mapping=[]
    for layer,datatype in sorted(pairs):
        full=known.get((layer,datatype))
        name=full if full else f'GDS {layer}/{datatype} (unmapped)'
        base=full.split('.')[0] if full else ''
        frame,fill=colors.get(base,('#788fa1','#788fa1'))
        entry=ET.SubElement(document,'properties')
        ET.SubElement(entry,'name').text=name
        ET.SubElement(entry,'source').text=f'{layer}/{datatype}@1'
        ET.SubElement(entry,'frame-color').text=frame
        ET.SubElement(entry,'fill-color').text=fill
        ET.SubElement(entry,'dither-pattern').text='I5'
        ET.SubElement(entry,'width').text='1'
        hidden=full is not None and full.endswith(('.label','.pin','.net','.probe','.block','.boundary'))
        ET.SubElement(entry,'visible').text='false' if hidden else 'true'
        mapping.append({'layer':layer,'datatype':datatype,'name':name,'source':f'{layer}/{datatype}@1',
                        'visible_by_default':not hidden,'verified':full is not None})
    destination=Path(project)/'build'/'latest'
    destination.mkdir(parents=True,exist_ok=True)
    output=destination/'klayout_layers_picads_exact.lyp'
    ET.ElementTree(document).write(output,encoding='utf-8',xml_declaration=True)
    evidence={'status':'EXACT_PAIRS','gds':str(gds),'palette':str(output),
              'observed_pairs':len(pairs),'mapped_pairs':sum(i['verified'] for i in mapping),
              'entries':mapping,'geometry_unchanged':True,
              'note':'Every palette row uses an exact layer/datatype pair present in the selected GDS. Unmapped pairs remain labelled numerically.'}
    (destination/'klayout_layer_mapping.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    return output,evidence
