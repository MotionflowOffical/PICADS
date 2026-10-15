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
                        read_macro_constraints, _validate_2d_clearance,check_macro_placement_zones,
                        effective_macro_die)
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


def update_co_macro_locations(text, locations, die_size_um=None, placement_mode="manual"):
    """Minimally rewrite physical_macros only; keep comments and unrelated YAML."""
    if placement_mode not in ('manual','compact'):
        raise MacroConstraintError('CO.MACROS_GUI: editor only saves manual or compact placement')
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
            chunk=re.sub(r'(?m)^(    mode\s*:\s*)\S+([^\n]*)$',lambda m: m.group(1)+placement_mode+m.group(2),chunk,count=1)
        else:
            chunk='\n    mode: '+placement_mode+chunk
        section=section[:start]+chunk+section[end:]
    else:
        section=section.replace('physical_macros:', 'physical_macros:\n  placement:\n    mode: '+placement_mode,1)
    # Update only the placement setting, retaining all unrelated CO comments.
    if die_size_um is not None:
        if die_size_um != 'auto' and (not isinstance(die_size_um,(list,tuple)) or len(die_size_um)!=2):
            raise MacroConstraintError('CO.MACROS_DIE: invalid chip size selection')
        value=('auto' if die_size_um == 'auto' else
               f'[{float(die_size_um[0]):g}, {float(die_size_um[1]):g}]')
        match=re.search(r'(?m)^  placement:\s*(?:#.*)?$',section)
        if match is None:
            raise MacroConstraintError('CO.MACROS_GUI: missing placement section')
        start=match.end()
        next_key=re.search(r'(?m)^  [A-Za-z_]\w*\s*:',section[start:])
        end=start+next_key.start() if next_key else len(section)
        chunk=section[start:end]
        if re.search(r'(?m)^    die_size_um\s*:',chunk):
            chunk=re.sub(r'(?m)^    die_size_um\s*:[^\n]*$',f'    die_size_um: {value}',chunk,count=1)
        else:
            chunk='\n    die_size_um: '+value+chunk
        section=section[:start]+chunk+section[end:]
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
        if placement_mode=='compact':
            # Automatic packing must not retain manual block coordinates.
            chunk=re.sub(r'(?m)^      location_um\s*:[^\n]*(?:\n|$)', '',chunk)
        else:
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
    if check['placement']['mode']!=placement_mode:
        raise MacroConstraintError('CO.MACROS_GUI: placement mode was not saved')
    if die_size_um is not None:
        expected=('auto' if die_size_um=='auto' else [float(x) for x in die_size_um])
        if check['placement']['die_size_um'] != expected:
            raise MacroConstraintError('CO.MACROS_DIE: die-size rewrite did not round-trip')
    for block in check['blocks']:
        if placement_mode=='compact':
            if 'location_um' in block:
                raise MacroConstraintError('CO.MACROS_GUI: automatic mode retained a manual coordinate')
        elif [round(x,3) for x in block['location_um']] != [round(float(x),3) for x in locations[block['instance']]]:
            raise MacroConstraintError('CO.MACROS_GUI: coordinate rewrite did not round-trip')
    return updated


def save_macro_locations(project_root, locations, measured_sizes=None, die_size_um=None):
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
    selected_die=co['die_size_um'] if die_size_um is None else die_size_um
    die_metrics=effective_macro_die(rows,mode='manual',die_size_um=selected_die,halo_um=co['halo_um'])
    edited=update_co_macro_locations(original,locations,die_size_um=selected_die)
    # Parse and revalidate the newly generated CO, including strict RTL binding.
    reread_doc=yaml.safe_load(edited)
    reread=read_macro_constraints(reread_doc['physical_macros'],root,physical,reread_doc.get('floorplan'))
    if reread['placement_mode']!='manual':raise MacroConstraintError('CO.MACROS_GUI: manual mode missing')
    effective_macro_die(rows,mode='manual',die_size_um=reread['die_size_um'],halo_um=reread['halo_um'])
    backup=root/'.chipcompiler'/'floorplan_backups'
    backup.mkdir(parents=True,exist_ok=True)
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    atomic_write(backup/(stamp+'.architecture.co'),original)
    atomic_write(path,edited)
    return {'status':'SAVED_REQUIRES_LAYOUT_REBUILD','blocks':rows,'die':die_metrics,'architecture_co':str(path),
            'note':'Coordinates are constraints, not proof of final placement; regenerate layout.'}


def save_automatic_macro_placement(project_root, measured_sizes=None):
    """Switch CO to automatic compact placement and an area-minimized auto die.

    Manual block coordinates are removed only after the automatic placement
    candidate satisfies the same hard region/stayout/spacing constraints.
    """
    root=Path(project_root).resolve()
    path=root/'architecture.co'
    original=path.read_text(encoding='utf-8')
    doc=yaml.safe_load(original)
    physical=yaml.safe_load((root/'chip.yaml').read_text(encoding='utf-8')).get('physical',{})
    co=read_macro_constraints(doc['physical_macros'],root,physical,doc.get('floorplan'))
    blocks=[{**b,'size_um':list((measured_sizes or {}).get(b['instance'],
                                         [b['width'],b['height']]))} for b in co['blocks']]
    rows,_=allocate_macro_rectangles(blocks,co['packing_spacing'],mode='compact',
        region_um=co['placement_region_um'],stayouts_um=co['placement_stayouts_um'],
        halo_um=co['halo_um'],grid_um=co['placement_grid_um'])
    locations={r['instance']:[r['x_um'],r['y_um']] for r in rows}
    edited=update_co_macro_locations(original,locations,die_size_um='auto',placement_mode='compact')
    reread_doc=yaml.safe_load(edited)
    reread=read_macro_constraints(reread_doc['physical_macros'],root,physical,reread_doc.get('floorplan'))
    if reread['placement_mode']!='compact' or reread['die_size_um']!='auto':
        raise MacroConstraintError('CO.MACROS_GUI: automatic sizing did not survive round-trip')
    from datetime import datetime,timezone
    backup=root/'.chipcompiler'/'floorplan_backups'
    backup.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    atomic_write(backup/(stamp+'.architecture.co'),original)
    atomic_write(path,edited)
    return {'status':'AUTO_PLACEMENT_SAVED_REQUIRES_LAYOUT_REBUILD',
            'planned_blocks':rows,'die':effective_macro_die(rows,mode='compact'),
            'architecture_co':str(path)}
