"""Read-only GDSII geometry preview from ACTUAL polygons and hierarchy.

This is not mask preparation, DRC, LVS, or a replacement for KLayout.
Only BOUNDARY, BOX and PATH geometry is rendered. TEXT is omitted with
an explicit warning. SREF and AREF support affine magnification, rotation,
and reflection; unresolved/recursive references fail instead of disappearing.
Limits are explicit and output is tagged PARTIAL when clipping occurs.
"""
from __future__ import annotations
import math, struct, html
from pathlib import Path
from dataclasses import dataclass,asdict
from collections import Counter
from .maskinspect import inspect_gds,GDSFormatError
from .project import atomic_write

@dataclass
class RenderReport:
    file:str
    svg:str
    status:str
    top:str
    visible_shapes:int
    layers:dict
    dbu_meters:float|None
    warnings:list[str]
    def as_dict(self):return asdict(self)


def _real8(data):
    if len(data)!=8:raise GDSFormatError('GDS.REAL8','Expected eight-byte GDS real')
    if not any(data):return 0.0
    value=int.from_bytes(data[1:],'big')/(1<<56) * 16**((data[0]&127)-64)
    return -value if data[0]&128 else value


def _compose(p,q):
    a,b,c,d,x,y=p;A,B,C,D,X,Y=q
    return (a*A+b*C,a*B+b*D,c*A+d*C,c*B+d*D,a*X+b*Y+x,c*X+d*Y+y)


def _affine(reflection=False,angle=0.0,mag=1.0,x=0.0,y=0.0):
    rad=math.radians(angle);co=math.cos(rad)*mag;si=math.sin(rad)*mag
    return (co,si if reflection else -si,si,-co if reflection else co,x,y)


def _point(T,p):
    a,b,c,d,x,y=T;X,Y=p
    return a*X+b*Y+x,c*X+d*Y+y


def render_gds_svg(path:Path,output:Path,top:str|None=None,max_shapes:int=20000,max_depth:int=64)->RenderReport:
    path=Path(path).resolve();output=Path(output).resolve()
    if type(max_shapes)!=int or not 1<=max_shapes<=200000:raise ValueError('max_shapes must be 1..200000')
    if type(max_depth)!=int or not 1<=max_depth<=128:raise ValueError('max_depth must be 1..128')
    inspect_gds(path)
    cells={};current=None;element=None;dbu_meters=None;omitted_text=0;unsupported=Counter()
    with path.open('rb') as f:
        while (hdr:=f.read(4)):
            length,kind,dtype=struct.unpack('>HBB',hdr);data=f.read(length-4)
            if kind==3 and len(data)==16:dbu_meters=_real8(data[8:16])
            elif kind==5:current={'name':None,'shapes':[],'refs':[]}
            elif kind==6 and current is not None:
                name=data.rstrip(b'\0').decode('ascii','replace')
                if name in cells:raise GDSFormatError('GDS.DUPLICATE_CELL',f'Duplicate cell name {name!r}')
                current['name']=name
            elif kind in (8,9,10,11,12,21,45,46):element={'kind':kind,'layer':None,'width':0,'reflected':False,'mag':1,'angle':0,'xy':[],'name':None,'colrow':(1,1)}
            elif element is not None:
                if kind==13 and len(data)==2:element['layer']=struct.unpack('>h',data)[0]
                elif kind==15 and len(data)==4:element['width']=abs(struct.unpack('>i',data)[0])
                elif kind==16:
                    if len(data)%8:raise GDSFormatError('GDS.XY','XY payload not divisible by 8')
                    element['xy']=[struct.unpack('>ii',data[i:i+8]) for i in range(0,len(data),8)]
                elif kind==18:element['name']=data.rstrip(b'\0').decode('ascii','replace')
                elif kind==19 and len(data)==4:element['colrow']=struct.unpack('>HH',data)
                elif kind==26 and len(data)==2:element['reflected']=bool(struct.unpack('>H',data)[0]&0x8000)
                elif kind==27:element['mag']=_real8(data)
                elif kind==28:element['angle']=_real8(data)
                elif kind==17:
                    if current is None:raise GDSFormatError('GDS.ELEMENT_ORDER','Element has no structure')
                    k=element['kind']
                    if k in (8,9,45):
                        if element['layer'] is None or len(element['xy'])<2:
                            raise GDSFormatError('GDS.INCOMPLETE_ELEMENT','Polygon or path lacks layer/XY')
                        current['shapes'].append(element)
                    elif k in (10,11):
                        if not element['name'] or len(element['xy'])!=(1 if k==10 else 3):
                            raise GDSFormatError('GDS.INCOMPLETE_REFERENCE','Cell reference lacks name/XY')
                        current['refs'].append(element)
                    elif k==12:omitted_text+=1
                    else:unsupported[k]+=1
                    element=None
            if kind==7:
                if current is None or not current['name']:raise GDSFormatError('GDS.STRUCTURE_NAME','Missing structure name')
                cells[current['name']]=current;current=None
    referenced={ref['name'] for cell in cells.values() for ref in cell['refs']}
    if top is None:
        roots=sorted(set(cells)-referenced)
        if len(roots)!=1:
            raise GDSFormatError('GDS.AMBIGUOUS_TOP',f'Expected one top cell, found {roots!r}; specify top explicitly')
        top=roots[0]
    if top not in cells:raise GDSFormatError('GDS.TOP_MISSING',f'Unknown top cell {top!r}')
    warnings=[]
    if omitted_text:warnings.append(f'{omitted_text} GDS TEXT elements omitted from geometry preview')
    if unsupported:warnings.append('Unsupported elements omitted: '+str(dict(unsupported)))
    if dbu_meters is None or not math.isfinite(dbu_meters) or dbu_meters<=0:
        warnings.append('Missing/unusable GDS UNITS: displaying raw database units, not micrometers')
        units='DBU';scale=1.0;dbu_meters=None
    else:
        scale=dbu_meters*1e6;units='µm'
    rendered=[];layers=Counter();clipped=False
    identity=(1,0,0,1,0,0)
    def flatten(name,T,stack):
        nonlocal clipped
        if name in stack:raise GDSFormatError('GDS.RECURSIVE_REFERENCE','Recursive cell reference: '+' -> '.join((*stack,name)))
        if len(stack)>=max_depth:raise GDSFormatError('GDS.REFERENCE_DEPTH','GDS reference depth limit exceeded')
        if name not in cells:raise GDSFormatError('GDS.UNKNOWN_REFERENCE',f'Reference to undefined cell {name!r}')
        cell=cells[name]
        for shape in cell['shapes']:
            if len(rendered)>=max_shapes:
                clipped=True;return
            coords=[_point(T,p) for p in shape['xy']]
            rendered.append((shape['layer'],shape['kind'],coords,shape['width'],T))
            layers[shape['layer']]+=1
        for ref in cell['refs']:
            k=ref['kind'];coords=ref['xy']
            if k==10:locations=[coords[0]]
            else:
                cols,rows=ref['colrow']
                if cols<1 or rows<1:raise GDSFormatError('GDS.BAD_ARRAY','Array dimension must be positive')
                if cols*rows>max_shapes:
                    raise GDSFormatError('GDS.ARRAY_LIMIT',f'Cell array has {cols*rows} placements; preview limit {max_shapes}')
                p0,p1,p2=coords
                locations=[(p0[0]+i*(p1[0]-p0[0])/cols+j*(p2[0]-p0[0])/rows,
                            p0[1]+i*(p1[1]-p0[1])/cols+j*(p2[1]-p0[1])/rows)
                           for j in range(rows) for i in range(cols)]
            for x,y in locations:
                if len(rendered)>=max_shapes:clipped=True;return
                mat=_affine(ref['reflected'],ref['angle'],ref['mag'],x,y)
                flatten(ref['name'],_compose(T,mat),(*stack,name))
    flatten(top,identity,())
    if clipped:warnings.append(f'Geometry was clipped at max_shapes={max_shapes}; SVG is PARTIAL')
    if not rendered:raise GDSFormatError('GDS.NO_VISIBLE_SHAPES',f'Top cell {top!r} has no renderable polygons/paths')
    all_points=[point for _,_,points,_,_ in rendered for point in points]
    minx=min(x for x,_ in all_points);maxx=max(x for x,_ in all_points)
    miny=min(y for _,y in all_points);maxy=max(y for _,y in all_points)
    if maxx==minx:maxx+=1
    if maxy==miny:maxy+=1
    width=1200;height=800;pad=30
    factor=min((width-2*pad)/(maxx-minx),(height-2*pad)/(maxy-miny))
    def pt(p):return f'{pad+(p[0]-minx)*factor:.2f},{height-pad-(p[1]-miny)*factor:.2f}'
    content=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800">',
             '<rect width="1200" height="800" fill="#09141e"/>']
    for layer,kind,coords,wirewidth,T in sorted(rendered,key=lambda item:item[0]):
        hue=(layer*67+191)%360
        rgb=f'hsl({hue},78%,62%)'
        points=' '.join(pt(p) for p in coords)
        if kind==9:
            # Affine-influenced width approximation for the preview only.
            a,b,c,d,_,_=T
            stroke=max(0.6,min(120,wirewidth*factor*math.sqrt(abs(a*d-b*c))))
            content.append(f'<polyline points="{points}" fill="none" stroke="{rgb}" stroke-width="{stroke:.2f}" opacity="0.76"/>')
        else:
            content.append(f'<polygon points="{points}" fill="{rgb}" fill-opacity="0.20" stroke="{rgb}" stroke-opacity="0.88" stroke-width="0.6"/>')
    content.append(f'<rect x="10" y="10" width="680" height="28" rx="4" fill="#071018" opacity="0.90"/>')
    header=f'{top} • {len(rendered)} real GDS shapes • {units} • {"PARTIAL" if clipped else "READ-ONLY VIEW"}'
    content.append(f'<text x="20" y="30" font-size="14" fill="#f2fafc" font-family="sans-serif">{html.escape(header)}</text>')
    content.append('</svg>')
    atomic_write(output,'\n'.join(content))
    return RenderReport(str(path),str(output),'PARTIAL' if clipped or omitted_text or unsupported else 'READ_ONLY_GEOMETRY',
                        top,len(rendered),dict(sorted(layers.items())),dbu_meters,warnings)
