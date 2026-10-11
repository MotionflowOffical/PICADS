"""User-run integration-validation suite. Standard-library bootstrap, no fake PASS.

Produces a portable ZIP containing exact stage statuses and native tool logs.
The base compiler is covered by pytest; Icarus/Yosys/physical/GUi depend on
actual local installations. A missing tool is UNAVAILABLE, never passed.
"""
from __future__ import annotations
import argparse,datetime,json,os,platform,shutil,subprocess,sys,tempfile,traceback,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def _run(argv:list[str],cwd:Path,log:Path,timeout:int=180,env:dict|None=None)->dict:
    log.parent.mkdir(parents=True,exist_ok=True)
    try:
        with log.open('w',encoding='utf-8',errors='replace') as handle:
            handle.write('COMMAND: '+repr(argv)+'\nWORKDIR: '+str(cwd)+'\n')
            handle.flush()
            result=subprocess.run(argv,cwd=cwd,stdout=handle,stderr=subprocess.STDOUT,
                                  timeout=timeout,env=env,check=False)
            handle.write('\nEXIT_CODE: '+str(result.returncode)+'\n')
        return {'status':'PASS' if result.returncode==0 else 'FAIL','exit_code':result.returncode,
                'log':log.name,'command':argv}
    except FileNotFoundError as exc:
        log.write_text(f'UNAVAILABLE: {exc}\n',encoding='utf-8')
        return {'status':'UNAVAILABLE','reason':'executable missing','log':log.name,'command':argv}
    except subprocess.TimeoutExpired as exc:
        with log.open('a',encoding='utf-8') as handle:handle.write(f'\nTIMEOUT after {timeout}s: {exc}\n')
        return {'status':'TIMEOUT','timeout_seconds':timeout,'log':log.name,'command':argv}
    except Exception as exc:
        log.write_text(traceback.format_exc(),encoding='utf-8')
        return {'status':'FAIL','reason':f'{type(exc).__name__}: {exc}','log':log.name,'command':argv}


def run_validation(output:Path,install_python_deps=False,physical_project:Path|None=None,
                   rtl_runner='auto',include_source=False)->dict:
    output=Path(output).expanduser().resolve();output.mkdir(parents=True,exist_ok=True)
    reports=output/'logs';reports.mkdir(exist_ok=True)
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
    env['PYTHONDONTWRITEBYTECODE']='1'
    summary={'run_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'platform':platform.platform(),'python':sys.version.split()[0],
             'project_version':'0.8.0','statuses':{},'warnings':[],
             'scope':'Development validation; NOT a fabrication or foundry signoff certificate.'}
    status=summary['statuses']
    def record(name,result):
        status[name]=result
        print(f'[{name}] {result["status"]}',flush=True)
        return result
    try:
        if install_python_deps:
            record('python_dependencies',_run([sys.executable,'-m','pip','install','-e','.[test,gui]'],
                 ROOT,reports/'python_dependencies.log',timeout=600,env=env))
        else:
            summary['warnings'].append('Automatic Python dependency installation disabled. Missing dependencies are reported as failures/unavailable.')
        import importlib.util
        toolkit={name:bool(importlib.util.find_spec(name)) for name in ('pytest','yaml','pycparser','PySide6')}
        tools={name:{'native_path':shutil.which(name),'available_native':bool(shutil.which(name))}
               for name in ('iverilog','vvp','yosys','librelane','openroad','klayout','magic','netgen','gcc','g++','wsl.exe')}
        wsl_tools={}
        if shutil.which('wsl.exe'):
            for tool in ('iverilog','vvp','yosys','librelane','klayout'):
                try:
                    r=subprocess.run(['wsl.exe','--exec','sh','-lc',f'command -v {tool}'],
                                     capture_output=True,text=True,timeout=8,check=False)
                    wsl_tools[tool]={'available':r.returncode==0,'path':r.stdout.strip() if r.returncode==0 else None,
                                     'stderr':r.stderr.strip()[-300:] if r.returncode else ''}
                except (subprocess.TimeoutExpired,OSError) as exc:
                    wsl_tools[tool]={'available':False,'probe_error':str(exc)}
        preferred_rtl=('native' if tools['iverilog']['available_native'] and tools['vvp']['available_native'] else
                       'wsl' if wsl_tools.get('iverilog',{}).get('available') and wsl_tools.get('vvp',{}).get('available') else 'native')
        preferred_yosys=('native' if tools['yosys']['available_native'] else
                         'wsl' if wsl_tools.get('yosys',{}).get('available') else 'native')
        selected_rtl=preferred_rtl if rtl_runner=='auto' else rtl_runner
        selected_yosys=preferred_yosys if rtl_runner=='auto' else rtl_runner
        summary['selected_external_runners']={'rtl':selected_rtl,'yosys':selected_yosys,
            'selection_rule':'Native preferred; WSL selected only if explicitly probed available, otherwise missing reported.'}
        (output/'tool_probe.json').write_text(json.dumps({'toolkit':toolkit,'tools':tools,'wsl_tools':wsl_tools},indent=2),encoding='utf-8')
        if not all(toolkit[n] for n in ('pytest','yaml','pycparser')):
            record('compiler_pytest',{'status':'BLOCKED','reason':'Required Python testing packages absent','needed':['pytest','PyYAML','pycparser']})
        else:
            record('compiler_pytest',_run([sys.executable,'-m','pytest','-q','--disable-warnings'],
                 ROOT,reports/'compiler_pytest.log',timeout=240,env=env))
        if toolkit['PySide6'] and toolkit['pytest']:
            gui_env=dict(env);gui_env['QT_QPA_PLATFORM']='offscreen'
            record('qt_gui_smoke',_run([sys.executable,'-m','pytest','-q','tests/test_gui_smoke.py','-rs'],
                 ROOT,reports/'qt_gui_smoke.log',timeout=80,env=gui_env))
        else:
            record('qt_gui_smoke',{'status':'UNAVAILABLE','reason':'PySide6 or pytest not installed, so GUI cannot be runtime tested.'})
        if toolkit['yaml'] and toolkit['pycparser']:
            for name in ('conditional_alu','transactional_memory','concurrent_fabric'):
                # Copy to an isolated temp project: never mutate user projects or
                # accidentally reuse a prior build/latest directory.
                with tempfile.TemporaryDirectory(prefix='cc-validate-') as temp:
                    source=ROOT/'examples'/name;target=Path(temp)/name
                    shutil.copytree(source,target,ignore=shutil.ignore_patterns('build','.chipcompiler','__pycache__'))
                    result=record('build_'+name,_run([sys.executable,'-m','chipcompiler','compile',str(target)],
                         ROOT,reports/f'build_{name}.log',timeout=100,env=env))
                    if name=='concurrent_fabric' and result['status']=='PASS':
                        # Save generated DLS/RTL reports for reproducibility.
                        source_build=target/'build'/'latest'
                        for artifact in ('fabric_protocol.json','report.json'):
                            if (source_build/artifact).is_file():
                                shutil.copyfile(source_build/artifact,output/(name+'_'+artifact))
            from chipcompiler.concurrent import concurrent_fabric,FabricConfig
            from chipcompiler.fabric_verify import check_fabric_protocol,randomized_fabric_check
            from chipcompiler.export import export_verilog
            from chipcompiler.rtl_check import check_rtl
            from chipcompiler.diagnostics import IssueCollector,EventLog
            for operator in ('builtin','external'):
                with tempfile.TemporaryDirectory(prefix='cc-rtl-') as temp:
                    work=Path(temp)
                    d=concurrent_fabric(FabricConfig(clients=3,width=4,depth=4,operator=operator),
                                        name='fabric_'+operator)
                    d.save(work/(d.name+'.dls'))
                    rtl=work/(d.name+'.v');export_verilog(d,rtl)
                    result={'status':'PASS','protocol':check_fabric_protocol(d,FabricConfig(3,4,4,operator)),
                            'randomized':randomized_fabric_check(d,FabricConfig(3,4,4,operator))}
                    if result['protocol']['status']!='PASS' or result['randomized']['status']!='PASS':
                        result['status']='FAIL'
                    record('dls_fabric_'+operator,result)
                    if selected_rtl=='native' and not (shutil.which('iverilog') and shutil.which('vvp')):
                        record('rtl_fabric_'+operator,{'status':'UNAVAILABLE','reason':'Icarus Verilog (iverilog/vvp) not available on native PATH.'})
                    elif selected_rtl=='wsl' and not (wsl_tools.get('iverilog',{}).get('available') and wsl_tools.get('vvp',{}).get('available')):
                        record('rtl_fabric_'+operator,{'status':'UNAVAILABLE','reason':'wsl.exe not available.'})
                    else:
                        issues=IssueCollector();events=EventLog(work/'events.jsonl')
                        checked=check_rtl(d,rtl,work,issues,events,
                                 run_options={'runner':selected_rtl},vector_count=128)
                        record('rtl_fabric_'+operator,checked)
                        for log in work.glob('*.log'):
                            shutil.copyfile(log,reports/(operator+'_'+log.name))
                        if (work/'rtl_verification.json').exists():
                            shutil.copyfile(work/'rtl_verification.json',output/(operator+'_rtl_verification.json'))
        else:
            for name in ('build_conditional_alu','build_transactional_memory','build_concurrent_fabric',
                         'dls_fabric_builtin','dls_fabric_external','rtl_fabric_builtin','rtl_fabric_external'):
                record(name,{'status':'BLOCKED','reason':'Required Python compiler dependencies missing'})
        if selected_yosys=='native' and not shutil.which('yosys'):
            record('yosys_real_synthesis',{'status':'UNAVAILABLE','reason':'yosys not available on native PATH'})
        elif selected_yosys=='wsl' and not wsl_tools.get('yosys',{}).get('available'):
            record('yosys_real_synthesis',{'status':'UNAVAILABLE','reason':'wsl.exe not installed'})
        elif toolkit['yaml']:
            with tempfile.TemporaryDirectory(prefix='cc-yosys-') as temp:
                target=Path(temp)/'conditional_alu'
                shutil.copytree(ROOT/'examples'/'conditional_alu',target,
                         ignore=shutil.ignore_patterns('build','.chipcompiler','__pycache__'))
                # BuildSession reads execution config, not an ad hoc wrapper.
                if selected_yosys=='wsl':
                    config=target/'chip.yaml'
                    import yaml
                    obj=yaml.safe_load(config.read_text(encoding='utf-8'))
                    obj['tools']={'execution':'wsl'}
                    config.write_text(yaml.safe_dump(obj),encoding='utf-8')
                command=_run([sys.executable,'-m','chipcompiler','build',str(target)],
                         ROOT,reports/'yosys_real_synthesis.log',timeout=600,env=env)
                record('yosys_real_synthesis',command)
                report=target/'build'/'latest'/'report.json'
                if report.exists():shutil.copyfile(report,output/'yosys_build_report.json')
                native=target/'build'/'latest'/'yosys.log'
                if native.exists():shutil.copyfile(native,reports/'yosys_native.log')
        if physical_project is not None:
            project=Path(physical_project).resolve()
            if not (project/'chip.yaml').is_file():
                record('physical_flow',{'status':'FAIL','reason':'No chip.yaml in specified physical project'})
            else:
                # Physical run can be lengthy; copy project, retain its PDK config.
                # A copied project preserves relative source contents but does not
                # alter the original. Absolute PDK paths remain as configured.
                with tempfile.TemporaryDirectory(prefix='cc-physical-') as tmp:
                    target=Path(tmp)/'project'
                    shutil.copytree(project,target,ignore=shutil.ignore_patterns('build','.chipcompiler','__pycache__'))
                    result=_run([sys.executable,'-m','chipcompiler','physical',str(target)],
                         ROOT,reports/'physical_flow.log',timeout=7500,env=env)
                    record('physical_flow',result)
                    latest=target/'build'/'latest'
                    for artifact in ('report.json','physical_evidence.json','config.json'):
                        if (latest/artifact).exists():shutil.copyfile(latest/artifact,output/('physical_'+artifact))
                    for log in latest.glob('*.log'):
                        shutil.copyfile(log,reports/('physical_'+log.name))
        else:
            record('physical_flow',{'status':'NOT_REQUESTED',
                     'reason':'No PDK-backed physical project supplied; cannot establish layout/signoff.'})
        summary['overall']=('FAIL' if any(v['status'] in ('FAIL','TIMEOUT','BLOCKED') for v in status.values())
                            else 'PARTIAL' if any(v['status'] in ('UNAVAILABLE','NOT_REQUESTED','NOT_APPLICABLE') for v in status.values())
                            else 'PASS')
    except Exception as exc:
        summary['overall']='FAIL'
        summary['unhandled_runner_exception']=traceback.format_exc()
        print('VALIDATION RUNNER ERROR:',type(exc).__name__,str(exc),flush=True)
    finally:
        (output/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        (output/'HOW_TO_SHARE.txt').write_text(
            'Chip Compiler automated test package. Send the entire diagnostic ZIP back to ChatGPT.\n'
            'PASS means that exact stage ran and passed. UNAVAILABLE and NOT_REQUESTED do not imply success.\n'
            'The ZIP contains tool paths, OS/Python versions, errors, generated test reports and logs.\n'
            'Do not include personal source files unless deliberately requested.\n',encoding='utf-8')
        z=output.with_suffix('.zip')
        with zipfile.ZipFile(z,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(output.rglob('*')):
                if file.is_file() and (include_source or file.suffix not in ('.py','.c','.cpp','.mcd','.co')):
                    archive.write(file,file.relative_to(output))
        summary['archive']=str(z)
        print('DIAGNOSTIC_ARCHIVE:',z,flush=True)
        print('OVERALL:',summary.get('overall'),flush=True)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description='Run actual Chip Compiler checks and produce a diagnostic ZIP.')
    parser.add_argument('--output',default='validation/ChipCompiler_v0.8.0_diagnostics')
    parser.add_argument('--install-python-deps',action='store_true',help='Explicitly install GUI/test Python requirements into active environment')
    parser.add_argument('--physical-project',type=Path,help='Optional REAL PDK-backed project for physical verification')
    parser.add_argument('--rtl-runner',choices=('auto','native','wsl'),default='auto',help='Auto probes native and WSL tools; never silently substitutes one.')
    args=parser.parse_args(argv)
    result=run_validation(Path(args.output),args.install_python_deps,args.physical_project,args.rtl_runner)
    return 0 if result.get('overall')=='PASS' else 2 if result.get('overall')=='PARTIAL' else 1

if __name__=='__main__':raise SystemExit(main())
