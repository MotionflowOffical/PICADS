"""Single-command v1.0 RTL-to-GDS acceptance test, with truthful outcomes.

Runs on a temporary copy of the bundled first-chip project. Produces a portable
ZIP with validation reports and native logs, never replacing any user data.
Native EDA and PDK checks are attempted only when the tools really exist.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from .dependencies import resolve_tool, probe_tools, dependency_environment, read_settings
from .physical_flow import physical_preflight
from .pipeline import BuildSession
from .project import atomic_write

ROOT = Path(__file__).resolve().parents[2]


def selected_pdk_root(pdk_name: str, requested: str | None = None) -> str | None:
    if requested:
        return str(Path(requested).expanduser().resolve())
    if os.getenv('PDK_ROOT'):
        return str(Path(os.environ['PDK_ROOT']).expanduser().resolve())
    selected = read_settings().get('pdk_directory')
    if not selected:
        return None
    folder = Path(selected).expanduser().resolve()
    # PICADS Settings selects a PDK directory for inventory; LibreLane needs
    # its parent if the selection itself is e.g. /somewhere/pdks/sky130A.
    if folder.name == pdk_name:
        return str(folder.parent)
    return str(folder)


def _copy_project(destination: Path) -> Path:
    example = ROOT/'examples'/'first_physical_chip'
    if not (example/'chip.yaml').is_file():
        raise FileNotFoundError('Missing bundled first_physical_chip project')
    destination.mkdir(parents=True)
    shutil.copytree(example,destination/'project',ignore=shutil.ignore_patterns('build','.chipcompiler','__pycache__'))
    return destination/'project'


def _preserve_build(report: dict, target: Path, diagnostic_dir: Path, prefix: str) -> dict:
    build=target/'build'/'latest'
    saved=[]
    for name in ('report.json','events.jsonl','equivalence.json','rtl_verification.json','rtl_verification.log',
                 'yosys.log','physical.log','physical_evidence.json','physical_preflight.json',
                 'physical_handoff.json','config.json','physical_evidence.json'):
        p=build/name
        if p.is_file():
            dest=diagnostic_dir/(prefix+'_'+name)
            shutil.copyfile(p,dest)
            saved.append(dest.name)
    # Keep reference design artifacts for inspection on another machine.
    # Never archive private PDK contents or a full tool installation.
    for role in ('verilog','dls','gds'):
        source=report.get('files',{}).get(role)
        if not source:continue
        file=Path(source)
        if file.is_file() and file.stat().st_size<=64*1024*1024:
            dest=diagnostic_dir/(prefix+'_'+file.name)
            shutil.copyfile(file,dest)
            saved.append(dest.name)
    return {'status':report['status'],'stages':report.get('stages',{}),
            'issues':report.get('issues',[]),'diagnostics':saved}


def _run_stage(root: Path, mode: str, diagnostics: Path, prefix: str, *,
               rtl: bool = False, physical: dict | None = None) -> dict:
    project=_copy_project(root)
    if rtl or physical is not None:
        import yaml
        f=project/'chip.yaml'
        data=yaml.safe_load(f.read_text(encoding='utf-8'))
        if rtl:data.setdefault('verification',{})['external_rtl']=True
        if physical is not None:data['physical']=physical
        f.write_text(yaml.safe_dump(data,sort_keys=False),encoding='utf-8')
    outcome=BuildSession(project,mode=mode).run().as_dict()
    return _preserve_build(outcome,project,diagnostics,prefix)


def run_acceptance(output: Path, *, pdk: str = 'sky130A', pdk_root: str | None = None,
                   library: str | None = None, gui: bool = True,
                   physical_timeout: int = 5400) -> dict:
    """Returns the diagnostic summary. Partial native coverage is not PASS."""
    if not isinstance(pdk,str) or not pdk.replace('_','').isalnum():
        raise ValueError('PDK name must be a simple identifier')
    if not 60 <= physical_timeout <= 86400:
        raise ValueError('physical_timeout must be between 60 and 86400 seconds')
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    rootdir=out/'evidence';rootdir.mkdir(exist_ok=True)
    summary={'schema':1,'product':'PICADS','version':'0.16.6',
             'timestamp_utc':datetime.now(timezone.utc).isoformat(),
             'target':'bounded first-chip RTL-to-GDS acceptance',
             'statuses':{},'manufacturing_qualified':False,
             'meaning':'Independent foundry signoff is not established by this runner.'}
    stages=summary['statuses']
    tools=probe_tools()
    (rootdir/'dependencies.json').write_text(json.dumps(tools,indent=2),encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='picads-v1-acceptance-') as temp:
        workspace=Path(temp)
        compiled=_run_stage(workspace/'compile','compile',rootdir,'compile')
        eq=compiled['stages'].get('equivalence',{}).get('status')
        stages['source_to_dls_and_rtl']={'status':'PASS' if compiled['status'] in ('SUCCESS','SUCCESS_WITH_WARNINGS') and str(eq).startswith('PASS')
                                           and compiled['stages'].get('export',{}).get('status')=='PASS' else 'FAIL',
                                         'equivalence':eq,'evidence':compiled}
        if all(resolve_tool(name) for name in ('iverilog','vvp')):
            verified=_run_stage(workspace/'rtl','compile',rootdir,'rtl',rtl=True)
            value=verified['stages'].get('rtl_check',{}).get('status')
            stages['native_rtl_equivalence']={'status':'PASS' if value=='PASS' else 'FAIL',
                                              'evidence':verified}
        else:
            stages['native_rtl_equivalence']={'status':'UNAVAILABLE',
                'missing_tools':[n for n in ('iverilog','vvp') if not resolve_tool(n)],
                'remedy':'Register Icarus iverilog and vvp in Settings.'}
        if resolve_tool('yosys'):
            synthesised=_run_stage(workspace/'synthesis','build',rootdir,'synthesis')
            stage=synthesised['stages'].get('yosys',{}).get('status')
            stages['native_yosys_synthesis']={'status':'PASS' if stage=='PASS' else 'FAIL',
                                              'evidence':synthesised}
        else:
            stages['native_yosys_synthesis']={'status':'UNAVAILABLE','remedy':'Install/register Yosys in Settings.'}
        root=selected_pdk_root(pdk,pdk_root)
        physical={'enabled':True,'pdk':pdk,'clock_period_ns':20,
                  'core_utilization':35,'timeout_s':physical_timeout}
        if root:physical['pdk_root']=root
        if library:physical['std_cell_library']=library
        preflight=physical_preflight(physical,True,check_tools=True)
        stages['physical_preflight']=preflight.as_dict()
        if not resolve_tool('librelane'):
            stages['real_placement_routing_gds']={'status':'UNAVAILABLE',
                'remedy':'Install/register LibreLane and its EDA environment, and select a compatible PDK.'}
        elif stages['native_yosys_synthesis']['status']!='PASS':
            stages['real_placement_routing_gds']={'status':'BLOCKED',
                'reason':'Yosys synthesis must pass before physical implementation'}
        elif preflight.status=='BLOCKED':
            stages['real_placement_routing_gds']={'status':'BLOCKED',
                'reason':'Physical settings invalid; inspect physical_preflight.json'}
        else:
            flowed=_run_stage(workspace/'physical','physical',rootdir,'physical',physical=physical)
            physical_stage=flowed['stages'].get('physical',{}).get('status')
            evidence=flowed['stages'].get('signoff',{})
            stages['real_placement_routing_gds']={
                'status':'PASS' if physical_stage=='PASS' else 'FAIL',
                'physical_step':physical_stage,'signoff_stage':evidence,
                'evidence':flowed}
        (rootdir/'physical_preflight.json').write_text(json.dumps(preflight.as_dict(),indent=2),encoding='utf-8')
        if gui:
            try:
                import PySide6  # noqa
                import pytest  # noqa
            except ImportError:
                stages['gui_runtime']={'status':'UNAVAILABLE','reason':'PySide6/pytest unavailable'}
            else:
                log=rootdir/'qt_gui_smoke.log'
                env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
                env['QT_QPA_PLATFORM']='offscreen'
                try:
                    with log.open('w',encoding='utf-8') as handle:
                        proc=subprocess.run([sys.executable,'-m','pytest','-q','tests/test_gui_smoke.py'],
                                            cwd=ROOT,env=dependency_environment(env),
                                            stdout=handle,stderr=subprocess.STDOUT,timeout=120,check=False)
                    stages['gui_runtime']={'status':'PASS' if proc.returncode==0 else 'FAIL',
                                            'return_code':proc.returncode,'log':log.name}
                except (OSError,subprocess.TimeoutExpired) as exc:
                    stages['gui_runtime']={'status':'FAIL','reason':str(exc)}
        else:
            stages['gui_runtime']={'status':'NOT_REQUESTED'}
    stages['foundry_signoff']={'status':'UNVERIFIED','reason':'DRC/LVS/STA and manufacturing qualification require independent PDK/foundry evidence.'}
    vital=[v['status'] for name,v in stages.items() if name not in ('physical_preflight','foundry_signoff','gui_runtime')]
    summary['overall']='FAIL' if 'FAIL' in vital else 'PARTIAL' if any(s!='PASS' for s in vital) else 'LOGICAL_AND_LAYOUT_CHECKS_COMPLETE'
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    (out/'INSTRUCTIONS.txt').write_text('PICADS first-chip acceptance report. Upload the generated ZIP to ChatGPT.\n'
       'PASS means that a stage really ran, not that mask manufacturing is qualified.\n'
       'Physical process qualification is always separate.\n',encoding='utf-8')
    # Versioned folders contain dots (v0.14.0); Path.with_suffix would silently
    # truncate the promised report name. Append .zip to the entire basename.
    archive=Path(str(out)+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for entry in sorted(out.rglob('*')):
            if entry.is_file():z.write(entry,entry.relative_to(out))
    summary['zip']=str(archive)
    return summary


def main(argv=None):
    ap=argparse.ArgumentParser(description='PICADS v1 baseline hardware-to-GDS acceptance test')
    ap.add_argument('--output',default='validation/PICADS_v0.16.6_v1_acceptance')
    ap.add_argument('--pdk',default='sky130A')
    ap.add_argument('--pdk-root',default=None)
    ap.add_argument('--std-cell-library',default=None)
    ap.add_argument('--physical-timeout',type=int,default=5400)
    ap.add_argument('--skip-gui',action='store_true')
    ns=ap.parse_args(argv)
    try:
        report=run_acceptance(Path(ns.output),pdk=ns.pdk,pdk_root=ns.pdk_root,
                              library=ns.std_cell_library,physical_timeout=ns.physical_timeout,
                              gui=not ns.skip_gui)
    except Exception as exc:
        print(json.dumps({'status':'FAIL','type':type(exc).__name__,'message':str(exc)},indent=2),file=sys.stderr)
        return 1
    print(json.dumps({'status':report['overall'],'zip':report['zip'],
                      'stages':{k:v['status'] for k,v in report['statuses'].items()}},indent=2))
    return 1 if report['overall']=='FAIL' else 2 if report['overall']=='PARTIAL' else 0


if __name__=='__main__':
    raise SystemExit(main())
