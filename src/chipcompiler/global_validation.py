"""Quick reproducible system validation of v0.13 global operator and memory sharing.

Executes in isolated temp folders. Captures actual tool outcomes: missing
external tools are UNAVAILABLE, never fabricated PASS results.
"""
from __future__ import annotations
import argparse,datetime,json,os,platform,shutil,sys,tempfile,traceback,zipfile
from pathlib import Path
from .system_validation import ROOT,_run
from .dependencies import resolve_tool,probe_tools
from .global_sharing import compile_global_source_processes,check_global_source_processes
from .project import open_project
from .pipeline import BuildSession
from .export import export_verilog
from .diagnostics import IssueCollector,EventLog
from .rtl_check import check_rtl
from .formal import prepare_global_shared_formal


def run(output:Path,rtl_runner='native')->dict:
    output=Path(output).expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True)
    logs=output/'logs';logs.mkdir(exist_ok=True)
    summary={'version':'0.14.0','run_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'platform':platform.platform(),'python':sys.version.split()[0],
             'scope':'Experimental global integer/comparison and shared-memory compilation, DLS simulation, optional real RTL and bounded formal safety.',
             'statuses':{},'overall':'UNKNOWN'}
    status=summary['statuses']
    def record(label,entry):
        status[label]=entry
        print(f'[{label}] {entry["status"]}',flush=True)
    try:
        original=ROOT/'examples'/'global_shared_processes'
        with tempfile.TemporaryDirectory(prefix='picads-global-validation-') as tmp:
            target=Path(tmp)/'hardware'
            shutil.copytree(original,target,ignore=shutil.ignore_patterns('build','__pycache__'))
            build=BuildSession(target).run()
            record('project_build',{'status':'PASS' if build.status in ('SUCCESS','SUCCESS_WITH_WARNINGS') else 'FAIL',
                                     'pipeline_status':build.status,'stages':build.stages})
            if build.status not in ('SUCCESS','SUCCESS_WITH_WARNINGS'):
                shutil.copyfile(target/'build'/'latest'/'report.json',output/'failed_build_report.json')
                raise ValueError('The bundled global source example failed to compile.')
            shutil.copyfile(target/'build'/'latest'/'report.json',output/'build_report.json')
            shutil.copyfile(target/'build'/'latest'/'global_schedule.json',output/'global_schedule.json')
            from .project import load_yaml
            issues=IssueCollector();project=open_project(target,issues)
            d=compile_global_source_processes(project.source,project.mcd['concurrent_clients'],project.co,
                         name='PICADSGlobalValidation',issues=issues)
            sampled=check_global_source_processes(project.source,d,issues,rounds=64)
            record('dls_global_scoreboard',sampled)
            (output/'dls_global_scoreboard.json').write_text(json.dumps(sampled,indent=2),encoding='utf-8')
            if sampled['status']!='PASS':raise ValueError('Sampled global scoreboard mismatch')
            from .rtl_check import make_source_process_vectors,make_testbench
            vectors=make_source_process_vectors(d,128)
            bench=make_testbench(d,vectors)
            (output/'rtl_testbench.v').write_text(bench,encoding='utf-8')
            record('rtl_collateral',{'status':'PASS','vectors':len(vectors),'meaning':'Testbench generated; no external RTL execution yet.'})
            rtl=Path(tmp)/(d.name+'.v');export_verilog(d,rtl)
            if rtl_runner=='native' and not all(resolve_tool(x) for x in ('iverilog','vvp')):
                record('real_icarus_rtl',{'status':'UNAVAILABLE','reason':'Icarus and/or vvp not registered or found on PATH'})
            else:
                checkout=Path(tmp)/'rtl';checkout.mkdir()
                rtl_target=checkout/rtl.name;shutil.copyfile(rtl,rtl_target)
                evidence=check_rtl(d,rtl_target,checkout,issues,EventLog(checkout/'events.jsonl'),
                      run_options={'runner':rtl_runner},vector_count=128)
                record('real_icarus_rtl',evidence)
                for path in checkout.glob('*.log'):
                    shutil.copyfile(path,logs/('rtl_'+path.name))
                if (checkout/'rtl_verification.json').exists():
                    shutil.copyfile(checkout/'rtl_verification.json',output/'rtl_verification.json')
            formal_dir=output/'formal_safety'
            generated=prepare_global_shared_formal(d,formal_dir,depth=20)
            record('formal_collateral',{'status':'NOT_APPLICABLE','generated':generated,
                      'reason':'Generation cannot be counted as proof.'})
            if all(resolve_tool(x) for x in ('sby','yosys','z3')):
                checked=_run(['sby','-f','safety.sby'],formal_dir,logs/'sby_safety.log',timeout=600)
                record('real_formal_safety_bmc',checked)
            else:
                record('real_formal_safety_bmc',{'status':'UNAVAILABLE',
                    'missing_tools':[x for x in ('sby','yosys','z3') if not resolve_tool(x)]})
            # Additional v0.13 automatic operator and shared-memory modes.
            # Each project is independently rebuilt, verified, exported and
            # optionally tested by the user's registered native RTL solver.
            for name in ('global_auto_operators','global_shared_memory'):
                sample=ROOT/'examples'/name
                work=Path(tmp)/name
                shutil.copytree(sample,work,ignore=shutil.ignore_patterns('build','__pycache__'))
                compiled=BuildSession(work).run()
                record('build_'+name,{'status':'PASS' if compiled.status in ('SUCCESS','SUCCESS_WITH_WARNINGS') else 'FAIL',
                    'pipeline_status':compiled.status,'stages':compiled.stages})
                if compiled.status not in ('SUCCESS','SUCCESS_WITH_WARNINGS'):
                    shutil.copyfile(work/'build'/'latest'/'report.json',output/(name+'_failure.json'))
                    raise ValueError(name+' build failed')
                validation_issues=IssueCollector()
                loaded=open_project(work,validation_issues)
                circuit=compile_global_source_processes(loaded.source,loaded.mcd['concurrent_clients'],
                          loaded.co,name='PICADS_'+name,issues=validation_issues)
                result=check_global_source_processes(loaded.source,circuit,validation_issues,rounds=16)
                record('dls_'+name,result)
                (output/(name+'_scoreboard.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
                if result['status']!='PASS':raise ValueError(name+' DLS mismatch')
                props=prepare_global_shared_formal(circuit,output/(name+'_formal_safety'),depth=18)
                record('formal_'+name+'_generated',{'status':'NOT_APPLICABLE','generated':props,
                    'reason':'Only on-machine solver success may count as formal verification.'})
                if all(resolve_tool(x) for x in ('sby','yosys','z3')):
                    formal_check=_run(['sby','-f','safety.sby'],output/(name+'_formal_safety'),
                          logs/(name+'_sby.log'),timeout=600)
                    record('formal_'+name+'_executed',formal_check)
                else:
                    record('formal_'+name+'_executed',{'status':'UNAVAILABLE','missing_tools':
                        [x for x in ('sby','yosys','z3') if not resolve_tool(x)]})
                rtl_file=Path(tmp)/(circuit.name+'.v');export_verilog(circuit,rtl_file)
                if not all(resolve_tool(x) for x in ('iverilog','vvp')):
                    record('rtl_'+name,{'status':'UNAVAILABLE','reason':'Icarus/vvp not installed or registered'})
                else:
                    folder=Path(tmp)/(name+'_rtl');folder.mkdir()
                    from .rtl_check import check_rtl
                    rtl_result=check_rtl(circuit,rtl_file,folder,validation_issues,
                         EventLog(folder/'events.jsonl'),run_options={'runner':'native'},vector_count=128)
                    record('rtl_'+name,rtl_result)
                    for logfile in folder.glob('*.log'):
                        shutil.copyfile(logfile,logs/(name+'_'+logfile.name))
    except Exception as exc:
        summary['runner_error']=traceback.format_exc()
        record('runner_exception',{'status':'FAIL','reason':f'{type(exc).__name__}: {exc}'})
    finally:
        summary['registered_dependencies']=probe_tools()
        summary['overall']=('FAIL' if any(x['status'] in ('FAIL','TIMEOUT','BLOCKED') for x in status.values()) else
                            'PARTIAL' if any(x['status'] in ('UNAVAILABLE','NOT_APPLICABLE') for x in status.values()) else 'PASS')
        (output/'summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
        (output/'README.txt').write_text('PICADS v0.13 global scheduler diagnostic ZIP. Share this file in the chat.\n'
             'External RTL and formal statuses must be PASS, not UNAVAILABLE, to claim native execution.\n'
             'No physical signoff, PDK timing or mask manufacturing is tested.\n',encoding='utf-8')
        archive=output.with_name(output.name+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for file in sorted(output.rglob('*')):
                if file.is_file():z.write(file,file.relative_to(output))
        print('DIAGNOSTIC_ARCHIVE',archive,flush=True)
        print('OVERALL',summary['overall'],flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description='Run focused PICADS global scheduler validation.')
    parser.add_argument('--output',default='validation/PICADS_v0.14.0_global_diagnostics')
    parser.add_argument('--rtl-runner',choices=['native','wsl'],default='native')
    args=parser.parse_args()
    summary=run(Path(args.output),args.rtl_runner)
    return 0 if summary['overall']=='PASS' else 2 if summary['overall']=='PARTIAL' else 1


if __name__=='__main__':raise SystemExit(main())
