"""PICADS CO hierarchical *logical* floorplan planner.

This module deliberately does NOT pretend that drawn rectangles are PDK-placed
cells. The regions become enforceable only after a technology-mapped instance
binding and an EDA placement hook are verified. See docs/MODULE_FLOORPLANNING.md.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from html import escape
import json
import math
from pathlib import Path
import re

_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class FloorplanError(ValueError):
    pass


def _quantity(value, key, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise FloorplanError(f'CO.FLOORPLAN_INVALID: {key} must be a finite {"positive" if positive else "nonnegative"} number')
    return float(value)


def _rectangle(value, key):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise FloorplanError(f'CO.FLOORPLAN_INVALID: {key} requires [x0, y0, x1, y1] in um')
    r = [_quantity(v, key) for v in value]
    if r[2] <= r[0] or r[3] <= r[1]:
        raise FloorplanError(f'CO.FLOORPLAN_INVALID: {key} has non-positive size')
    return r


def _inside(small, large, eps=1e-7):
    return small[0] >= large[0]-eps and small[1] >= large[1]-eps and small[2] <= large[2]+eps and small[3] <= large[3]+eps


def _spacing(config, defaults, path):
    for key in ('min_spacing_um', 'max_spacing_um', 'preferred_spacing_um', 'border_um'):
        if key in config:
            _quantity(config[key], f'{path}.{key}')
    low = _quantity(config.get('min_spacing_um', defaults['min_spacing_um']), path+'.min_spacing_um')
    high = _quantity(config.get('max_spacing_um', defaults['max_spacing_um']), path+'.max_spacing_um')
    preferred = _quantity(config.get('preferred_spacing_um', defaults['preferred_spacing_um']), path+'.preferred_spacing_um')
    border = _quantity(config.get('border_um', defaults['border_um']), path+'.border_um')
    if low > high or not low <= preferred <= high:
        raise FloorplanError(f'CO.FLOORPLAN_SPACING: {path}: expected min_spacing <= preferred_spacing <= max_spacing')
    return {'min_spacing_um':low,'max_spacing_um':high,'preferred_spacing_um':preferred,'border_um':border}


def _dls_paths(dls):
    """Actual pre-synthesis instances, not inferred logical declarations."""
    found = {}
    def visit(mod, path, seen):
        if id(mod) in seen:
            raise FloorplanError('CO.FLOORPLAN_RECURSIVE: DLS instance tree is recursive')
        for instance in mod.instances:
            child = mod.submodules[instance['module']]
            route = path + '/' + instance['name']
            found[route] = {'module': child.name, 'source_function': instance.get('source_function', child.name),
                            'nodes':len(child.nodes), 'registers':len(child.registers)}
            visit(child, route, seen | {id(mod)})
    visit(dls, dls.name, set())
    return found


def _default_modules(dls, architecture):
    """Derive only present source functions/real DLS instances; never invent ALUs."""
    if dls.instances:
        return [{'name': item['name'], 'instance': f'{dls.name}/{item["name"]}'} for item in dls.instances]
    # A flattened transaction has no verifiable submodule placement identities.
    return [{'name': dls.name, 'source_function':dls.name}]


def _build_spec(raw, context, ancestors=(), names=None):
    if not isinstance(raw, dict):
        raise FloorplanError('CO.FLOORPLAN_INVALID: every module must be a mapping')
    unknown = set(raw)-{'name','source_function','instance','resource','weight','modules','required',
                        'min_spacing_um','max_spacing_um','preferred_spacing_um','border_um',
                        'min_width_um','min_height_um','enforcement'}
    if unknown:
        raise FloorplanError('CO.FLOORPLAN_UNKNOWN: unsupported module fields: '+', '.join(sorted(unknown)))
    mode = raw.get('enforcement', context['default_enforcement'])
    if mode not in ('guide','validate','required'):
        raise FloorplanError('CO.FLOORPLAN_ENFORCEMENT: module enforcement must be guide, validate or required')
    name = raw.get('name')
    if not isinstance(name,str) or not _NAME.fullmatch(name):
        raise FloorplanError('CO.FLOORPLAN_INVALID: module name must be a simple hardware identifier')
    path = '/'.join((*ancestors, name))
    if path in context['names']:
        raise FloorplanError('CO.FLOORPLAN_DUPLICATE: '+path)
    context['names'].add(path)
    selectors=[k for k in ('source_function','instance','resource') if k in raw]
    if len(selectors)>1:
        raise FloorplanError('CO.FLOORPLAN_BINDING: specify at most one of source_function, instance and resource for '+path)
    for key in selectors:
        if not isinstance(raw[key],str) or not raw[key].strip():
            raise FloorplanError(f'CO.FLOORPLAN_BINDING: {path}.{key} must be nonempty')
    if 'required' in raw and type(raw['required']) is not bool:
        raise FloorplanError('CO.FLOORPLAN_INVALID: required must be true/false')
    reason = ''
    if 'source_function' in raw and raw['source_function'] not in context['reachable']:
        reason='source function not reachable from top'
    if 'instance' in raw and raw['instance'] not in context['instances']:
        reason='no actual generated DLS instance at requested path'
    if 'resource' in raw and context['resources'].get(raw['resource'],0)==0:
        reason='resource was not allocated by CO'
    if reason:
        if raw.get('required',False) or mode != 'guide':
            raise FloorplanError('CO.FLOORPLAN_REQUIRED: '+path+': '+reason)
        context['pruned'].append({'module':path,'reason':reason})
        return None
    children=raw.get('modules',[])
    if not isinstance(children,list):
        raise FloorplanError('CO.FLOORPLAN_INVALID: '+path+'.modules must be a list')
    selected=[]
    for child in children:
        spec=_build_spec(child,context,(*ancestors,name))
        if spec is not None:selected.append(spec)
    weight=_quantity(raw.get('weight',1),path+'.weight',positive=True)
    width=_quantity(raw.get('min_width_um',0),path+'.min_width_um')
    height=_quantity(raw.get('min_height_um',0),path+'.min_height_um')
    if 'instance' in raw:
        binding='DLS_INSTANCE_PRE_SYNTHESIS'
    elif 'source_function' in raw:
        binding='FUNCTIONAL_ONLY_NOT_CELL_MAPPED'
    elif 'resource' in raw:
        binding='CO_RESOURCE_NOT_CELL_MAPPED'
    else:
        binding='DESCRIPTIVE_ONLY'
    if mode == 'validate' and binding != 'DLS_INSTANCE_PRE_SYNTHESIS':
        raise FloorplanError('CO.FLOORPLAN_VALIDATION_UNBOUND: '+path+' needs a real DLS instance path to validate')
    if mode == 'required':
        raise FloorplanError('CO.FLOORPLAN_ENFORCEMENT_UNSUPPORTED: '+path+': required cell placement needs technology-mapped instance provenance and a verified placement-region backend; PICADS cannot enforce it yet')
    return {'name':name,'path':path,'selector':{key:raw[key] for key in selectors},'binding':binding,'enforcement':mode,
            'weight':weight,'min_width_um':width,'min_height_um':height,'settings':raw,'children':selected}


def _split(node_list, rect, gap):
    """Deterministic weighted guillotine division with exact sibling gap."""
    if len(node_list)==1:
        return [(node_list[0],rect)]
    x0,y0,x1,y1=rect
    w,h=x1-x0,y1-y0
    vertical = w >= h
    available = (w if vertical else h)-gap
    if available <= 0:
        raise FloorplanError('CO.FLOORPLAN_NO_SPACE: module bounds cannot fit the requested sibling spacing')
    total=sum(x['weight'] for x in node_list)
    pivot=min(range(1,len(node_list)),key=lambda i:abs(sum(x['weight'] for x in node_list[:i])-total/2))
    a=node_list[:pivot];b=node_list[pivot:]
    ratio=sum(x['weight'] for x in a)/total
    first=available*ratio
    if vertical:
        ra=[x0,y0,x0+first,y1];rb=[x0+first+gap,y0,x1,y1]
    else:
        ra=[x0,y0,x1,y0+first];rb=[x0,y0+first+gap,x1,y1]
    return _split(a,ra,gap)+_split(b,rb,gap)


def _parse_keepouts(keepouts, region, physical):
    """Independent CO placement exclusions; never confuse with module fences.

    FP_OBSTRUCTIONS are supported by LibreLane. A hard keepout forbids
    standard-cell placement throughout the rectangle; it does NOT assign
    any module to a different rectangle. A soft keepout only influences
    initial placement and cannot be classified as a hard guarantee.
    """
    if not isinstance(keepouts,list):
        raise FloorplanError('CO.FLOORPLAN_KEEPOUT_FORMAT: keepouts must be a list')
    result=[];names=set()
    for i,entry in enumerate(keepouts):
        if not isinstance(entry,dict) or set(entry)-{'name','bounds_um','kind','enforcement'}:
            raise FloorplanError('CO.FLOORPLAN_KEEPOUT_FORMAT: keepout requires name, bounds_um, kind and enforcement only')
        name=entry.get('name')
        if not isinstance(name,str) or not _NAME.fullmatch(name) or name in names:
            raise FloorplanError('CO.FLOORPLAN_KEEPOUT_NAME: unique hardware identifier required')
        names.add(name)
        bounds=_rectangle(entry.get('bounds_um'),f'floorplan.keepouts[{i}].bounds_um')
        if not _inside(bounds,region):
            raise FloorplanError('CO.FLOORPLAN_KEEPOUT_BOUNDS: '+name+' is outside floorplan region')
        kind=entry.get('kind','hard')
        enforcement=entry.get('enforcement','guide')
        if kind not in ('hard','soft') or enforcement not in ('guide','required'):
            raise FloorplanError('CO.FLOORPLAN_KEEPOUT_MODE: kind must be hard/soft; enforcement guide/required')
        if enforcement=='required':
            if kind=='soft':
                raise FloorplanError('CO.FLOORPLAN_SOFT_NOT_HARD: soft obstructions cannot guarantee empty space')
            die=physical.get('die_area_um')
            if die is None or not _inside(bounds,_rectangle(die,'physical.die_area_um')):
                raise FloorplanError('CO.FLOORPLAN_KEEPOUT_DIE: hard keepouts require explicit physical.die_area_um containing the region')
            if not physical.get('enabled',False):
                raise FloorplanError('CO.FLOORPLAN_KEEPOUT_PHYSICAL_DISABLED: physical.enabled must be true for enforced keepouts')
        result.append({'name':name,'bounds_um':bounds,'kind':kind,'enforcement':enforcement,
                       'status':'CONFIG_READY_NOT_YET_PLACED' if enforcement=='required' else 'GUIDE_ONLY'})
    hard=[r for r in result if r['kind']=='hard' and r['enforcement']=='required']
    for i,a in enumerate(hard):
        for b in hard[i+1:]:
            x0=max(a['bounds_um'][0],b['bounds_um'][0]);x1=min(a['bounds_um'][2],b['bounds_um'][2])
            y0=max(a['bounds_um'][1],b['bounds_um'][1]);y1=min(a['bounds_um'][3],b['bounds_um'][3])
            if x1>x0 and y1>y0:
                raise FloorplanError('CO.FLOORPLAN_KEEPOUT_OVERLAP: '+a['name']+' and '+b['name'])
    return result


def librelane_keepout_config(plan):
    """Translate only explicit, hard, requested CO exclusions to LL.

    Individual regions are NOT module fences. This translation is supported by
    LibreLane's FP_OBSTRUCTIONS, independent of technology-mapped cell names.
    """
    hard=[x['bounds_um'] for x in plan.get('keepouts',[]) if x['enforcement']=='required' and x['kind']=='hard']
    return {'FP_OBSTRUCTIONS':hard} if hard else {}


def plan_floorplan(settings, dls, architecture, co=None, physical=None):
    """Return a checked, source-connected logical-region plan in micrometers.

    `enforcement: required` is purposely rejected: no PNR cell-region binding
    exists yet; silent fallback to a decorative SVG would be dangerous.
    """
    if not isinstance(settings,dict):
        raise FloorplanError('CO.FLOORPLAN_INVALID: floorplan must be a mapping')
    allowed={'enabled','enforcement','region_um','min_spacing_um','max_spacing_um',
             'preferred_spacing_um','border_um','modules','keepouts'}
    unknown=set(settings)-allowed
    if unknown:
        raise FloorplanError('CO.FLOORPLAN_UNKNOWN: '+', '.join(sorted(unknown)))
    if type(settings.get('enabled',True)) is not bool:
        raise FloorplanError('CO.FLOORPLAN_INVALID: enabled must be boolean')
    if settings.get('enforcement','guide') not in ('guide','validate','required'):
        raise FloorplanError('CO.FLOORPLAN_INVALID: enforcement must be guide, validate or required')
    p = physical or {}
    if 'region_um' in settings:
        region=_rectangle(settings['region_um'],'floorplan.region_um')
    elif 'die_area_um' in p:
        region=_rectangle(p['die_area_um'],'physical.die_area_um')
    else:
        raise FloorplanError('CO.FLOORPLAN_NO_REGION: set floorplan.region_um or physical.die_area_um; cannot infer physical um from logical gate counts')
    if 'die_area_um' in p and not _inside(region,_rectangle(p['die_area_um'],'physical.die_area_um')):
        raise FloorplanError('CO.FLOORPLAN_OUTSIDE_DIE: floorplan bounds extend beyond configured physical die')
    defaults=_spacing(settings,{'min_spacing_um':0,'max_spacing_um':1000000,
                                'preferred_spacing_um':0,'border_um':0},'floorplan')
    instances=_dls_paths(dls)
    schedule=(dls.metadata.get('schedule') or {})
    resources=schedule.get('physical_units') or dls.metadata.get('operator_counts') or {}
    context={'reachable':set(architecture.reachable),'instances':instances,'resources':resources,
             'pruned':[], 'names':set(), 'default_enforcement':settings.get('enforcement','guide')}
    modules=settings.get('modules')
    if modules is None:modules=_default_modules(dls, architecture)
    if not isinstance(modules,list) or not modules:
        raise FloorplanError('CO.FLOORPLAN_INVALID: modules must be a nonempty list')
    parsed=[_build_spec(node,context) for node in modules]
    roots=[node for node in parsed if node is not None]
    if not roots:
        raise FloorplanError('CO.FLOORPLAN_EMPTY: all modules were pruned; no actual functional work remains')
    result=[]
    def place(nodes,region_box,settings_here,parent=None):
        spacing=_spacing(settings_here,defaults,parent or 'floorplan')
        border=spacing['border_um']
        inner=[region_box[0]+border,region_box[1]+border,region_box[2]-border,region_box[3]-border]
        if inner[2]<=inner[0] or inner[3]<=inner[1]:
            raise FloorplanError('CO.FLOORPLAN_NO_SPACE: borders consume region '+(parent or 'root'))
        allocations=_split(nodes,inner,spacing['preferred_spacing_um'])
        for n,r in allocations:
            if r[2]-r[0]+1e-8<n['min_width_um'] or r[3]-r[1]+1e-8<n['min_height_um']:
                raise FloorplanError('CO.FLOORPLAN_TOO_SMALL: '+n['path']+' violates minimum module dimensions')
            record={'name':n['name'],'path':n['path'],'parent':parent,'bounds_um':[round(x,6) for x in r],
                    'binding':n['binding'],'enforcement':n['enforcement'],'selector':n['selector'],'weight':n['weight'],'children':[ch['path'] for ch in n['children']]}
            result.append(record)
            if n['children']:
                place(n['children'],r,n['settings'],n['path'])
    place(roots,region,settings)
    exclusions=_parse_keepouts(settings.get('keepouts',[]),region,p)
    validated=any(m['enforcement']=='validate' for m in result)
    return {'schema':2,'status':'PLAN_VALIDATED_NOT_PLACED' if validated else 'GUIDE_ONLY_NOT_ENFORCED','units':'um',
            'region_um':region,'modules':result,'keepouts':exclusions,'pruned':context['pruned'],
            'min_spacing_um':defaults['min_spacing_um'], 'max_spacing_um':defaults['max_spacing_um'],
            'preferred_spacing_um':defaults['preferred_spacing_um'],
            'actual_dls_instances':instances,'allocated_operator_resources':resources,
            'warnings':['Logical region coordinates are NOT standard-cell placement constraints.',
                        'No routed GDS/DEF membership or physical timing is verified by this plan.',
                        'Module separation can add wire length and congestion; compare physical metrics.']}


def render_floorplan_svg(plan, target):
    """Resolution-independent visualization of *planned*, not routed, regions."""
    target=Path(target)
    x0,y0,x1,y1=plan['region_um'];w=x1-x0;h=y1-y0
    if w<=0 or h<=0:raise FloorplanError('Cannot draw zero-sized die')
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {w} {h}" width="1200" height="{max(250,round(1200*h/w))}">',
           f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="#f8fafc" stroke="#334155" stroke-width="{min(w,h)/350}"/>']
    colors=['#cbd5e1','#c7d2fe','#bae6fd','#bbf7d0','#fed7aa','#fecdd3']
    for i,item in enumerate(plan['modules']):
        a,b,c,d=item['bounds_um'];depth=item['path'].count('/')
        stroke=max(min(w,h)/600,0.05)
        lines.append(f'<rect x="{a}" y="{b}" width="{c-a}" height="{d-b}" fill="{colors[depth%len(colors)]}" fill-opacity="0.75" stroke="#334155" stroke-width="{stroke}"/>')
        font=min((c-a)/max(len(item['name'])*0.65,1), (d-b)/3, min(w,h)/45)
        if font>0.5:
            lines.append(f'<text x="{a+(c-a)/2}" y="{b+(d-b)/2}" font-size="{font}" fill="#172554" text-anchor="middle" font-family="sans-serif">{escape(item["name"])}</text>')
    for item in plan.get('keepouts',[]):
        a,b,c,d=item['bounds_um']
        stroke='#b91c1c' if item['enforcement']=='required' else '#9ca3af'
        lines.append(f'<rect x="{a}" y="{b}" width="{c-a}" height="{d-b}" fill="none" stroke="{stroke}" stroke-dasharray="2 1" stroke-width="{max(min(w,h)/300,0.1)}"/>')
    lines.append('</svg>')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return target
