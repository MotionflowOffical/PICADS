"""Reproducible diagnostic bundle; no blanket harvesting of personal project files."""
from __future__ import annotations
import json,sys,os,hashlib,zipfile,datetime,platform,subprocess,shutil
from pathlib import Path
from .tools import probe
from .project import atomic_write

def package(root:Path,destination:Path|None=None,include_source:bool=False)->dict:
    root=Path(root).resolve();build=root/'build'/'latest'
    if not (build/'report.json').is_file():raise FileNotFoundError('No build report; run compile/build first')
    report=json.loads((build/'report.json').read_text(encoding='utf-8'))
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=Path(destination).resolve() if destination else build/f'diagnostic-{stamp}.zip'
    target.parent.mkdir(parents=True,exist_ok=True)
    filelist=[]
    for suffix in ('report.json','events.jsonl','equivalence.json','yosys.log','physical.log'):
        p=build/suffix
        if p.is_file():filelist.append(p)
    inputs={}
    for p in sorted(root.rglob('*')):
        if not p.is_file() or any(part in ('build','.chipcompiler','.git') for part in p.relative_to(root).parts):continue
        if p.stat().st_size>10_000_000:continue
        rel=p.relative_to(root).as_posix()
        if p.suffix in ('.py','.co','.mcd','.yaml','.yml','.json','.v','.dls'):
            inputs[rel]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            if include_source:filelist.append(p)
    env={
        'chipcompiler_run_id':report.get('run_id'),'build_status':report.get('status'),
        'python':sys.version,'platform':platform.platform(),'external_tools':probe(),
        'inputs':inputs,'source_contents_included':include_source,
        'notes':['No environment variables, API keys or arbitrary home-directory files are packaged.',
                 'Source code is excluded unless --include-source is explicitly requested.',
                 'Reproduce with: python -m chipcompiler compile <project-root>',
                 'Inspect report.json issues: issue_id, origin, stage, code, evidence and blocked_by.']}
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('environment_manifest.json',json.dumps(env,indent=2))
        for p in filelist:
            relative=p.relative_to(build).as_posix() if p.is_relative_to(build) else 'source/'+p.relative_to(root).as_posix()
            z.write(p,relative)
    return {'status':'PACKAGED','archive':str(target),'files_included':len(filelist),'source_included':include_source,
            'last_run_status':report.get('status')}
