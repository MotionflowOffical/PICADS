"""Single entry point. Commands emit diagnosable, non-zero process status on failures."""
from __future__ import annotations
import argparse,json,sys,os,shutil
from pathlib import Path
from . import __version__
from .pipeline import BuildSession
from .tools import probe
from .dependencies import register_tool, unregister_tool, tool_status, probe_tools, settings_file, auto_detect_all
from .pdk import inspect_pdk, register_pdk, clear_pdk, pdk_status
from .project import snapshot,restore
from .ir import DLS


def init_project(path:Path):
    root=Path(path).resolve();root.mkdir(parents=True,exist_ok=True)
    from .project import atomic_write
    samples={
      'chip.yaml': 'name: ArithmeticExample\nmcd: design.mcd\nsource: circuit.py\nco: architecture.co\nphysical:\n  enabled: false\n',
      'design.mcd': 'top: calculate\ndescription: Automatically synthesized 4-bit arithmetic circuit\nmodules:\n  - name: Arithmetic\n    purpose: Select addition or multiplication based on d\n',
      'architecture.co':'architecture:\n  adder: auto\n',
      'circuit.py':'def calculate(a: u4, b: u4, d: bool) -> u8:\n    if d:\n        return a * b\n    return a + b\n',
    }
    existed=[]
    for name,data in samples.items():
        p=root/name
        if p.exists():existed.append(name)
        else:atomic_write(p,data)
    return {'created':str(root),'unchanged_existing_files':existed}

def main(argv=None)->int:
    ap=argparse.ArgumentParser(prog='picads',description='PICADS procedural integrated circuit design and automation')
    ap.add_argument('--version',action='version',version=__version__)
    commands=ap.add_subparsers(dest='command',required=True)
    for c in ('compile','build','physical','doctor','gui','init','backup','restore','simulate','trace','diagnose','inspect-mask','render-mask','physical-preflight'):
        sp=commands.add_parser(c)
        if c not in ('doctor',):sp.add_argument('project',nargs='?',default='.')
        if c=='restore':sp.add_argument('archive');sp.add_argument('--confirm',action='store_true')
        if c=='backup':sp.add_argument('--label',default='manual')
        if c=='simulate':sp.add_argument('--inputs',required=True,help='JSON input values, e.g. {"a":3,"b":2,"d":1}')
        if c=='trace':
            sp.add_argument('--vectors',required=True,help='Path to JSON list of input-vector dictionaries')
            sp.add_argument('--output',help='Output VCD path (default: build/latest/trace.vcd)')
            sp.add_argument('--clock-period-ns',type=int,default=10)
            sp.add_argument('--include-internal',action='store_true')
        if c=='diagnose':sp.add_argument('--include-source',action='store_true',help='Explicitly include source files in the bug report')
        if c=='render-mask':
            sp.add_argument('--output',help='SVG output path; default is next to input GDS file')
            sp.add_argument('--top',help='Specify GDS top cell, required if ambiguous')
            sp.add_argument('--max-shapes',type=int,default=20000)
    dep=commands.add_parser('dependencies',help='List/register/clear external EDA applications and installation folders')
    dep.add_argument('operation',choices=('list','wsl-status','set','clear','auto','catalog','install','repair'),nargs='?',default='list')
    dep.add_argument('tool',nargs='?')
    dep.add_argument('path',nargs='?')
    dep.add_argument('--folder',action='store_true',help='Register installation directory instead of executable')
    pdk=commands.add_parser('pdk',help='Read-only PDK inventory and selected technology folder')
    pdk.add_argument('operation',choices=('status','inspect','set','clear'),nargs='?',default='status')
    pdk.add_argument('path',nargs='?')
    ns=ap.parse_args(argv)
    try:
        if ns.command=='pdk':
            if ns.operation=='inspect':
                if not ns.path:raise ValueError('Usage: picads pdk inspect FOLDER')
                result=inspect_pdk(ns.path)
            elif ns.operation=='set':
                if not ns.path:raise ValueError('Usage: picads pdk set FOLDER')
                result=register_pdk(ns.path)
            elif ns.operation=='clear':result=clear_pdk()
            else:result=pdk_status()
        elif ns.command=='dependencies':
            if ns.operation=='list':
                from .wsl_backend import backend_status
                result={'registry':str(settings_file()),'tools':probe_tools(),
                        'librelane_wsl_backend':backend_status()}
            elif ns.operation=='wsl-status':
                from .wsl_backend import backend_status
                result=backend_status(live=True)
            elif ns.operation=='catalog':
                from .windows_installer import install_catalog, dependency_root
                result={'install_root':str(dependency_root()),'packages':install_catalog()}
            elif ns.operation=='install':
                if not ns.tool:raise ValueError('Usage: picads dependencies install oss-cad-suite|klayout|kicad|librelane')
                from .windows_installer import install_selected
                result=install_selected(ns.tool.split(','),progress=lambda line:print(line,file=sys.stderr,flush=True))
            elif ns.operation=='repair':
                if not ns.tool:raise ValueError('Usage: picads dependencies repair oss-cad-suite|klayout')
                from .windows_installer import repair_package
                result=repair_package(ns.tool, progress=lambda line:print(line,file=sys.stderr,flush=True))
            elif ns.operation=='auto':result={'registry':str(settings_file()),'tools':auto_detect_all()}
            elif ns.operation=='set':
                if not ns.tool or not ns.path:raise ValueError('Usage: picads dependencies set TOOL PATH [--folder]')
                result={'tool':ns.tool,'status':register_tool(ns.tool,ns.path,'folder' if ns.folder else 'app')}
            else:
                if not ns.tool:raise ValueError('Usage: picads dependencies clear TOOL')
                result={'tool':ns.tool,'status':unregister_tool(ns.tool)}
        elif ns.command=='doctor':
            from .wsl_backend import backend_status
            result={'python':sys.version.split()[0],'tools':probe(),'librelane_wsl_backend':backend_status(live=True),'pdk':pdk_status(),'pyside6':bool(__import__('importlib').util.find_spec('PySide6')),
                    'status':'External tools are optional for compile; native tools enable RTL tests; ASIC physical backend remains optional and separately configured',
                    'windows_native_installable':['oss-cad-suite','klayout','kicad (WinGet)'],
                    'full_asic_backend':'LibreLane selectable guided WSL2/Docker setup (not native Windows; smoke test required)'}
        elif ns.command=='init':result=init_project(Path(ns.project))
        elif ns.command=='backup':result=snapshot(Path(ns.project),ns.label)
        elif ns.command=='restore':result=restore(Path(ns.project),Path(ns.archive),ns.confirm)
        elif ns.command=='diagnose':
            from .diagnose import package
            result=package(Path(ns.project),include_source=ns.include_source)
        elif ns.command=='inspect-mask':
            from .maskinspect import inspect_gds
            result=inspect_gds(Path(ns.project)).as_dict()
        elif ns.command=='render-mask':
            from .maskrender import render_gds_svg
            file=Path(ns.project)
            target=Path(ns.output) if ns.output else file.with_suffix('.preview.svg')
            result=render_gds_svg(file,target,top=ns.top,max_shapes=ns.max_shapes).as_dict()
        elif ns.command=='gui':
            from .gui import launch
            return launch(Path(ns.project))
        elif ns.command=='physical-preflight':
            from .physical_flow import physical_preflight
            compile_result=BuildSession(Path(ns.project),mode='compile')
            result_compile=compile_result.run()
            if not compile_result.dls:
                result={'status':'BLOCKED','reason':'Logical compiler failed; no reliable RTL to implement',
                        'compile':result_compile.as_dict()}
            else:
                physical_config=compile_result.project.config.get('physical') or {}
                toolconf=compile_result.project.config.get('tools') or {}
                preflight=physical_preflight(physical_config,compile_result.dls.requires_clock(),
                    execution=toolconf.get('execution','native'),
                    wsl_distribution=toolconf.get('wsl_distribution'))
                from .project import atomic_write
                destination=compile_result.out/'physical_preflight.json'
                atomic_write(destination,json.dumps(preflight.as_dict(),indent=2))
                result={'status':preflight.status,'report':str(destination),
                        'compile_status':result_compile.status,'checks':preflight.checks,'notes':preflight.notes,
                        'librelane_config':preflight.librelane_config}
            print(json.dumps(result,indent=2,default=str))
            return 0 if result['status']=='READY_TO_ATTEMPT' else 2
        else:
            session=BuildSession(Path(ns.project),mode='compile' if ns.command in ('simulate','trace') else ns.command)
            outcome=session.run()
            result=outcome.as_dict()
            if ns.command=='simulate' and session.dls:
                inputs=json.loads(ns.inputs)
                dls=session.dls
                mode=(dls.metadata.get('schedule') or {}).get('mode')
                if mode=='time_share':
                    if 'start' in inputs:raise ValueError('Do not provide start for CLI transaction simulation; the command controls START/READY/DONE.')
                    if set(inputs)!=set(dls.inputs)-{'start'}:
                        raise ValueError('Time-shared simulate input names must match source input names exactly.')
                    sim=dls.new_simulator()
                    sim.step({**inputs,'start':1},clock=True)
                    for _ in range(dls.metadata['schedule']['execution_cycles']+1):
                        sim.step({**inputs,'start':0},clock=True)
                    result['simulated_output']=sim.step({**inputs,'start':0},clock=False)
                    result['simulation_protocol']='clocked time_share transaction, output available when done=1'
                    result['simulated_clock_edges']=sim.cycle
                elif dls.metadata.get('pipeline'):
                    if 'input_valid' in inputs:raise ValueError('Do not supply input_valid for CLI single-vector pipelining; use trace for custom streams.')
                    if set(inputs)!=set(dls.inputs)-{'input_valid'}:
                        raise ValueError('Pipelined simulate inputs must match source input names exactly.')
                    sim=dls.new_simulator()
                    sim.step({**inputs,'input_valid':1},clock=True)
                    for _ in range(dls.metadata['pipeline']['stages']-1):
                        sim.step({**inputs,'input_valid':0},clock=True)
                    result['simulated_output']=sim.step({**inputs,'input_valid':0},clock=False)
                    result['simulation_protocol']='pipeline output sampled after the configured latency'
                    result['simulated_clock_edges']=sim.cycle
                else:
                    result['simulated_output']=dls.new_simulator().step(inputs)
                result['output_verification_status']=session.result.stages.get('equivalence',{}).get('status','UNVERIFIED')
            if ns.command=='trace':
                if result['status']=='FAILED' or session.dls is None:
                    result['trace_status']='BLOCKED_BY_COMPILATION'
                else:
                    from .waveform import export_vcd
                    from .project import atomic_write
                    vectors=json.loads(Path(ns.vectors).read_text(encoding='utf-8'))
                    if not isinstance(vectors,list):raise ValueError('Vectors file must be JSON array of dictionaries')
                    target=Path(ns.output) if ns.output else session.out/'trace.vcd'
                    result['trace']=export_vcd(session.dls,vectors,target,
                        clock_period_ns=ns.clock_period_ns,include_internal=ns.include_internal)
                    result['files']['vcd']=str(target)
                    atomic_write(session.out/'report.json',json.dumps(result,indent=2))
            print(json.dumps(result,indent=2,default=str))
            return 1 if result['status']=='FAILED' else 2 if result['status']=='INCOMPLETE' else 0
        print(json.dumps(result,indent=2,default=str))
        return 2 if ((ns.command=='render-mask' and result.get('status')=='PARTIAL') or (ns.command=='dependencies' and ns.operation=='install' and result.get('status')!='PASS')) else 0
    except Exception as e:
        print(json.dumps({'status':'ERROR','origin':'CLI','type':type(e).__name__,'message':str(e)},indent=2),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
