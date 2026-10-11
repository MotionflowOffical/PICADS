"""Evidence-based physical artifact inspection, never a mask signoff certificate.

LibreLane completes flow steps; this layer only establishes what files and
metrics actually exist. Even DRC/LVS/timing pass is not foundry qualification.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass,asdict
from .maskinspect import inspect_gds,GDSFormatError

@dataclass
class PhysicalEvidence:
    status:str
    run_dir:str
    gds:list[str]
    metrics:str|None
    checks:dict
    notes:list[str]
    def as_dict(self):return asdict(self)

def inspect_librelane(run_dir:Path)->PhysicalEvidence:
    run_dir=Path(run_dir).resolve()
    final=run_dir/'final'
    gds=[]
    for folder in ('gds','klayout_gds','mag_gds'):
        if (final/folder).is_dir():
            gds.extend(str(p) for p in (final/folder).rglob('*') if p.is_file() and p.suffix.lower() in ('.gds','.gdsii') and p.stat().st_size>0)
    mp=final/'metrics.json'
    metrics=None;checks={};notes=[]
    readable=[]
    for name in gds:
        try:
            inspection=inspect_gds(Path(name))
            readable.append(name)
            checks.setdefault('gds_integrity',{'status':'PASS','libraries':[]})['libraries'].append({
                'file':name,'library':inspection.library,'structures':len(inspection.structures),
                'elements':inspection.elements})
        except (GDSFormatError,OSError) as exc:
            checks['gds_integrity']={'status':'FAIL','file':name,'reason':str(exc),
                                     'code':getattr(exc,'code','GDS.READ_ERROR')}
            notes.append('GDS integrity error for '+name+': '+str(exc))
    gds=readable

    if mp.is_file():
        metrics=str(mp)
        try:
            data=json.loads(mp.read_text(encoding='utf-8'))
            if not isinstance(data,dict):raise ValueError('metrics root is not a JSON object')
            # LibreLane names are documented by individual steps. Missing
            # metrics remain UNVERIFIED, not reported as zero violations.
            names={
                'drc_klayout':['klayout__drc_error__count'],
                'drc_magic':['magic__drc_error__count'],
                'lvs':['netgen__lvs_error__count','netgen__lvs__errors'],
                'antenna':['klayout__antenna_error__count'],
            }
            for label,keys in names.items():
                matched=[(k,data[k]) for k in keys if k in data]
                if not matched:checks[label]={'status':'UNVERIFIED','reason':'No recognized metric in file'}
                else:
                    invalid=any(type(v) not in (int,float) or v<0 for _,v in matched)
                    checks[label]={'status':'UNVERIFIED' if invalid else 'FAIL' if any(v>0 for _,v in matched) else 'PASS',
                                    'metrics':dict(matched)}
            # No fabricated timing pass: require at least a supported slack
            # metric, and don't infer unspecified corner closure.
            timing=[(k,v) for k,v in data.items() if k in ('timing__setup__ws','timing__setup__tns','setup__ws','setup__tns')]
            if timing and all(type(v) in (int,float) for _,v in timing):
                checks['timing']={'status':'FAIL' if any(v<0 for _,v in timing) else 'PASS','metrics':dict(timing),
                                  'scope':'reported metrics only; other PVT corners not independently checked'}
            else:checks['timing']={'status':'UNVERIFIED','reason':'No recognized setup slack metric'}
        except (ValueError,OSError) as exc:
            notes.append(f'Unusable physical metrics: {type(exc).__name__}: {exc}')
            checks['metrics']={'status':'UNVERIFIED','reason':'Invalid metrics document'}
    else:notes.append('Missing final/metrics.json; no DRC/LVS/timing claims possible')
    # Unreported checks must remain visible, not disappear from the evidence
    # object merely because the external process returned success.
    for label in ('drc_klayout','drc_magic','lvs','antenna','timing'):
        checks.setdefault(label,{'status':'UNVERIFIED','reason':'No recognized result was supplied by the physical flow'})
    if not gds:
        notes.append('Missing nonempty final GDSII in recognized LibreLane output directories')
        status='FAIL'
    elif any(c['status']=='FAIL' for c in checks.values()):status='FAIL'
    else:status='LAYOUT_GENERATED'
    notes.append('Manufacturing mask signoff not established: foundry rule decks, mask layers, corners and qualification require independent evidence')
    return PhysicalEvidence(status,str(run_dir),gds,metrics,checks,notes)
