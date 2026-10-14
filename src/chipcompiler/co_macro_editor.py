"""Loss-limited, validated CO hard-macro coordinate writer.

Only the physical_macros section and its known location/mode declarations are
modified. Unrelated CO sections, source code, and comments remain untouched.
An atomic snapshot is created before writing; nothing is written if geometry or
source validation fails. Coordinates use microns, origin at physical lower left.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
import yaml

from .co_macros import (MacroConstraintError, allocate_macro_rectangles,
                        read_macro_constraints, _validate_2d_clearance,check_macro_placement_zones)
from .project import atomic_write


def coordinates_from_blocks(blocks, locations, *, min_coord=30):
    """Return actual-size rectangles from user positions, ensuring exact coverage."""
    names={b['instance'] for b in blocks}
    if set(locations)!=names:
        raise MacroConstraintError('CO.MACROS_GUI: coordinates must cover exactly the declared instances')
    placed=[]
    for b in blocks:
        xy=locations[b['instance']]
        if (not isinstance(xy,(tuple,list)) or len(xy)!=2 or
            any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or x<min_coord for x in xy)):
            raise MacroConstraintError(f'CO.MACROS_GUI: coordinates must be finite microns >= {min_coord}')
        w,h=b['size_um']
        placed.append({'name':b['name'],'module':b['module'],'instance':b['instance'],
                       'x_um':round(float(xy[0]),3),'y_um':round(float(xy[1]),3),
                       'width_um':w,'height_um':h})
    return placed


def update_co_macro_locations(text, locations):
    """Minimally rewrite physical_macros only; keep comments and unrelated YAML."""
    original=yaml.safe_load(text)
    if not isinstance(original,dict) or not isinstance(original.get('physical_macros'),dict):
        raise MacroConstraintError('CO.MACROS_GUI: no physical_macros section')
    declared=original['physical_macros'].get('blocks',[])
    if {b.get('instance') for b in declared}!=set(locations) or len(declared)!=len(locations):
        raise MacroConstraintError('CO.MACROS_GUI: CO blocks differ from editor')
    # Top-level YAML key; do not rewrite the rest of architecture.co.
    header=re.search(r'(?m)^physical_macros:\s*(?:#.*)?$',text)
    if header is None:
        raise MacroConstraintError('CO.MACROS_GUI: expected unindented physical_macros key')
    following=re.search(r'(?m)^[A-Za-z_][\w-]*\s*:',text[header.end():])
    stop=header.end()+following.start() if following else len(text)
    section=text[header.start():stop]
    # Replace mode while preserving trailing inline comments.
    match=re.search(r'(?m)^  placement:\s*(?:#.*)?$',section)
    if match:
        start=match.end()
        nxt=re.search(r'(?m)^  \w[\w-]*\s*:',section[start:])
        end=start+nxt.start() if nxt else len(section)
        chunk=section[start:end]
        if re.search(r'(?m)^    mode\s*:',chunk):
            chunk=re.sub(r'(?m)^(    mode\s*:\s*)\S+([^\n]*)$',r'\g<1>manual\g<2>',chunk,count=1)
        else:
            chunk='\n    mode: manual'+chunk if not chunk.startswith('\n') else '\n    mode: manual'+chunk
        section=section[:start]+chunk+section[end:]
    else:
        section=section.replace('physical_macros:', 'physical_macros:\n  placement:\n    mode: manual',1)
    block_marker=re.search(r'(?m)^  blocks:\s*(?:#.*)?$',section)
    if not block_marker:raise MacroConstraintError('CO.MACROS_GUI: expected blocks: sequence')
    body=section[block_marker.end():]
    markers=list(re.finditer(r'(?m)^    -\s+name\s*:',body))
    if len(markers)!=len(declared):
        raise MacroConstraintError('CO.MACROS_GUI: cannot safely identify every YAML block')
    chunks=[]
    for i,m in enumerate(markers):
        end=markers[i+1].start() if i+1<len(markers) else len(body)
        chunk=body[m.start():end]
        inst_match=re.search(r'(?m)^      instance:\s*([A-Za-z_]\w*)\s*(?:#.*)?$',chunk)
        if not inst_match or inst_match.group(1) not in locations:
            raise MacroConstraintError('CO.MACROS_GUI: unrecognized block instance')
        x,y=locations[inst_match.group(1)]
        new=f'location_um: [{round(float(x),3):g}, {round(float(y),3):g}]'
        if re.search(r'(?m)^      location_um\s*:',chunk):
            chunk=re.sub(r'(?m)^      location_um\s*:[^\n]*$', '      '+new,chunk,count=1)
        else:
            pos=chunk.rfind('\n')
            if pos<0:chunk+='\n      '+new+'\n'
            else:
                prefix=chunk[:pos];suffix=chunk[pos:]
                if prefix.endswith('\n'):chunk=prefix+'      '+new+suffix
                else:chunk=prefix+'\n      '+new+suffix
        chunks.append(chunk)
    section=section[:block_marker.end()]+body[:markers[0].start()]+''.join(chunks)
    updated=text[:header.start()]+section+text[stop:]
    check=yaml.safe_load(updated)['physical_macros']
    if check['placement']['mode']!='manual':
        raise MacroConstraintError('CO.MACROS_GUI: placement mode was not saved')
    for block in check['blocks']:
        if [round(x,3) for x in block['location_um']] != [round(float(x),3) for x in locations[block['instance']]]:
            raise MacroConstraintError('CO.MACROS_GUI: coordinate rewrite did not round-trip')
    return updated


def save_macro_locations(project_root, locations, measured_sizes=None):
    """Validate spacing and persist CO atomically with a file backup."""
    root=Path(project_root).resolve()
    path=root/'architecture.co'
    original=path.read_text(encoding='utf-8')
    full=yaml.safe_load(original)
    physical=yaml.safe_load((root/'chip.yaml').read_text(encoding='utf-8')).get('physical',{})
    co=read_macro_constraints(full['physical_macros'],root,physical,full.get('floorplan'))
    blocks=[]
    for b in co['blocks']:
        size=(measured_sizes or {}).get(b['instance'],[b['width'],b['height']])
        if len(size)!=2 or any(not isinstance(x,(float,int)) or x<=0 for x in size):
            raise MacroConstraintError('CO.MACROS_GUI: invalid measured dimensions')
        blocks.append({**b,'size_um':list(size)})
    rows=coordinates_from_blocks(blocks,locations,min_coord=0 if co['placement_region_um'] else 30)
    _validate_2d_clearance(rows,co['spacing'])
    check_macro_placement_zones(rows,region_um=co['placement_region_um'],
        stayouts_um=co['placement_stayouts_um'],halo_um=co['halo_um'])
    edited=update_co_macro_locations(original,locations)
    # Parse and revalidate the newly generated CO, including strict RTL binding.
    reread_doc=yaml.safe_load(edited)
    reread=read_macro_constraints(reread_doc['physical_macros'],root,physical,reread_doc.get('floorplan'))
    if reread['placement_mode']!='manual':raise MacroConstraintError('CO.MACROS_GUI: manual mode missing')
    backup=root/'.chipcompiler'/'floorplan_backups'
    backup.mkdir(parents=True,exist_ok=True)
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    atomic_write(backup/(stamp+'.architecture.co'),original)
    atomic_write(path,edited)
    return {'status':'SAVED_REQUIRES_LAYOUT_REBUILD','blocks':rows,'architecture_co':str(path),
            'note':'Coordinates are constraints, not proof of final placement; regenerate layout.'}
