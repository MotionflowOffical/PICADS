"""One-command PICADS v1 feature and workflow test robot.

Real CLI subprocesses; real Qt event-loop user journeys when Qt is installed;
negative/mutation tests, native RTL/synthesis/physical acceptance when installed.
Never runs against or overwrites a user project: all example projects are copied.
The output ZIP contains logs and a machine-readable per-stage disposition.
"""
from __future__ import annotations
import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
import xml.etree.ElementTree as ET

from .dependencies import probe_tools
from .project import atomic_write

ROOT=Path(__file__).resolve().parents[2]
VERSION='0.16.6'


def _invoke(command:list[str],directory:Path,env:dict,log:Path,timeout:int)->dict:
    try:
        with log.open('w',encoding='utf-8') as stream:
            p=subprocess.run(command,cwd=directory,env=env,stdout=stream,
                             stderr=subprocess.STDOUT,timeout=timeout,check=False)
        return {'status':'PASS' if p.returncode==0 else 'FAIL',
                'return_code':p.returncode,'log':log.name,'command':command}
    except subprocess.TimeoutExpired:
        with log.open('a',encoding='utf-8') as stream:stream.write('\nTIMEOUT after '+str(timeout)+' seconds\n')
        return {'status':'FAIL','reason':'TIMEOUT','log':log.name,'command':command}
    except OSError as e:
        log.write_text(str(e),encoding='utf-8')
        return {'status':'FAIL','reason':f'{type(e).__name__}: {e}','log':log.name,'command':command}


def _json_command(args:list[str],cwd:Path,env:dict,log:Path,expect_rc:int=0)->tuple[dict,dict]:
    run=_invoke([sys.executable,'-m','chipcompiler',*args],cwd,env,log,150)
    try:
        payload=json.loads(log.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        payload={}
    run['status']='PASS' if run.get('return_code')==expect_rc else 'FAIL'
    if run['status']=='FAIL':
        run['reason']=f'Expected exit code {expect_rc}, got {run.get("return_code")}'
    return run,payload


def _exercise_cli(tmp:Path,env:dict,logs:Path)->dict:
    """Exercise program entry points; expected failures count as success only if diagnosed."""
    src=ROOT/'examples'/'alu_slice_component'
    target=tmp/'project';shutil.copytree(src,target,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    stages={}
    run,build=_json_command(['compile',str(target)],ROOT,env,logs/'01_cli_compile.log')
    valid=(run['status']=='PASS' and build.get('status') in ('SUCCESS','SUCCESS_WITH_WARNINGS')
           and build.get('stages',{}).get('equivalence',{}).get('status')=='PASS_EXHAUSTIVE'
           and Path(build.get('files',{}).get('verilog','NO_FILE')).is_file())
    stages['compile_real_entrypoint']={**run,'status':'PASS' if valid else 'FAIL',
                                       'equivalence':build.get('stages',{}).get('equivalence',{}).get('status')}
    # Preserve the generated chip artifacts before deliberate-error rebuilds replace 'latest'.
    artifacts=logs/'alu_generated'
    artifacts.mkdir(exist_ok=True)
    for role,source_path in build.get('files',{}).items():
        if role in {'verilog','dls','equivalence','report','events','architecture'}:
            candidate=Path(source_path)
            if candidate.is_file() and candidate.stat().st_size < 20*1024*1024:
                shutil.copyfile(candidate,artifacts/candidate.name)
    for part in ('circuit.py','design.mcd','architecture.co','chip.yaml'):
        shutil.copyfile(target/part,artifacts/part)
    for n,(a,b,op,expected) in enumerate(((15,1,0,16),(0,1,1,15),(13,7,2,5),(13,7,3,10))):
        cmd=['simulate',str(target),'--inputs',json.dumps({'a':a,'b':b,'op':op})]
        check,payload=_json_command(cmd,ROOT,env,logs/f'02_simulate_{n}.log')
        good=check['status']=='PASS' and payload.get('simulated_output')=={'result':expected}
        stages[f'cli_simulation_{n}']={**check,'status':'PASS' if good else 'FAIL','expected':expected,
                                      'observed':payload.get('simulated_output')}
    vectors=[{'a':15,'b':1,'op':0},{'a':0,'b':1,'op':1},{'a':13,'b':7,'op':2}]
    (tmp/'vectors.json').write_text(json.dumps(vectors),encoding='utf-8')
    trace=tmp/'trace.vcd'
    check,payload=_json_command(['trace',str(target),'--vectors',str(tmp/'vectors.json'),
                                 '--output',str(trace)],ROOT,env,logs/'03_cli_trace.log')
    stages['waveform_export']={**check,'status':'PASS' if check['status']=='PASS' and trace.is_file() and
          trace.stat().st_size>100 and '$enddefinitions' in trace.read_text() else 'FAIL'}
    if trace.is_file():
        shutil.copyfile(trace,artifacts/'alu_trace.vcd')
    # A preflight is expected to refuse physical design while disabled.
    check,payload=_json_command(['physical-preflight',str(target)],ROOT,env,logs/'04_cli_preflight.log',expect_rc=2)
    stages['preflight_rejects_disabled_layout']={**check,'status':'PASS' if
                check['status']=='PASS' and payload.get('status')=='BLOCKED' else 'FAIL'}
    source=target/'circuit.py';original=source.read_text(encoding='utf-8')
    source.write_text('def alu_slice(\n',encoding='utf-8')
    check,payload=_json_command(['compile',str(target)],ROOT,env,logs/'05_cli_invalid_source.log',expect_rc=1)
    err=payload.get('issues',[])
    diagnosed=(check['status']=='PASS' and payload.get('status')=='FAILED'
               and payload.get('stages',{}).get('export',{}).get('status')=='BLOCKED'
               and bool(err) and not any(str(i.get('code','')).startswith('INTERNAL.') for i in err))
    stages['detect_malformed_source']={**check,'status':'PASS' if diagnosed else 'FAIL',
                                        'issue_codes':[i.get('code') for i in err]}
    source.write_text(original,encoding='utf-8')
    check,payload=_json_command(['compile',str(target)],ROOT,env,logs/'06_cli_recovered.log')
    stages['recover_after_error']={**check,'status':'PASS' if check['status']=='PASS' and
                    payload.get('status') in ('SUCCESS','SUCCESS_WITH_WARNINGS') else 'FAIL'}
    return stages


def _pytest_result(logs: Path, env: dict, files: list[str], *, label: str,
                   timeout: int = 300) -> dict:
    """Run exact user-facing feature tests and retain per-case JUnit evidence.

    A regression test's assumptions about the user's install must not become
    a false v1 feature failure. Run the independently specified v1 contracts.
    """
    xml_path = logs / (label + '.xml')
    cmd = [sys.executable, '-m', 'pytest', '-q', '-ra',
           f'--junitxml={xml_path}', *files]
    result = _invoke(cmd, ROOT, env, logs / (label + '.log'), timeout)
    if xml_path.is_file():
        try:
            tree = ET.parse(xml_path)
            suites = tree.getroot()
            cases = []
            for case in suites.iter('testcase'):
                failure = case.find('failure')
                error = case.find('error')
                skip = case.find('skipped')
                state = 'FAIL' if failure is not None or error is not None else 'SKIP' if skip is not None else 'PASS'
                reason = next((node for node in (failure, error, skip) if node is not None), None)
                cases.append({'name': case.get('name'), 'class': case.get('classname'),
                              'status': state, 'reason': reason.get('message') if reason is not None else None})
            result['cases'] = cases
            result['case_counts'] = {status: sum(c['status'] == status for c in cases)
                                     for status in ('PASS', 'FAIL', 'SKIP')}
            if not cases:
                result['status'] = 'FAIL'
                result['reason'] = 'pytest did not report any executed test cases'
        except (ET.ParseError, OSError) as exc:
            result['status'] = 'FAIL'
            result['reason'] = f'Cannot parse JUnit report: {exc}'
    elif result['status'] == 'PASS':
        result['status'] = 'FAIL'
        result['reason'] = 'pytest returned success without creating per-test report'
    result['junit_xml'] = xml_path.name
    return result


def _feature_contracts(logs: Path, env: dict) -> dict:
    return _pytest_result(logs, env, ['tests/test_v1_feature_matrix.py'],
                          label='v1_feature_matrix', timeout=240)


def _historical_regressions(logs: Path, env: dict) -> dict:
    """Optional maintenance check only; never included in the default suite."""
    results = {}
    excluded = {'test_v1_feature_matrix.py', 'test_gui_smoke.py',
                'test_gui_workflow.py', 'test_gui_dependency_installer.py'}
    for file in sorted((ROOT / 'tests').glob('test_*.py')):
        if file.name in excluded:
            continue
        results[file.stem] = _pytest_result(logs, env,
            [str(file.relative_to(ROOT))], label='historical_' + file.stem,
            timeout=300)
    return results


def _gui_tests(logs:Path,env:dict)->dict:
    if not __import__('importlib').util.find_spec('PySide6'):
        return {'status':'UNAVAILABLE','reason':'PySide6 not installed. Install with SETUP_GUI_WINDOWS.bat.',
                'tests':['tests/test_gui_smoke.py','tests/test_gui_workflow.py','tests/test_gui_dependency_installer.py']}
    gui_env=dict(env)
    gui_env['QT_QPA_PLATFORM']='offscreen'
    gui_env['PICADS_GUI_EVIDENCE_DIR']=str(logs)
    return _pytest_result(logs, gui_env,
            ['tests/test_gui_smoke.py', 'tests/test_gui_workflow.py',
             'tests/test_gui_dependency_installer.py'],
            label='gui_workflow', timeout=300)


def _native_alu(logs:Path)->dict:
    """Native RTL and Yosys for user-specified ALU source component.

    Both stages use actual PICADS compilation and real external tools only.
    Native tool absence is UNAVAILABLE, never PASS. Temporary copy only.
    """
    from .dependencies import resolve_tool
    from .pipeline import BuildSession
    import yaml
    result={}
    with tempfile.TemporaryDirectory(prefix='picads-native-alu-') as temp:
        project=Path(temp)/'alu'
        shutil.copytree(ROOT/'examples'/'alu_slice_component',project,
                        ignore=shutil.ignore_patterns('build','.chipcompiler'))
        if resolve_tool('iverilog') and resolve_tool('vvp'):
            settings=yaml.safe_load((project/'chip.yaml').read_text(encoding='utf-8'))
            settings['verification']={'external_rtl':True,'rtl_vectors':256}
            (project/'chip.yaml').write_text(yaml.safe_dump(settings,sort_keys=False),encoding='utf-8')
            verified=BuildSession(project,'compile').run()
            native=verified.stages.get('rtl_check',{})
            result['alu_icarus']={'status':'PASS' if native.get('status')=='PASS' else 'FAIL',
                                    'stage':native,'issues':verified.issues}
            for name in ('rtl_verification.json','rtl_verification.log'):
                source=project/'build'/'latest'/name
                if source.is_file():shutil.copyfile(source,logs/('alu_'+name))
        else:result['alu_icarus']={'status':'UNAVAILABLE','reason':'Icarus iverilog and vvp both required'}
        if resolve_tool('yosys'):
            built=BuildSession(project,'build').run()
            stage=built.stages.get('yosys',{})
            result['alu_yosys']={'status':'PASS' if stage.get('status')=='PASS' else 'FAIL',
                                 'stage':stage,'issues':built.issues}
            source=project/'build'/'latest'/'yosys.log'
            if source.is_file():shutil.copyfile(source,logs/'alu_yosys.log')
        else:result['alu_yosys']={'status':'UNAVAILABLE','reason':'Yosys executable not registered'}
    return result


def _native_test(logs:Path,env:dict,pdk:str,pdk_root:str|None,timeout:int)->dict:
    output=logs/'physical_native_acceptance'
    # Never accept a stale native summary from an earlier test run.
    if output.is_dir():
        (output/'summary.json').unlink(missing_ok=True)
    cmd=[sys.executable,'-m','chipcompiler.acceptance','--output',str(output),
         '--pdk',pdk,'--physical-timeout',str(timeout),'--skip-gui']
    if pdk_root:cmd+=['--pdk-root',pdk_root]
    run=_invoke(cmd,ROOT,env,logs/'native_workflow.log',timeout+300)
    summary=output/'summary.json'
    if summary.is_file():
        data=json.loads(summary.read_text(encoding='utf-8'))
        overall=data.get('overall')
        run['status']='FAIL' if overall=='FAIL' else 'PARTIAL' if overall=='PARTIAL' else 'PASS'
        run['native_stages']={k:v['status'] for k,v in data.get('statuses',{}).items()}
        # Preserve extracted reports, not a ZIP embedded inside another ZIP.
        (logs/'physical_native_acceptance.zip').unlink(missing_ok=True)
    else:
        run['status']='FAIL';run['reason']='Native acceptance failed to produce summary.json'
    # The enclosing PICADS report is the ONLY diagnostic ZIP; extracted native
    # evidence remains in its folder, so a nested ZIP is unnecessary.
    (logs/'physical_native_acceptance.zip').unlink(missing_ok=True)
    return run


def run_validation(destination:Path,*,full_regression=False,native=True,gui=True,
                   pdk='sky130A',pdk_root=None,physical_timeout=5400)->dict:
    output=Path(destination).resolve();output.mkdir(parents=True,exist_ok=True)
    # Only this dedicated evidence folder is cleared, preventing stale results
    # from an earlier run from masquerading as this run's evidence.
    logs=output/'evidence'
    if logs.exists():
        if logs.is_dir(): shutil.rmtree(logs)
        else: raise ValueError('Evidence path is not a folder')
    logs.mkdir()
    env=dict(os.environ)
    env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
    # Isolate global tool-registration writes made by automated tests; native
    # subprocesses need real user registrations so they run with original settings.
    summary={'schema':1,'product':'PICADS','version':VERSION,
             'run_utc':datetime.now(timezone.utc).isoformat(),
             'mode':'v1.0 feature acceptance and real entrypoint/user journey testing',
             'manufacturing_qualified':False,'statuses':{},
             'explanation':'Logical and GUI feature tests are not physical manufacturing signoff.'}
    statuses=summary['statuses']
    with tempfile.TemporaryDirectory(prefix='picads-feature-qa-') as tmp:
        isolated=dict(env);isolated['PICADS_SETTINGS_DIR']=str(Path(tmp)/'settings')
        try:
            statuses['cli_user_journeys']=_exercise_cli(Path(tmp),isolated,logs)
        except BaseException as exc:
            (logs/'cli_exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
            statuses['cli_user_journeys']={'fatal':{'status':'FAIL','reason':str(exc)}}
        try:
            statuses['v1_feature_contracts']=_feature_contracts(logs,isolated)
        except BaseException as exc:
            (logs/'pytest_exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
            statuses['v1_feature_contracts']={'status':'FAIL','reason':str(exc)}
        if full_regression:
            try:
                statuses['optional_historical_regressions']=_historical_regressions(logs,isolated)
            except BaseException as exc:
                (logs/'historical_exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
                statuses['optional_historical_regressions']={'status':'FAIL','reason':str(exc)}
        if gui:
            try:statuses['gui_robot']=_gui_tests(logs,isolated)
            except BaseException as exc:statuses['gui_robot']={'status':'FAIL','reason':repr(exc)}
        else:statuses['gui_robot']={'status':'NOT_REQUESTED'}
    try:
        statuses['installed_tools']=probe_tools()
        (logs/'installed_tools.json').write_text(json.dumps(statuses['installed_tools'],indent=2),encoding='utf-8')
    except Exception as exc:
        statuses['installed_tools']={'fatal':{'status':'FAIL','reason':str(exc)}}
    if native:
        try:statuses['native_alu']=_native_alu(logs)
        except BaseException as exc:
            (logs/'alu_native_exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
            statuses['native_alu']={'fatal':{'status':'FAIL','reason':repr(exc)}}
        try:statuses['native_toolchain']=_native_test(logs,env,pdk,pdk_root,physical_timeout)
        except BaseException as exc:
            (logs/'native_exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
            statuses['native_toolchain']={'status':'FAIL','reason':repr(exc)}
    else:
        statuses['native_alu']={'status':'NOT_REQUESTED'}
        statuses['native_toolchain']={'status':'NOT_REQUESTED'}
    leaf=[]
    def walk(node):
        if isinstance(node,dict):
            if 'status' in node:leaf.append(node['status'])
            else:
                for value in node.values():walk(value)
    for name in ('cli_user_journeys','v1_feature_contracts','gui_robot','native_alu','native_toolchain'):
        walk(statuses[name])
    if full_regression:
        walk(statuses['optional_historical_regressions'])
    # All default stages are user-facing v1.0 contracts. Previous feature
    # history remains available exclusively through --full-regression.
    # In particular a normal run does not call _historical_regressions().
    summary['counts']={x:leaf.count(x) for x in sorted(set(leaf))}
    cases=statuses.get('v1_feature_contracts',{}).get('cases',[])
    gui_cases=statuses.get('gui_robot',{}).get('cases',[])
    native_acceptance=statuses.get('native_toolchain',{}).get('native_stages',{})
    matrix={
      'scope':'v1.0 essential functions; no historical regression cases in default run',
      'contract_cases':cases, 'gui_cases':gui_cases,
      'native_alu':statuses.get('native_alu'),
      'native_physical_stages':native_acceptance,
      'guarantees':{
        'independent_dls_oracle':'exhaustive 1024 combinations for bundled ALU',
        'rtl':'independent native Icarus only when installed',
        'synthesis':'native Yosys only when installed',
        'layout':'real PDK-backed LibreLane attempt, otherwise PARTIAL',
        'signoff':'not automatically guaranteed by logic tests',
      },
    }
    atomic_write(logs/'v1_capability_matrix.json', json.dumps(matrix,indent=2,default=str))
    summary['overall']='FAIL' if 'FAIL' in leaf else 'PARTIAL' if any(x!='PASS' for x in leaf) else 'PASS_EXECUTED_CHECKS'
    atomic_write(output/'summary.json',json.dumps(summary,indent=2,default=str))
    atomic_write(output/'HOW_TO_REPORT.txt',
        'Upload ONLY the enclosing diagnostics ZIP (not the unpacked folder).\n'
        'It contains the summary, all test logs, generated ALU RTL/DLS/VCD,\n'
        'the external-tool reports and screenshots when available.\n'
        'PASS reflects only the checks executed.\n'
        'If native tools are unavailable, overall status is PARTIAL.\n'
        'This report does not qualify fabrication masks.\n')
    archive=_package_report(output)
    summary['zip']=str(archive)
    return summary


def _package_report(output:Path)->Path:
    """Build one self-verifying diagnostic archive, including ALL evidence files.

    Contents are a stable flat report root with subfolders, no nested ZIPs.
    The manifest lists SHA-256 and sizes for every payload; the ZIP is checked
    after writing.  A Python/tool failure is still represented in the report.
    """
    output=Path(output).resolve()
    files=[p for p in sorted(output.rglob('*')) if p.is_file() and p.name!='FILE_MANIFEST.json']
    manifest={'schema':1,'product':'PICADS','version':VERSION,'file_count':len(files),'files':[]}
    for entry in files:
        manifest['files'].append({'path':entry.relative_to(output).as_posix(),
                     'size_bytes':entry.stat().st_size,
                     'sha256':hashlib.sha256(entry.read_bytes()).hexdigest()})
    (output/'FILE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    archive=Path(str(output)+'.zip')
    temp_archive=Path(str(archive)+'.tmp')
    try:
        with zipfile.ZipFile(temp_archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for path in sorted(output.rglob('*')):
                if path.is_file():z.write(path,path.relative_to(output))
        with zipfile.ZipFile(temp_archive) as z:
            bad=z.testzip()
            if bad:raise RuntimeError(f'Diagnostic ZIP integrity failure: {bad}')
            members={info.filename for info in z.infolist()}
            expected={p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
            if members!=expected:raise RuntimeError('Diagnostic ZIP missing report files')
        temp_archive.replace(archive)
    finally:
        temp_archive.unlink(missing_ok=True)
    return archive


def _emergency_report(destination:Path,exc:BaseException)->Path:
    """Still create a single uploadable ZIP if the robot unexpectedly crashes."""
    output=Path(destination).resolve()
    output.mkdir(parents=True,exist_ok=True)
    (output/'FATAL_ERROR.txt').write_text(traceback.format_exc(),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps({'schema':1,'product':'PICADS',
       'version':VERSION,'overall':'FAIL','reason':str(exc),'statuses':{'robot':{'status':'FAIL'}}},indent=2),encoding='utf-8')
    (output/'HOW_TO_REPORT.txt').write_text('Automatic tester crashed. Upload this ZIP anyway.\n',encoding='utf-8')
    return _package_report(output)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Automated PICADS v1 feature and physical acceptance testing')
    parser.add_argument('--output',default='validation/PICADS_v0.16.6_automated_diagnostics')
    parser.add_argument('--full-regression',action='store_true',help='Optional developer maintenance only: historical regression files (NOT default feature verification)')
    parser.add_argument('--skip-native',action='store_true',help='Skip real Icarus/Yosys/LibreLane native tool check')
    parser.add_argument('--skip-gui',action='store_true',help='Skip Qt automated user journeys')
    parser.add_argument('--pdk',default='sky130A')
    parser.add_argument('--pdk-root')
    parser.add_argument('--physical-timeout',type=int,default=5400)
    ns=parser.parse_args(argv)
    try:
        data=run_validation(Path(ns.output),full_regression=ns.full_regression,
                native=not ns.skip_native,gui=not ns.skip_gui,pdk=ns.pdk,
                pdk_root=ns.pdk_root,physical_timeout=ns.physical_timeout)
    except Exception as exc:
        try: archive=_emergency_report(Path(ns.output),exc)
        except Exception as pack_exc:
            print(f'Diagnostic packaging failed: {pack_exc}',file=sys.stderr)
            archive=None
        print(json.dumps({'status':'FAIL','reason':str(exc),'zip':str(archive) if archive else None}),file=sys.stderr)
        return 1
    print(json.dumps({'overall':data['overall'],'zip':data['zip'],'counts':data['counts']},indent=2))
    return 1 if data['overall']=='FAIL' else 2 if data['overall']=='PARTIAL' else 0

if __name__=='__main__':raise SystemExit(main())
