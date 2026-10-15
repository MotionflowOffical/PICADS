"""Native CO hard-macro floorplanning for an explicitly modular RTL implementation.

This backend is intentionally *not* a source-to-gates attribution algorithm.  It
uses real named RTL instances and separately hardens their physical views.  An
independent Python DLS reference is not automatically equivalent to these RTL
sources; the caller must record that verification boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from html import escape

from .project import safe_path, atomic_write
from .physical import inspect_librelane
from .physical_flow import artifact_hash
from .tools import run_external

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

class MacroConstraintError(ValueError):
    pass


def _id(value, label):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise MacroConstraintError(f'CO.MACROS_IDENTIFIER: {label} must be a Verilog identifier')
    return value


def _positive(v, name, low=0, high=100000):
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not low < v <= high:
        raise MacroConstraintError(f'CO.MACROS_NUMBER: {name} must be greater than {low}, at most {high}')
    return float(v)


def _load_rtl(root, value, label):
    if not isinstance(value, str) or not value.endswith('.v'):
        raise MacroConstraintError(f'CO.MACROS_PATH: {label} must be a project-relative Verilog .v file')
    try:
        file = safe_path(root, value)
    except ValueError as e:
        raise MacroConstraintError(f'CO.MACROS_PATH: {e}') from e
    if not file.is_file():
        raise MacroConstraintError(f'CO.MACROS_PATH: missing {label}: {value}')
    return file


def _placement_rect(value, label):
    """Physical x0,y0,x1,y1 in micrometres; not a screen-space region."""
    if (not isinstance(value, (list, tuple)) or len(value) != 4 or
        any(isinstance(v, bool) or not isinstance(v, (int, float)) or
            not math.isfinite(v) or v < 0 for v in value) or
        value[2] <= value[0] or value[3] <= value[1]):
        raise MacroConstraintError(f'CO.MACROS_ZONE: {label} must be [x0,y0,x1,y1] in um')
    return [float(v) for v in value]


def check_macro_placement_zones(rows, *, region_um=None, stayouts_um=(), halo_um=0):
    """Shared safety rule used by CO layout synthesis and the drag editor.

    A stay-out is an exclusion rectangle; its halo must be clear of the
    entire macro body. No successful save or physical build can bypass it.
    """
    for row in rows:
        x,y=row['x_um'],row['y_um']
        x2,y2=x+row['width_um'],y+row['height_um']
        if region_um is not None:
            rx,ry,rx2,ry2=region_um
            if x < rx-1e-6 or y < ry-1e-6 or x2 > rx2+1e-6 or y2 > ry2+1e-6:
                raise MacroConstraintError(f'CO.MACROS_REGION: {row["instance"]} is outside required placement region')
        for index,(kx,ky,kx2,ky2) in enumerate(stayouts_um):
            # A diagonal escape is permitted only when the expanded rectangles
            # no longer overlap in either Cartesian dimension.
            if x < kx2+halo_um-1e-6 and x2 > kx-halo_um+1e-6 and \
               y < ky2+halo_um-1e-6 and y2 > ky-halo_um+1e-6:
                raise MacroConstraintError(f'CO.MACROS_STAYOUT: {row["instance"]} intersects stay-out #{index+1} (halo {halo_um:g} um)')
    return True


def read_macro_constraints(raw, project_root, physical, floorplan=None):
    """Read strict, reusable CO specification without invoking EDA tools."""
    if not isinstance(raw, dict) or raw.get('enabled') is not True:
        raise MacroConstraintError('CO.MACROS_CONFIG: physical_macros.enabled must be true')
    allowed = {'enabled', 'enforcement', 'top_module', 'top_rtl', 'blocks', 'spacing', 'halo_um', 'placement', 'auto_core_utilization'}
    if set(raw) - allowed:
        raise MacroConstraintError('CO.MACROS_UNKNOWN: ' + ', '.join(sorted(set(raw)-allowed)))
    if raw.get('enforcement') != 'required':
        raise MacroConstraintError('CO.MACROS_ENFORCEMENT: this backend requires enforcement: required')
    if not physical.get('enabled') or not physical.get('pdk'):
        raise MacroConstraintError('CO.MACROS_PHYSICAL: physical.enabled and physical.pdk required')
    top = _id(raw.get('top_module'), 'top_module')
    top_rtl = _load_rtl(project_root, raw.get('top_rtl'), 'top_rtl')
    top_body = top_rtl.read_text(encoding='utf-8')
    if not re.search(r'\bmodule\s+'+re.escape(top)+r'\s*\(', top_body):
        raise MacroConstraintError('CO.MACROS_TOP: top RTL does not declare '+top)
    auto_util = _positive(raw.get('auto_core_utilization', 45), 'auto_core_utilization', low=0, high=90)
    spacing = raw.get('spacing', {})
    if not isinstance(spacing, dict) or set(spacing)-{'min_um','preferred_um','max_um','pdn_min_um'}:
        raise MacroConstraintError('CO.MACROS_SPACING: require min_um, preferred_um and max_um')
    minimum = _positive(spacing.get('min_um', 5), 'spacing.min_um')
    preferred = _positive(spacing.get('preferred_um', 10), 'spacing.preferred_um')
    maximum = _positive(spacing.get('max_um', 60), 'spacing.max_um')
    if not minimum <= preferred <= maximum:
        raise MacroConstraintError('CO.MACROS_SPACING: require min <= preferred <= max')
    pdn_min = None
    if 'pdn_min_um' in spacing:
        pdn_min = _positive(spacing['pdn_min_um'], 'spacing.pdn_min_um')
        if pdn_min < minimum or pdn_min > maximum:
            raise MacroConstraintError('CO.MACROS_PDN_SPACING: pdn_min_um must be between min_um and max_um')
    halo = _positive(raw.get('halo_um', 5), 'halo_um', low=-1)
    placement = raw.get('placement', {'mode':'compact'})
    if not isinstance(placement, dict) or set(placement)-{'mode','region_um','stayouts_um','grid_um','die_size_um'}:
        raise MacroConstraintError('CO.MACROS_PLACEMENT: expected placement: {mode: compact|row|manual}')
    die_spec = placement.get('die_size_um', 'auto')
    if die_spec != 'auto':
        if not isinstance(die_spec, list) or len(die_spec) != 2:
            raise MacroConstraintError('CO.MACROS_DIE: placement.die_size_um must be auto or [width, height]')
        die_spec = [_positive(v, 'placement.die_size_um', low=20, high=100000)
                    for v in die_spec]
    grid_um = _positive(placement.get('grid_um', 0), 'placement.grid_um', low=-1, high=25)
    placement_mode = placement.get('mode', 'compact')
    if placement_mode not in ('compact', 'row', 'manual'):
        raise MacroConstraintError('CO.MACROS_PLACEMENT: mode must be compact, row or manual')
    region = _placement_rect(placement['region_um'],'placement.region_um') if 'region_um' in placement else None
    stayouts = placement.get('stayouts_um', [])
    if not isinstance(stayouts,list):
        raise MacroConstraintError('CO.MACROS_ZONE: placement.stayouts_um must be a list')
    stayouts = [_placement_rect(v,f'placement.stayouts_um[{i}]') for i,v in enumerate(stayouts)]
    # Reuse existing mandatory CO physical floorplan keepouts. These are
    # placement exclusions and must not silently become only painted guides.
    if isinstance(floorplan,dict):
        for entry in floorplan.get('keepouts',[]):
            if (isinstance(entry,dict) and entry.get('kind')=='hard' and
                    entry.get('enforcement')=='required'):
                stayouts.append(_placement_rect(entry.get('bounds_um'),
                    'floorplan.keepouts.'+str(entry.get('name','unnamed'))))
    if region is not None:
        for i,(x,y,x2,y2) in enumerate(stayouts):
            if x < region[0] or y < region[1] or x2 > region[2] or y2 > region[3]:
                raise MacroConstraintError(f'CO.MACROS_ZONE: stay-out #{i+1} extends outside placement region')
    blocks = raw.get('blocks')
    if not isinstance(blocks, list) or len(blocks) < 2 or len(blocks) > 32:
        raise MacroConstraintError('CO.MACROS_BLOCKS: expected 2..32 real blocks')
    instances = set(); modules = set(); defined=[]
    for index, b in enumerate(blocks):
        if not isinstance(b, dict) or set(b)-{'name','module','instance','rtl','die_size_um','preview_size_um','core_utilization','clock_port','location_um'}:
            raise MacroConstraintError(f'CO.MACROS_BLOCK: invalid block definition at index {index}')
        name = _id(b.get('name'), 'block.name')
        mod = _id(b.get('module'), 'block.module')
        inst = _id(b.get('instance'), 'block.instance')
        if inst in instances or mod in modules:
            raise MacroConstraintError('CO.MACROS_DUPLICATE: module and instance names must be unique')
        instances.add(inst);modules.add(mod)
        rtl = _load_rtl(project_root, b.get('rtl'), f'{name}.rtl')
        body = rtl.read_text(encoding='utf-8')
        match = re.search(r'\bmodule\s+'+re.escape(mod)+r'\s*\((.*?)\)\s*;', body, re.S)
        if match is None:
            raise MacroConstraintError('CO.MACROS_RTL: missing ANSI port header for '+mod)
        # Avoid silently treating a textual mention as an instance.
        if not re.search(r'\b'+re.escape(mod)+r'\s+'+re.escape(inst)+r'\s*\(', top_body):
            raise MacroConstraintError(f'CO.MACROS_BINDING: instance {mod} {inst} not found in {top_rtl.name}')
        dimensions = b.get('die_size_um')
        auto_die = dimensions == 'auto'
        if auto_die:
            # Editor-only estimate before synthesis has produced an actual LEF.
            # The physical macro always uses the LEF dimensions emitted by
            # LibreLane's relative floorplanner, NOT this preview estimate.
            preview = b.get('preview_size_um', [160, 160])
            if not isinstance(preview, list) or len(preview) != 2:
                raise MacroConstraintError(f'CO.MACROS_DIMENSIONS: {name}.preview_size_um requires [width,height]')
            width,height = (_positive(v, f'{name}.preview_size_um', low=20, high=10000) for v in preview)
        else:
            if 'preview_size_um' in b:
                raise MacroConstraintError(f'CO.MACROS_DIMENSIONS: {name}.preview_size_um is only valid with die_size_um: auto')
            if not isinstance(dimensions, list) or len(dimensions) != 2:
                raise MacroConstraintError(f'CO.MACROS_DIMENSIONS: {name} requires [width,height] or auto')
            width,height = (_positive(v, f'{name}.die_size_um', low=20, high=10000) for v in dimensions)
        utilization = _positive(b.get('core_utilization', auto_util), f'{name}.core_utilization',low=0,high=90)
        clock = b.get('clock_port', 'clk' if re.search(r'\binput\s+(?:wire\s+)?clk\b', match.group(1)) else None)
        if clock is not None:
            _id(clock, f'{name}.clock_port')
        location = b.get('location_um')
        if location is not None:
            if not isinstance(location, list) or len(location)!=2 or any(
                isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in location
            ):
                raise MacroConstraintError(f'CO.MACROS_LOCATION: {name}.location_um must be [x,y] nonnegative microns')
            location=[float(v) for v in location]
        defined.append({'name':name,'module':mod,'instance':inst,'rtl':rtl,'ports':match.group(1),
                        'width':width,'height':height,'die_mode':'auto' if auto_die else 'fixed',
                        'core_utilization':utilization,'core_utilization_explicit':'core_utilization' in b,
                        'clock':clock,'location_um':location})
    if placement_mode=='manual' and any(b['location_um'] is None for b in defined):
        raise MacroConstraintError('CO.MACROS_LOCATION: manual placement requires location_um for every block')
    if placement_mode!='manual' and any(b['location_um'] is not None for b in defined):
        raise MacroConstraintError('CO.MACROS_LOCATION: location_um requires placement.mode: manual')
    # OpenROAD's met1 channel repair can fail when the nominal gap between
    # multiple SKY130 hard macros leaves only ~15 um after placement halos.
    # For four or more automatically packed macros, reserve 60 um between
    # macro bodies, subject to the user's hard maximum. Explicit manual
    # coordinates are never moved. pdn_min_um overrides this heuristic.
    # This is placement-risk mitigation, NOT evidence that PDN will pass.
    pdn_target = (pdn_min if pdn_min is not None else
                  (60.0 if physical.get('pdk','').lower() == 'sky130a' and len(defined) >= 4 else 0.0))
    pack_preferred = min(maximum, max(preferred, pdn_target))
    packing_spacing = {'min_um': minimum, 'preferred_um': pack_preferred, 'max_um': maximum}
    return {'top':top,'top_rtl':top_rtl,'blocks':defined,'spacing':{'min_um':minimum,'preferred_um':preferred,'max_um':maximum},
            'halo_um':halo,'placement_mode':placement_mode,'placement_region_um':region,'placement_stayouts_um':stayouts,
            'packing_spacing':packing_spacing,'pdn_placement_target_um':pdn_target,'placement_grid_um':grid_um,'die_size_um':die_spec,
            'auto_core_utilization':auto_util}


def read_lef_size(path, module):
    data=Path(path).read_text(encoding='utf-8',errors='replace')
    section=re.search(r'\bMACRO\s+'+re.escape(module)+r'\b(.*?)\bEND\s+'+re.escape(module)+r'\b',data,re.S)
    if not section:raise MacroConstraintError('CO.MACROS_LEF: missing MACRO '+module)
    size=re.search(r'\bSIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;',section.group(1))
    if not size:raise MacroConstraintError('CO.MACROS_LEF: missing SIZE for '+module)
    return [_positive(float(size.group(i)),module+'.LEF_SIZE') for i in (1,2)]


def inspect_macro_lef_power(path, module):
    """Require physically exposed VPWR/VGND macro LEF pins before integration.

    The power hookups in PDN_MACRO_CONNECTIONS connect nets, not metal geometry.
    Both POWER and GROUND pins must exist as LEF PORT geometry, or a top-level
    PDN grid cannot reliably supply the separately hardened macro.
    """
    data=Path(path).read_text(encoding='utf-8',errors='replace')
    macro=re.search(r'\bMACRO\s+'+re.escape(module)+r'\b(.*?)\bEND\s+'+re.escape(module)+r'\b',data,re.S|re.I)
    if not macro:
        raise MacroConstraintError('CO.MACROS_LEF_POWER: missing macro LEF definition for '+module)
    pins={}
    for pin,usage in [('VPWR','POWER'),('VGND','GROUND')]:
        m=re.search(r'\bPIN\s+'+pin+r'\b(.*?)\bEND\s+'+pin+r'\b',macro.group(1),re.S|re.I)
        if not m or not re.search(r'\bUSE\s+'+usage+r'\s*;',m.group(1),re.I):
            raise MacroConstraintError(f'CO.MACROS_LEF_POWER: {module} lacks {pin} LEF pin USE {usage}')
        if not re.search(r'\bPORT\b',m.group(1),re.I) or not re.search(r'\bRECT\b',m.group(1),re.I):
            raise MacroConstraintError(f'CO.MACROS_LEF_POWER: {module} {pin} has no metal PORT rectangle')
        pins[pin]={'use':usage,'layers':list(dict.fromkeys(re.findall(r'\bLAYER\s+(\w+)\s*;',m.group(1),re.I)))}
        if not pins[pin]['layers']:
            raise MacroConstraintError(f'CO.MACROS_LEF_POWER: {module} {pin} has no routing layer')
    return pins


def final_view(run, subdir, module, suffix):
    folder = Path(run)/'final'/subdir
    candidates = sorted(p for p in folder.rglob('*') if p.is_file() and p.name.endswith(suffix) and p.stat().st_size>0) if folder.is_dir() else []
    preferred = [p for p in candidates if p.name.startswith(module+'.')]
    if len(preferred)==1:return preferred[0]
    if len(candidates)==1:return candidates[0]
    raise MacroConstraintError(f'CO.MACROS_VIEW: expected one {module} {subdir} view in {run}, found {len(candidates)}')


def _rect_gap(a, b):
    """Minimum Euclidean edge clearance of two axis-aligned macro rectangles."""
    dx=max(0, a['x_um']-b['x_um']-b['width_um'], b['x_um']-a['x_um']-a['width_um'])
    dy=max(0, a['y_um']-b['y_um']-b['height_um'], b['y_um']-a['y_um']-a['height_um'])
    return math.hypot(dx,dy)


def _validate_2d_clearance(rows, spacing):
    low=spacing['min_um']; high=spacing['max_um']
    for i,a in enumerate(rows):
        neighbors=[]
        for j,b in enumerate(rows):
            if i==j:continue
            gap=_rect_gap(a,b)
            if gap < low-0.001:
                raise MacroConstraintError(f'CO.MACROS_SPACING: {a["instance"]} and {b["instance"]} clearance {gap:.3f} um below minimum {low:.3f} um')
            neighbors.append(gap)
        if neighbors and min(neighbors)>high+0.001:
            raise MacroConstraintError(f'CO.MACROS_SPACING: {a["instance"]} has no other macro within maximum {high:.3f} um')


def _dimensioned_rect(block, x, y):
    w,h=block['size_um']
    return {'name':block['name'],'module':block['module'],'instance':block['instance'],
            'x_um':round(x,4),'y_um':round(y,4),'width_um':w,'height_um':h}


def autosized_macro_die(rows, *, margin_um=30.0):
    """Return a die sized from *actual placed* hard-macro bounding boxes.

    CO placement.region_um is the permitted macro placement extent, not an
    implicit die size. Area outside the macro bodies is needed for the top
    wrapper, pins, power grid and routing; this statistic is NOT cell density.
    The margin is intentionally retained around the outermost macro geometry.
    """
    if not rows:
        raise MacroConstraintError('CO.MACROS_DIE: no placed macros')
    margin = _positive(margin_um, 'die.margin_um', low=0)
    right = max(r['x_um'] + r['width_um'] for r in rows)
    upper = max(r['y_um'] + r['height_um'] for r in rows)
    die = [round(right + margin, 2), round(upper + margin, 2)]
    macro_area = sum(r['width_um'] * r['height_um'] for r in rows)
    die_area = die[0] * die[1]
    if die_area <= 0:
        raise MacroConstraintError('CO.MACROS_DIE: invalid die geometry')
    return {
        'die_area_um': [0.0, 0.0, *die],
        'width_um': die[0], 'height_um': die[1],
        'macro_area_um2': round(macro_area, 3),
        'macro_coverage_percent': round(100.0 * macro_area / die_area, 2),
        'reserved_for_routing_pdn_and_top_cells_percent': round(100.0 * (1 - macro_area / die_area), 2),
        'sizing_basis': 'placed_macro_bounds_plus_margin',
        'margin_um': margin,
        'meaning': 'Geometric hard-macro footprint only, not utilization of standard cells or verified routability',
    }


def effective_macro_die(rows, *, mode='compact', die_size_um='auto', halo_um=0, margin_um=30.0):
    """Die width/height for the real layout, not the permissive CO region.

    Automatic mode always takes the smallest envelope for the CURRENT legal
    placement, with its reserved external margin. Manual explicit dimensions
    are mandatory limits; they must contain macro geometry plus core/PDN halo.
    """
    computed = autosized_macro_die(rows, margin_um=margin_um)
    if mode != 'manual' or die_size_um == 'auto':
        return computed
    if not isinstance(die_size_um,(tuple,list)) or len(die_size_um)!=2:
        raise MacroConstraintError('CO.MACROS_DIE: expected manual [width,height]')
    w,h=map(float,die_size_um)
    if not all(math.isfinite(v) and v>20 for v in (w,h)):
        raise MacroConstraintError('CO.MACROS_DIE: explicit chip dimensions must exceed 20 um')
    # The generated CORE_AREA inset is ten micrometres. It must contain the
    # macro body and its requested halo; a die-size field cannot waive that.
    inset = 10.0 + float(halo_um)
    for r in rows:
        if (r['x_um'] < inset-1e-6 or r['y_um'] < inset-1e-6 or
            r['x_um']+r['width_um'] > w-inset+1e-6 or
            r['y_um']+r['height_um'] > h-inset+1e-6):
            raise MacroConstraintError(
                f'CO.MACROS_DIE: {r["instance"]} does not fit in {w:g} x {h:g} um die '
                f'with {inset:g} um core/halo edge clearance')
    area=w*h
    return {**computed,'die_area_um':[0.,0.,round(w,3),round(h,3)],
            'width_um':round(w,3),'height_um':round(h,3),
            'macro_coverage_percent':round(100*computed['macro_area_um2']/area,2),
            'reserved_for_routing_pdn_and_top_cells_percent':round(100*(1-computed['macro_area_um2']/area),2),
            'sizing_basis':'manual_explicit_die',
            'meaning':'User-defined die bounding box validated against physical core/halo; routing/signoff still unverified'}

def allocate_macro_rectangles(blocks, spacing, *, margin=30, mode='row', region_um=None, stayouts_um=(), halo_um=0, grid_um=0):
    """Place real LEF-sized hard macros with selectable CO row/compact/manual mode.

    Compact mode enumerates deterministic horizontal and vertical shelf layouts
    in multiple orders and selects a balanced minimum-envelope arrangement.
    This is a floorplan heuristic, not a claim of globally optimal routing.
    The actual DEF is checked after LibreLane against the same coordinates.
    """
    if not blocks:
        raise MacroConstraintError('CO.MACROS_BLOCKS: cannot place empty block list')
    gap=spacing['preferred_um']

    def die(rows):
        info = autosized_macro_die(rows, margin_um=margin)
        return [info['width_um'], info['height_um']]

    if mode=='manual':
        rows=[]
        for b in blocks:
            xy=b.get('location_um')
            if xy is None or (region_um is None and min(xy)<margin-1e-6):
                raise MacroConstraintError('CO.MACROS_LOCATION: manual macro coordinates must respect the required die border')
            rows.append(_dimensioned_rect(b,*xy))
        _validate_2d_clearance(rows,spacing)
        check_macro_placement_zones(rows,region_um=region_um,stayouts_um=stayouts_um,halo_um=halo_um)
        return rows,die(rows)

    if mode=='row':
        x=float(margin);rows=[]
        for b in blocks:
            rows.append(_dimensioned_rect(b,x,float(margin)))
            x+=b['size_um'][0]+gap
        _validate_2d_clearance(rows,spacing)
        check_macro_placement_zones(rows,region_um=region_um,stayouts_um=stayouts_um,halo_um=halo_um)
        return rows,die(rows)

    if mode!='compact':
        raise MacroConstraintError('CO.MACROS_PLACEMENT: unsupported mode '+str(mode))

    # Candidate positions are deterministic and reproduce on all platforms.
    # Try height-first and width-first shelves. A 2D solution is selected when
    # its envelope/perimeter improves on the old single-row approach.
    import itertools
    n=len(blocks)
    orderings=list(itertools.permutations(range(n))) if n<=6 else [
        tuple(range(n)),tuple(sorted(range(n),key=lambda i:-blocks[i]['size_um'][1])),
        tuple(sorted(range(n),key=lambda i:-blocks[i]['size_um'][0])),
        tuple(sorted(range(n),key=lambda i:-blocks[i]['size_um'][0]*blocks[i]['size_um'][1]))]
    max_span=sum(max(b['size_um']) for b in blocks)+(n-1)*gap
    thresholds=set()
    for o in orderings:
        for axis in (0,1):
            accum=0.0
            for index in o:
                accum+=(blocks[index]['size_um'][axis]+(gap if accum else 0))
                thresholds.add(round(accum,4))
    # Limit candidate enumeration for unusually large RTL assemblies.
    threshold_list=sorted(thresholds)
    if len(threshold_list)>80:
        threshold_list=threshold_list[::max(1,len(threshold_list)//80)]
    best=None
    for order in orderings:
        for vertical in (False,True):
            for limit in threshold_list:
                major=minor=shelf_height=0.0; output={}
                for index in order:
                    b=blocks[index]
                    width,height=b['size_um']
                    item_major=height if vertical else width
                    item_minor=width if vertical else height
                    if major and major+gap+item_major>limit+1e-6:
                        minor+=shelf_height+gap;major=shelf_height=0.0
                    major_offset=major+(gap if major else 0.0)
                    x=minor if vertical else major_offset
                    y=major_offset if vertical else minor
                    output[index]=_dimensioned_rect(b,x+margin,y+margin)
                    major=major_offset+item_major
                    shelf_height=max(shelf_height,item_minor)
                rows=[output[i] for i in range(n)]
                # Some shelf layouts can place diagonal blocks too close.
                try:
                    _validate_2d_clearance(rows,spacing)
                    check_macro_placement_zones(rows,region_um=region_um,stayouts_um=stayouts_um,halo_um=halo_um)
                except MacroConstraintError:continue
                dw,dh=die(rows)
                # Actual fabricated DIE_AREA is what costs silicon. Ranking
                # (die minus two margins) used to underweight perimeter and
                # could choose a physically LARGER die than another candidate.
                area=dw*dh
                rank=(round(area,4),round(dw+dh,4),round(abs(dw-dh),4),order,vertical,limit)
                if best is None or rank<best[0]:best=(rank,rows,[dw,dh])
    if best is None and region_um is not None:
        # Place candidates next to region origin, stay-out boundaries and
        # already placed rectangles. Backtrack for small multi-macro projects.
        x0,y0,x1,y1=region_um
        placed=[]
        by_area=sorted(blocks,key=lambda b:-(b['size_um'][0]*b['size_um'][1]))
        nodes=[0]
        def attempt(i):
            if i==len(by_area):
                try:_validate_2d_clearance(placed,spacing)
                except MacroConstraintError:return False
                return True
            if nodes[0]>120000:return False
            b=by_area[i]
            w,h=b['size_um']
            xs={x0,x1-w};ys={y0,y1-h}
            for q in placed:
                xs.update((q['x_um']+q['width_um']+gap,q['x_um']-w-gap))
                ys.update((q['y_um']+q['height_um']+gap,q['y_um']-h-gap))
            for sx,sy,ex,ey in stayouts_um:
                xs.update((ex+halo_um,sx-w-halo_um))
                ys.update((ey+halo_um,sy-h-halo_um))
            choices=sorted((round(x,3),round(y,3)) for x in xs for y in ys if x>=x0-1e-6 and y>=y0-1e-6 and x+w<=x1+1e-6 and y+h<=y1+1e-6)
            for x,y in choices:
                nodes[0]+=1
                row=_dimensioned_rect(b,x,y)
                try:
                    check_macro_placement_zones([row],region_um=region_um,stayouts_um=stayouts_um,halo_um=halo_um)
                    for other in placed:
                        if _rect_gap(row,other)<spacing['min_um']-0.001:
                            raise MacroConstraintError('clearance')
                except MacroConstraintError:continue
                placed.append(row)
                if attempt(i+1):return True
                placed.pop()
            return False
        if len(by_area)<=10 and attempt(0):
            ordered={r['instance']:r for r in placed}
            rows=[ordered[b['instance']] for b in blocks]
            dw,dh=die(rows)
            best=((dw*dh,),(rows),[dw,dh])
    if best is None:
        raise MacroConstraintError('CO.MACROS_NO_PLACEMENT: cannot pack required macros within CO placement region, stay-outs and spacing')
    if grid_um and mode=='compact':
        # Nearby X/Y coordinates produced from independent fractional LEF
        # dimensions can create 1-5 um sliver channels for OpenROAD PDN.
        # Snap compact placements to a common coarse grid, but ONLY if the
        # resulting rectangles still satisfy all hard CO rules. Never modify
        # manual positions. A rejected snap leaves the legal plan unchanged.
        aligned=[]
        for row in best[1]:
            aligned.append({**row,
                'x_um':round(round(row['x_um']/grid_um)*grid_um,4),
                'y_um':round(round(row['y_um']/grid_um)*grid_um,4)})
        try:
            if region_um is None and any(min(r['x_um'],r['y_um'])<margin for r in aligned):
                raise MacroConstraintError('CO.MACROS_GRID_BORDER: snapped placement crosses die margin')
            _validate_2d_clearance(aligned,spacing)
            check_macro_placement_zones(aligned,region_um=region_um,stayouts_um=stayouts_um,halo_um=halo_um)
        except MacroConstraintError:
            pass  # Keep the proven-legal unsnapped arrangement.
        else:
            return aligned,die(aligned)
    return best[1],best[2]


def alternate_pdn_floorplan(blocks, co, previous, increment=20.0):
    """Propose one distinct, validated, less cramped automatic floorplan.

    The OpenROAD PDN-0179 code alone does not prove this layout will route.
    Keep user-requested minimum/maximum, placement region and stay-outs hard.
    Manual mode is never changed or retried automatically.
    """
    if co['placement_mode']!='compact':
        return None
    spacing=dict(co['packing_spacing'])
    current=spacing['preferred_um']
    new=min(spacing['max_um'],round(current+increment,3))
    if new<=current+1e-6:
        return None
    spacing['preferred_um']=new
    try:
        plan,die=allocate_macro_rectangles(blocks,spacing,mode='compact',
            region_um=co['placement_region_um'],stayouts_um=co['placement_stayouts_um'],
            halo_um=co['halo_um'],grid_um=co['placement_grid_um'])
    except MacroConstraintError:
        return None
    before=[(r['instance'],r['x_um'],r['y_um']) for r in previous]
    after=[(r['instance'],r['x_um'],r['y_um']) for r in plan]
    if before==after:return None
    return plan,die,new


def render_co_macro_plan_svg(rows, die, path):
    """Visualize measured LEF macro bounds (placement PLAN, never GDS evidence)."""
    dw,dh=die
    scale=min(900/max(dw,1),650/max(dh,1))
    margin=18
    width=dw*scale+margin*2
    height=dh*scale+margin*2+38
    fills=('#335d8e','#38785e','#8e6735','#74458d','#8b4451')
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}" height="{height:.2f}" viewBox="0 0 {width:.2f} {height:.2f}">',
           f'<rect x="0" y="0" width="{width:.2f}" height="{height:.2f}" fill="#f4f7fa"/>',
           f'<text x="15" y="24" font-family="Arial" font-size="14" fill="#283748">CO MACRO PLAN · {dw:.0f} × {dh:.0f} µm · not signoff</text>',
           f'<rect x="{margin}" y="{margin+38}" width="{dw*scale:.2f}" height="{dh*scale:.2f}" fill="#e7eef4" stroke="#61758a" stroke-width="2"/>']
    for i,b in enumerate(rows):
        x=margin+b['x_um']*scale
        y=margin+38+(dh-b['y_um']-b['height_um'])*scale
        w,h=b['width_um']*scale,b['height_um']*scale
        name=escape(b['name']); inst=escape(b['instance'])
        # Clip labels inside their own rectangles, rather than allowing them to
        # overprint adjoining macros (particularly in narrow SVG preview tabs).
        # The full names remain available in SVG hover titles.
        label_size=min(14.,max(6.,(w-10)/max(1,len(b['name']))/0.59))
        instance_size=min(12.,max(6.,(w-10)/max(1,len(b['instance']))/0.59))
        parts.extend([f'<clipPath id="macro_clip_{i}"><rect x="{x+3:.2f}" y="{y+3:.2f}" width="{max(1,w-6):.2f}" height="{max(1,h-6):.2f}"/></clipPath>',
                      f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fills[i%len(fills)]}" stroke="#18334a" stroke-width="2"><title>{name} ({inst})</title></rect>',
                      f'<g clip-path="url(#macro_clip_{i})">',
                      f'<text x="{x+5:.2f}" y="{y+5+label_size:.2f}" font-family="Arial" font-size="{label_size:.2f}" font-weight="bold" fill="white">{name}</text>',
                      f'<text x="{x+5:.2f}" y="{y+9+label_size+instance_size:.2f}" font-family="Arial" font-size="{instance_size:.2f}" fill="white">{inst}</text>',
                      '</g>'])
    parts.append('</svg>')
    Path(path).write_text('\n'.join(parts)+'\n',encoding='utf-8')


def verify_routed_macro_def(path, plan, tol_um=3):
    """Ensure every requested macro is placed at its CO location in routed DEF."""
    content=Path(path).read_text(encoding='utf-8',errors='replace')
    units=re.search(r'\bUNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;',content)
    components=re.search(r'\bCOMPONENTS\s+\d+\s*;(.*?)\bEND\s+COMPONENTS',content,re.S)
    if not units or not components:raise MacroConstraintError('CO.MACROS_DEF: routed DEF lacks units/components')
    dbu=int(units.group(1)); items={}
    for part in re.findall(r'\s*-\s+.*?;',components.group(1),re.S):
        name=re.match(r'\s*-\s+(\S+)\s+(\S+)',part)
        coord=re.search(r'\+\s+(FIXED|PLACED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)',part)
        if name and coord:
            items[name.group(1)]={'module':name.group(2),'x_um':int(coord.group(2))/dbu,
                                   'y_um':int(coord.group(3))/dbu,'orientation':coord.group(4)}
    for b in plan:
        got=items.get(b['instance'])
        if not got or got['module']!=b['module']:
            raise MacroConstraintError('CO.MACROS_DEF: expected real macro '+b['instance']+' '+b['module'])
        if abs(got['x_um']-b['x_um'])>tol_um or abs(got['y_um']-b['y_um'])>tol_um:
            raise MacroConstraintError('CO.MACROS_DEF: macro moved outside required placement: '+b['instance'])
    rects=[{**b, 'x_um':items[b['instance']]['x_um'],'y_um':items[b['instance']]['y_um']} for b in plan]
    _validate_2d_clearance(rects,{'min_um':plan[0]['min_spacing_um'],
                                  'max_um':plan[0]['max_spacing_um']})
    return {'status':'MACRO_DEF_PLACEMENTS_VERIFIED','instances':items}


def plan_spacing_allowed(gap, plan):
    # Constraints embedded in plan for post-placement checks.
    low=plan[0]['min_spacing_um']; high=plan[0]['max_spacing_um']
    return low-0.5 <= gap <= high+0.5


def _blackbox_header(block):
    mod=block['module']
    return f'(* blackbox *) module {mod} (\n`ifdef USE_POWER_PINS\n inout VPWR, inout VGND,\n`endif\n {block["ports"]}\n);\nendmodule\n'


def gds_referenced_structures(path):
    """Read SNAME references, not merely unused structures in GDS library."""
    import struct
    refs=set()
    with Path(path).open('rb') as file:
        while head:=file.read(4):
            if len(head)!=4:raise MacroConstraintError('CO.MACROS_GDS: truncated GDS header')
            length,record,datatype=struct.unpack('>HBB',head)
            if length<4 or length%2:raise MacroConstraintError('CO.MACROS_GDS: invalid record size')
            payload=file.read(length-4)
            if len(payload)!=length-4:raise MacroConstraintError('CO.MACROS_GDS: truncated GDS record')
            if record==18:refs.add(payload.rstrip(b'\0').decode('ascii','replace'))
    return refs


def collect_pdn_errors(physical_log):
    """Parse real LibreLane/OpenROAD PDN errors, including wrapped Rich logs.

    The old implementation overlooked PDN-0178/0179 and misreported this
    exact failure as NO_PDN_FINDINGS. This remains diagnostic only: it never
    changes the physical return status or grants power-grid signoff.
    """
    path=Path(physical_log)
    if not path.is_file():
        return {'status':'NO_LOG','findings':[], 'remaining_channels':[]}
    log=path.read_text(encoding='utf-8',errors='replace')
    log=re.sub(r'\x1b\][^\x1b]*(?:\x1b\\|\x07)','',log)
    log=re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]','',log)
    # Rich wraps native OpenROAD warnings over several lines; omit its
    # progress redraws so a single geometrical channel can be recovered.
    native='\n'.join(re.sub(r'^\[(?:STDOUT|STDERR)\]\s*','',line).strip()
                     for line in log.splitlines()
                     if not ('Classic - Stage' in line and '━━━━━━━━' in line))
    native=re.sub(r'\b(?:openroad|flow)\.py:\d+\b', '', native)
    findings=[]
    for key in ('PSM-0069','PSM-0039','PSM-0038','PDN-0110','PDN-0178','PDN-0179'):
        matches=list(re.finditer(re.escape(key),native))
        if matches:
            excerpt=native[matches[0].start():matches[0].start()+280]
            excerpt=re.sub(r'\s+',' ',excerpt).strip()
            findings.append({'code':key,'count_in_log':len(matches),'sample':excerpt[:220]})
    channel_re=re.compile(
        r'\[PDN-0178\]\s+Remaining\s+channel\s*'
        r'\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)\s*-\s*'
        r'\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)\s*'
        r'on\s+(\w+)\s+for\s+nets:\s*([A-Za-z0-9_, ]+)',re.I)
    channels=[]
    for match in channel_re.finditer(native):
        channel={'bounds_um':[float(match.group(i)) for i in range(1,5)],
                 'layer':match.group(5),'nets':match.group(6).strip()}
        if channel not in channels: channels.append(channel)
    codes={f['code'] for f in findings}
    status=('PDN_CHANNEL_REPAIR_FAILED' if 'PDN-0179' in codes else
            'PDN_CONNECTIVITY_SUSPECT' if 'PSM-0069' in codes else
            'PDN_WARNINGS' if findings else 'NO_PDN_FINDINGS')
    return {'status':status,'findings':findings,'remaining_channels':channels}



def classify_macro_hardening_failure(log_path, result):
    """Report a failed child-macro verification without skipping any checks.

    LibreLane's Classic flow can complete geometry and still return code 2 at
    its deferred KLayout/Magic XOR checker. Its final native error is often
    only '1 XOR differences found', not the physical geometry responsible.
    Preserve the failed state; expose the exact required investigation files.
    """
    path = Path(log_path)
    original = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
    original += '\n' + str(result.get('stdout_tail') or '')
    original += '\n' + str(result.get('stderr_tail') or '')
    original = re.sub(r'\x1b\][^\x1b]*(?:\x1b\\|\x07)', '', original)
    original = re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]', '', original)
    matches = re.findall(r'\b(\d+)\s+XOR\s+differences?\s+found\b', original, re.I)
    if matches:
        return {
            'status': 'MAGIC_KLAYOUT_XOR_MISMATCH',
            'xor_difference_count': max(map(int, matches)),
            'log': str(path),
            'interpretation': 'Different GDS geometries in Magic and KLayout stream-outs; not a CPU XOR instruction or DLS equivalence failure.',
            'remedy': 'Inspect this macro run KLayout.XOR output/metrics and compare the Magic and KLayout GDS layers; do not disable ERROR_ON_XOR_ERROR or RUN_KLAYOUT_XOR to claim signoff.'
        }
    return {'status': 'MACRO_HARDENING_FAILED', 'log': str(path),
            'remedy': 'Inspect the full child-macro LibreLane log for the first native fatal error.'}


def _write_json(path,obj):
    atomic_write(Path(path),json.dumps(obj,indent=2)+'\n')


def child_macro_librelane_config(block, physical):
    """Physically size child macros from synthesis, unless CO pins an explicit die.

    In relative mode, LibreLane computes core dimensions using the cell area
    after synthesis and the chosen FP_CORE_UTIL; the generated LEF (not the
    source preview hint) is the source of truth for top-level packing.
    """
    config={'DESIGN_NAME':block['module'], 'VERILOG_FILES':['dir::design.v'],
            'PDK':physical['pdk'],
            'STD_CELL_LIBRARY':physical.get('std_cell_library','sky130_fd_sc_hd'),
            'FP_CORE_UTIL':(block['core_utilization'] if block.get('die_mode')=='auto' or
                            block.get('core_utilization_explicit') else physical.get('core_utilization',25)),
            'PDN_ENABLE_RAILS':True,'PDN_ENABLE_GLOBAL_CONNECTIONS':True,
            'PDN_MULTILAYER':False,'PDN_ENABLE_PINS':True}
    if block.get('die_mode','fixed')=='auto':
        config['FP_SIZING']='relative'
        config['FP_ASPECT_RATIO']=1.0
    else:
        # Preserve existing fixed-die projects and their exact input hashes.
        config['DIE_AREA']=[0,0,block['width'],block['height']]
        config['CORE_AREA']=[10,10,block['width']-10,block['height']-10]
    if block['clock']:
        config['CLOCK_PORT']=block['clock']
        config['CLOCK_PERIOD']=physical['clock_period_ns']
    return config


def child_macro_cache_digest(block, physical, config=None):
    """Hash actual RTL and complete sizing configuration for safe view reuse."""
    config = child_macro_librelane_config(block, physical) if config is None else config
    return hashlib.sha256(
        block['rtl'].read_bytes()+json.dumps(config,sort_keys=True).encode()+
        str(physical.get('pdk_root','')).encode()
    ).hexdigest()


def cached_macro_lef_size(project_root, block, physical):
    """Get a verified-current cached LEF size; never trust an old preview plan."""
    folder=Path(project_root)/'build'/'co_macro_cache'/block['module']
    stamp=folder/'source.sha256'
    digest=child_macro_cache_digest(block,physical)
    if not stamp.is_file() or stamp.read_text(encoding='utf-8').strip()!=digest:
        return None
    try:
        path=final_view(folder/'runs'/('hard_'+digest[:14]),'lef',block['module'],'.lef')
        return read_lef_size(path,block['module'])
    except (MacroConstraintError,OSError,ValueError):
        return None


def run_native_macro_flow(session, preflight):
    """Executed by normal PICADS Physical/Generate-GDS GUI, no extra launcher."""
    from .physical_flow import make_physical_handoff,verify_handoff_inputs
    from .maskinspect import inspect_gds
    co=read_macro_constraints(session.project.co['physical_macros'],session.root,
                              session.project.config['physical'],session.project.co.get('floorplan'))
    physical=session.project.config['physical']
    backend=(session.project.config.get('tools') or {}).get('execution','native')
    dist=(session.project.config.get('tools') or {}).get('wsl_distribution')
    opts={'runner':backend,'wsl_distribution':dist} if backend=='wsl' else {}
    root=session.out/'co_macros';root.mkdir(exist_ok=True)
    input_hashes={str(p):artifact_hash(p) for p in [co['top_rtl'],*(b['rtl'] for b in co['blocks'])]}
    cache=session.root/'build'/'co_macro_cache';cache.mkdir(parents=True,exist_ok=True)
    run_tag='cc_'+session.result.run_id
    all_views={}
    macro_runs=[]
    for b in co['blocks']:
        folder=cache/b['module'];folder.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(b['rtl'],folder/'design.v')
        config=child_macro_librelane_config(b,physical)
        _write_json(folder/'config.json',config)
        # Archive-backed build directories have separate lifetimes; do not reuse
        # a cached macro without proving it comes from the same RTL and config.
        digest=child_macro_cache_digest(b,physical,config)
        stamp=folder/'source.sha256';tag='hard_'+digest[:14]
        run=folder/'runs'/tag
        valid=False
        if stamp.is_file() and stamp.read_text().strip()==digest:
            try:
                all_views[b['module']]={k:final_view(run,v,b['module'],s) for k,v,s in
                                         [('gds','gds','.gds'),('lef','lef','.lef'),('nl','nl','.v')]}
                valid=True
            except MacroConstraintError:pass
        if not valid:
            cmd=['librelane']+(['--dockerized'] if backend=='wsl' or physical.get('dockerized') else [])
            if physical.get('pdk_root'):cmd.extend(['--pdk-root',str(physical['pdk_root'])])
            cmd+=['--pdk',physical['pdk'],'--run-tag',tag]
            if run.exists():
                cmd+=['--overwrite']
            # In the GUI's Generate Layout mode, stop after all three macro
            # handoff views (GDS, LEF, synthesized netlist) have been produced.
            # In Classic, Magic.WriteLEF is AFTER KLayout.StreamOut, but BEFORE
            # KLayout.XOR/DRC/LVS. Those checks belong to Verify Existing Layout.
            if session.mode == 'layout':
                cmd += ['--to', 'Magic.WriteLEF']
            cmd += ['config.json']
            ret=run_external(cmd,folder,folder,session.issues,session.events,
                             f'macro_{b["module"]}',timeout=physical.get('timeout_s',14400),**opts)
            if ret['status']!='PASS':
                diagnostic=classify_macro_hardening_failure(folder/('macro_'+b['module']+'.log'),ret)
                diagnostic.update(module=b['module'],run_tag=tag,run_directory=str(run),
                                  source_rtl=str(b['rtl']))
                diagnostic_path=root/'macro_hardening_diagnostics.json'
                _write_json(diagnostic_path,diagnostic)
                session.result.files['macro_hardening_diagnostics']=str(diagnostic_path)
                xor_failure=diagnostic['status']=='MAGIC_KLAYOUT_XOR_MISMATCH'
                issue=session.issues.add(
                    'CO.MACROS_XOR_MISMATCH' if xor_failure else 'CO.MACROS_HARDENING_FAILED',
                    'ERROR','PHYSICAL','physical',
                    (f'Child macro {b["module"]} has {diagnostic["xor_difference_count"]} Magic/KLayout GDS XOR differences; physical verification failed.'
                     if xor_failure else f'Required macro {b["module"]} failed to harden in LibreLane.'),
                    remedy=diagnostic['remedy'],evidence={**ret,'macro_diagnostics':diagnostic})
                session._done('physical','FAIL',block=b['module'],failed_step='macro_hardening',
                              issue_id=issue.issue_id,result=ret,diagnostics=str(diagnostic_path))
                return
            all_views[b['module']]={k:final_view(run,v,b['module'],s) for k,v,s in
                                     [('gds','gds','.gds'),('lef','lef','.lef'),('nl','nl','.v')]}
            stamp.write_text(digest+'\n')
        views=all_views[b['module']]
        # Record immutable evidence for resuming post-layout checks on each
        # child without re-synthesizing or rerouting it later.
        macro_runs.append({
            'module': b['module'], 'run_tag': tag,
            'source_sha256': artifact_hash(folder/'design.v'),
            'config_sha256': artifact_hash(folder/'config.json'),
            'views': {kind: {
                'relative_path': str(path.relative_to(folder)),
                'sha256': artifact_hash(path)
            } for kind,path in views.items()}
        })
    if (session.project.co.get('synthesis') or {}).get('abc_aig'):
        abc={}
        for block in co['blocks']:
            mod=block['module']; directory=cache/mod
            aig_script=(f'read_verilog design.v; hierarchy -check -top {mod}; '
                        f'synth -top {mod}; dffunmap; abc -g AND; clean; '
                        f'write_aiger -zinit -symbols abc_optimized.aig')
            status=run_external(['yosys','-p',aig_script],directory,directory,
                                session.issues,session.events,f'abc_{mod}',timeout=600,**opts)
            aig=directory/'abc_optimized.aig'
            ok=status['status']=='PASS' and aig.is_file() and aig.stat().st_size>0
            abc[mod]={'status':'PASS' if ok else 'UNAVAILABLE',
                      'path':str(aig) if ok else None,'returncode':status.get('returncode')}
            if not ok:
                aig.unlink(missing_ok=True)
        report=root/'abc_aig_results.json'; _write_json(report,abc)
        session.result.files['macro_abc_aig']=str(report)
        session._done('abc_aig','PASS' if all(x['status']=='PASS' for x in abc.values()) else 'PARTIAL',
                      reports=abc,scope='Independent optimization graph; not the routed technology-mapped netlist')
    if any(artifact_hash(Path(p))!=h for p,h in input_hashes.items()):
        raise MacroConstraintError('CO.MACROS_SOURCE_CHANGED: source RTL changed during macro hardening')
    dims=[]
    power_pin_evidence={}
    child_sizing={}
    for b in co['blocks']:
        view=all_views[b['module']]['lef']
        power_pin_evidence[b['module']]=inspect_macro_lef_power(view,b['module'])
        measured=read_lef_size(view,b['module'])
        dims.append({**b,'size_um':measured})
        child_sizing[b['module']]={'mode':b['die_mode'], 'lef_size_um':measured,
                                  'target_core_utilization_percent':b['core_utilization'],
                                  'preview_hint_used_for_physical':False}
    plan,die=allocate_macro_rectangles(dims,co['packing_spacing'],mode=co['placement_mode'],
        region_um=co['placement_region_um'],stayouts_um=co['placement_stayouts_um'],halo_um=co['halo_um'],grid_um=co['placement_grid_um'])
    for r in plan:
        r['min_spacing_um']=co['spacing']['min_um'];r['max_spacing_um']=co['spacing']['max_um']
    die_metrics=effective_macro_die(plan, mode=co['placement_mode'],
        die_size_um=co['die_size_um'],halo_um=co['halo_um'])
    die=[die_metrics['width_um'],die_metrics['height_um']]
    plan_preview=root/'co_macro_floorplan.svg'
    render_co_macro_plan_svg(plan,die,plan_preview)
    session.result.files['co_macro_floorplan']=str(plan_preview)
    views_dir=root/'views';views_dir.mkdir(exist_ok=True)
    macros={}
    for b,r in zip(co['blocks'],plan):
        mod=b['module'];dest=views_dir/mod;dest.mkdir(parents=True,exist_ok=True)
        src=all_views[mod]
        for kind,suffix in [('gds','.gds'),('lef','.lef'),('nl','.nl.v')]:
            shutil.copyfile(src[kind],dest/(mod+suffix))
        (dest/(mod+'.vh')).write_text(_blackbox_header(b),encoding='utf-8')
        base=f'dir::co_macros/views/{mod}/{mod}'
        macros[mod]={'instances':{b['instance']:{'location':[r['x_um'],r['y_um']],'orientation':'N'}},
                     'gds':[base+'.gds'],'lef':[base+'.lef'],
                     'nl':[base+'.nl.v'],'vh':[base+'.vh']}
    shutil.copyfile(co['top_rtl'],root/'top.v')
    # For small educational macros, the SKY130 default strap pitch can miss
    # entire macro power-pin regions. Bound the top-level pitch by the smallest
    # hardened macro dimensions, without changing PDK-defined strap widths.
    min_width=min(b['size_um'][0] for b in dims)
    min_height=min(b['size_um'][1] for b in dims)
    pdn_hpitch=round(min(80.0,max(25.0,min_height/2.0)),2)
    pdn_vpitch=round(min(80.0,max(25.0,min_width/2.0)),2)
    topcfg={**preflight.librelane_config, 'DESIGN_NAME':co['top'],'VERILOG_FILES':['dir::co_macros/top.v'],
            'DIE_AREA':[0,0,*die], 'CORE_AREA':[10,10,die[0]-10,die[1]-10],
            'MACROS':macros,'FP_MACRO_HORIZONTAL_HALO':co['halo_um'],
            'FP_MACRO_VERTICAL_HALO':co['halo_um'],'PDN_CONNECT_MACROS_TO_GRID':True,
            'PDN_MACRO_CONNECTIONS':[f'{b["instance"]} VPWR VGND VPWR VGND' for b in co['blocks']],
            'PDN_MULTILAYER':True, 'PDN_HPITCH':pdn_hpitch, 'PDN_VPITCH':pdn_vpitch}
    # Physical hard-macro floorplan determines the bounding box; explicit fixed
    # die/core settings must not silently conflict with real macro dimensions.
    _write_json(session.out/'config.json',topcfg)
    _write_json(root/'co_macro_plan.json',{'status':'REQUESTED_NOT_YET_VERIFIED','blocks':plan,
                                         'top':co['top'],'spacing':co['spacing'],'packing_spacing':co['packing_spacing'],
                                         'pdn_placement_target_um':co['pdn_placement_target_um'],
                                         'placement_mode':co['placement_mode'],'placement_grid_um':co['placement_grid_um'],
                                         'die_size_constraint_um':co['die_size_um'],
                                         'auto_die':die_metrics,'child_sizing':child_sizing,
                                         'placement_region_um':co['placement_region_um'],
                                         'pdn':{'top_hpitch_um':pdn_hpitch,'top_vpitch_um':pdn_vpitch,
                                                'child_multilayer':False,'child_power_pins':power_pin_evidence,
                                                'verification':'Electrical connectivity still must pass LibreLane'},
                                         'notice':'Physical RTL explicitly selected in CO; Python DLS equivalence not demonstrated'})
    session.result.files['co_macro_plan']=str(root/'co_macro_plan.json')
    handoff=make_physical_handoff(root/'top.v',session.out/'config.json',session.out/'physical_handoff.json',
                                  pdk=physical['pdk'],run_tag=run_tag,tool_path='WSL' if backend=='wsl' else 'native')
    session.result.files['physical_handoff']=str(session.out/'physical_handoff.json')
    cmd=['librelane']+(['--dockerized'] if backend=='wsl' or physical.get('dockerized') else [])
    if physical.get('pdk_root'):cmd.extend(['--pdk-root',str(physical['pdk_root'])])
    cmd+=['--pdk',physical['pdk'],'--run-tag',run_tag]
    if session.mode=='layout':cmd+=['--to','KLayout.StreamOut']
    cmd+=['config.json']
    from .diagnostics import IssueCollector
    # A failed *trial* must not permanently mark a recovered build FAILED.
    # Only report a TOOL error if the final attempt also fails. All original
    # attempts and their native logs remain in the machine-readable receipts.
    result=run_external(cmd,session.out,session.out,IssueCollector(),session.events,
                        'physical',timeout=physical.get('timeout_s',14400),**opts)
    attempts=[{'run_tag':run_tag,'status':result['status'],'log':result.get('log'),
               'preferred_gap_um':co['packing_spacing']['preferred_um']}]
    pdn_diagnostic=collect_pdn_errors(session.out/'physical.log') if result['status']!='PASS' else None
    alternative=(alternate_pdn_floorplan(dims,co,plan) if
                 result['status']=='FAIL' and pdn_diagnostic and
                 pdn_diagnostic['status']=='PDN_CHANNEL_REPAIR_FAILED' else None)
    if alternative:
        retry_plan,retry_die,retry_gap=alternative
        # A retry is a NEW LibreLane run with exact placement provenance;
        # do not reuse or overwrite the first run's DEF/GDS/log.
        retry_tag=run_tag+'_pdn1'
        for row in retry_plan:
            row['min_spacing_um']=co['spacing']['min_um']
            row['max_spacing_um']=co['spacing']['max_um']
            topcfg['MACROS'][row['module']]['instances'][row['instance']]['location']=[
                row['x_um'],row['y_um']]
        topcfg['DIE_AREA']=[0,0,*retry_die]
        topcfg['CORE_AREA']=[10,10,retry_die[0]-10,retry_die[1]-10]
        _write_json(session.out/'config.json',topcfg)
        new_handoff=make_physical_handoff(root/'top.v',session.out/'config.json',
            session.out/'physical_handoff.json',pdk=physical['pdk'],
            run_tag=retry_tag,tool_path='WSL' if backend=='wsl' else 'native')
        new_cmd=[retry_tag if i>0 and cmd[i-1]=='--run-tag' else part for i,part in enumerate(cmd)]
        retry_result=run_external(new_cmd,session.out,session.out,IssueCollector(),session.events,
                                  'physical_pdn_retry1',timeout=physical.get('timeout_s',14400),**opts)
        attempts.append({'run_tag':retry_tag,'status':retry_result['status'],
                         'log':retry_result.get('log'),'preferred_gap_um':retry_gap})
        plan,die,run_tag,result,handoff=retry_plan,retry_die,retry_tag,retry_result,new_handoff
        die_metrics=autosized_macro_die(plan)
        render_co_macro_plan_svg(plan,die,plan_preview)
        current_report=json.loads((root/'co_macro_plan.json').read_text(encoding='utf-8'))
        current_report.update(blocks=plan,auto_die=die_metrics,
                              packing_spacing={**co['packing_spacing'],'preferred_um':retry_gap},
                              pdn_recovery_attempts=attempts)
        _write_json(root/'co_macro_plan.json',current_report)
        pdn_diagnostic=(collect_pdn_errors(session.out/'physical_pdn_retry1.log')
                        if result['status']!='PASS' else None)
    if result['status']!='PASS':
        pdn_diagnostic=pdn_diagnostic or collect_pdn_errors(
            session.out/'physical_pdn_retry1.log' if len(attempts)>1 else session.out/'physical.log')
        pdn_diagnostic['attempts']=attempts
        _write_json(root/'pdn_diagnostics.json',pdn_diagnostic)
        session.result.files['macro_pdn_diagnostics']=str(root/'pdn_diagnostics.json')
        if result.get('returncode'):
            session.issues.add('TOOL.EXIT_NONZERO','ERROR','TOOL','physical',
                f'External physical flow exited with code {result["returncode"]}.',
                remedy='Inspect the final native physical log and PDN diagnostics.',evidence=result)
        issue=session.issues.add('CO.MACROS_TOP_FAILED','ERROR','PHYSICAL','physical',
            'Required modular top-level placement/routing failed.' +
            (' PDN-0179: power-grid channel repair failed; inspect co_macros/pdn_diagnostics.json and macro clearances.'
             if pdn_diagnostic['status']=='PDN_CHANNEL_REPAIR_FAILED' else
             ' PSM-0069: power grid connectivity failed; inspect co_macros/pdn_diagnostics.json.'
             if pdn_diagnostic['status']=='PDN_CONNECTIVITY_SUSPECT' else ''),
            evidence={**result,'pdn_diagnostics':pdn_diagnostic})
        session._done('physical',result['status'],issue_id=issue.issue_id,result=result);return
    if len(attempts)>1:
        session.events.emit('physical','pdn_recovery_succeeded',attempts=attempts)
    if not verify_handoff_inputs(handoff) or any(artifact_hash(Path(p))!=h for p,h in input_hashes.items()):
        raise MacroConstraintError('CO.MACROS_INPUTS_CHANGED: physical RTL/config changed while running')
    final=session.out/'runs'/run_tag
    evidence=inspect_librelane(final,expected_top=co['top'])
    _write_json(session.out/'physical_evidence.json',evidence.as_dict())
    session.result.files['physical_evidence']=str(session.out/'physical_evidence.json')
    if not evidence.gds or evidence.checks.get('expected_top',{}).get('status')!='PASS':
        raise MacroConstraintError('CO.MACROS_GDS: missing final GDS with correct modular top')
    defpath=final_view(final,'def',co['top'],'.def')
    placement=verify_routed_macro_def(defpath,plan)
    from .maskinspect import inspect_gds
    gds=Path(evidence.gds[0]);structures=set(inspect_gds(gds).structures)
    missing={co['top']} | {b['module'] for b in co['blocks']}
    if not missing.issubset(structures):
        raise MacroConstraintError('CO.MACROS_GDS_HIERARCHY: final GDS missing '+repr(sorted(missing-structures)))
    references=gds_referenced_structures(gds)
    missing_refs={b['module'] for b in co['blocks']}-references
    if missing_refs:
        raise MacroConstraintError('CO.MACROS_GDS_REFERENCES: no placed GDS references for '+repr(sorted(missing_refs)))
    _write_json(root/'co_macro_placement_verified.json',{'status':'MACRO_GDS_AND_DEF_PLACEMENT_VERIFIED',
                'top':co['top'],'blocks':plan,'def':str(defpath),'gds':str(gds),'def_evidence':placement})
    session.result.files['co_macro_placement']=str(root/'co_macro_placement_verified.json')
    session.result.files['gds']=str(gds)
    layers=inspect_gds(gds)
    _write_json(session.out/'layout_artifacts.json',{'schema':1,'status':'LAYOUT_GENERATED_NOT_MASK_SIGNOFF',
                'gds':str(gds),'gds_sha256':artifact_hash(gds),'run_tag':run_tag,'top':co['top'],
                'macro_children': macro_runs,
                'gds_relative_to_build':str(gds.relative_to(session.out)),
                'layers':layers.layer_elements, 'rtl_source':'CO_EXPLICIT_MODULAR_RTL',
                'source_equivalence':'NOT_ESTABLISHED'})
    session.result.files['layout_layers']=str(session.out/'layout_artifacts.json')
    session._done('physical_source_equivalence','UNVERIFIED',
                  reason='PICADS Python DLS and independent CO modular RTL have not been formally proven equivalent')
    session._done('physical','PASS',gds=[str(gds)],macro_placement='MACRO_GDS_AND_DEF_PLACEMENT_VERIFIED',
                  real_modules=[b['module'] for b in co['blocks']],
                  source_equivalence='NOT_ESTABLISHED')
    if session.mode=='layout':
        session._done('macro_signoff','DEFERRED',reason='Child GDS/LEF created; child KLayout XOR/DRC/LVS not run yet')
        session._done('signoff','DEFERRED',reason='Generate-GDS only; run physical verification separately')
    else:
        session._done('signoff','UNAVAILABLE',reason='Independent signoff and equivalence not established')


def verify_cached_macro_children(session, layout_manifest, physical, runner_options):
    """Resume child macro signoff without re-synthesis or placement.

    Macro view hashes are captured at Generate Layout time. A changed or
    missing view fails closed rather than verifying a replacement design.
    Returns True only when *every* declared child passes LibreLane's
    post-Magic.WriteLEF checks, including GDS XOR, DRC and LVS.
    """
    children = layout_manifest.get('macro_children')
    if not isinstance(children, list) or not children:
        issue = session.issues.add(
            'VERIFY.MACRO_RECEIPTS_MISSING', 'ERROR', 'FILESYSTEM', 'macro_signoff',
            'The modular GDS has no child-macro verification receipts. Regenerate with the updated PICADS.')
        session._done('macro_signoff', 'FAIL', issue_id=issue.issue_id)
        return False

    base = (session.root/'build'/'co_macro_cache').resolve()
    for item in children:
        module = item.get('module') if isinstance(item, dict) else None
        tag = item.get('run_tag') if isinstance(item, dict) else None
        if not (isinstance(module, str) and IDENT.fullmatch(module)
                and isinstance(tag, str) and re.fullmatch(r'hard_[a-f0-9]{14}', tag)):
            issue = session.issues.add('VERIFY.MACRO_RECEIPT_INVALID', 'ERROR', 'FILESYSTEM',
                'macro_signoff', 'Invalid macro verification receipt; refusing to run external commands.')
            session._done('macro_signoff', 'FAIL', issue_id=issue.issue_id)
            return False
        folder = (base/module).resolve()
        if not folder.is_relative_to(base):
            issue = session.issues.add('VERIFY.MACRO_CACHE_PATH', 'ERROR', 'FILESYSTEM',
                'macro_signoff', 'Macro cache resolves outside the project build directory.')
            session._done('macro_signoff', 'FAIL', issue_id=issue.issue_id)
            return False
        files = [(folder/'design.v', item.get('source_sha256')),
                 (folder/'config.json', item.get('config_sha256'))]
        views = item.get('views')
        if not isinstance(views, dict) or set(views) != {'gds','lef','nl'}:
            files.append((folder/'missing-macro-views', None))
        else:
            for kind in ('gds', 'lef', 'nl'):
                record = views.get(kind)
                rel = record.get('relative_path') if isinstance(record, dict) else None
                checksum = record.get('sha256') if isinstance(record, dict) else None
                if not isinstance(rel, str) or not rel:
                    files.append((folder/'missing-macro-view', None))
                else:
                    candidate = (folder/rel).resolve()
                    files.append((candidate, checksum))
        valid = all(path.is_relative_to(folder) and path.is_file()
                    and isinstance(expected,str) and re.fullmatch(r'[a-f0-9]{64}',expected)
                    and artifact_hash(path) == expected
                    for path,expected in files)
        if not valid or not (folder/'runs'/tag).is_dir():
            issue = session.issues.add('VERIFY.MACRO_CACHE_CHANGED', 'ERROR', 'FILESYSTEM',
                'macro_signoff', f'The saved {module} macro views, config or run state changed or disappeared.',
                remedy='Regenerate the physical layout to recreate the matching macro views.')
            session._done('macro_signoff', 'FAIL', module=module, issue_id=issue.issue_id)
            return False
        cmd = ['librelane']
        if runner_options.get('runner') == 'wsl' or physical.get('dockerized'):
            cmd.append('--dockerized')
        if physical.get('pdk_root'):
            cmd += ['--pdk-root', str(physical['pdk_root'])]
        cmd += ['--pdk', physical['pdk'], '--run-tag', tag,
                '--from', 'Odb.CheckDesignAntennaProperties', 'config.json']
        result = run_external(cmd, folder, folder, session.issues, session.events,
                              f'macro_signoff_{module}',
                              timeout=physical.get('timeout_s',14400), **runner_options)
        if result['status'] != 'PASS':
            diagnostic=classify_macro_hardening_failure(folder/('macro_signoff_'+module+'.log'),result)
            # An XOR count is a real failed geometry check, not a reason to
            # downgrade or suppress verification. Preserve that failure and
            # explain exactly which child GDS pair must be inspected.
            issue = session.issues.add('VERIFY.MACRO_SIGNOFF_FAILED', 'ERROR', 'PHYSICAL',
                'macro_signoff', f'LibreLane signoff failed for {module}.' +
                (f' Magic/KLayout GDS XOR count: {diagnostic["xor_difference_count"]}.'
                 if diagnostic['status']=='MAGIC_KLAYOUT_XOR_MISMATCH' else ''),
                evidence={**result,'macro_diagnostics':diagnostic},
                remedy=diagnostic['remedy'])
            session._done('macro_signoff', 'FAIL', module=module,
                          issue_id=issue.issue_id, result=result, diagnostics=diagnostic)
            return False
        # Verification must never silently replace the original layout.
        if not all(path.is_file() and artifact_hash(path) == expected for path,expected in files):
            issue = session.issues.add('VERIFY.MACRO_VIEW_CHANGED', 'ERROR', 'FILESYSTEM',
                'macro_signoff', f'{module} physical views changed during verification.')
            session._done('macro_signoff','FAIL', module=module, issue_id=issue.issue_id)
            return False
    session._done('macro_signoff', 'PASS', modules=[x['module'] for x in children],
                  checks='LibreLane child post-layout checks, including XOR/DRC/LVS')
    return True
