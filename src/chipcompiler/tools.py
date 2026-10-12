"""Explicit wrappers for optional external tools. No silent fake success."""
from __future__ import annotations
import subprocess,shutil,os,json,time,threading,collections,re
from pathlib import Path
from .diagnostics import IssueCollector,EventLog
from .project import atomic_write
from .dependencies import resolve_tool, probe_tools, TOOLS, dependency_environment, tool_status, DependencyConfigurationError

def probe()->dict[str,dict]:
    return probe_tools()

def run_external(argv:list[str],cwd:Path,logs:Path,issues:IssueCollector,events:EventLog,
                 stage:str,timeout:int=600,runner:str='native',wsl_distribution:str|None=None)->dict:
    assert argv
    requested=list(argv)
    if runner=='wsl':
        executable=resolve_tool('wsl.exe')
        if executable:
            argv=[executable]+(['--distribution',wsl_distribution] if wsl_distribution else [])+[
                '--cd',str(Path(cwd).resolve()),'--exec',*argv]
        else:argv=['wsl.exe',*argv]
    elif runner=='native':
        executable=resolve_tool(argv[0]) if argv[0] in TOOLS else shutil.which(argv[0])
        if executable:
            argv=[executable,*argv[1:]]
    else:
        i=issues.add('TOOL.RUNNER_INVALID','ERROR','CONFIG',stage,
            f'Unknown external execution backend {runner!r}.',remedy='Use native or wsl runner.')
        return {'status':'FAIL','issue_id':i.issue_id}
    if not executable:
        selected=tool_status(requested[0]) if runner=='native' and requested[0] in TOOLS else None
        selected_info=(f" Registered location: {selected['selection']}. {selected['error']}" if selected and selected['source']=='registered' else '')
        issue=issues.add('TOOL.MISSING','ERROR','DEPENDENCY',stage,
                         f'Required external tool runner for {requested[0]!r} is unavailable ({runner}).{selected_info}',
                         cause='EDA dependency or WSL executable is missing from the selected execution environment.',
                         remedy='Open Settings > External Dependencies; choose the correct App/Folder or clear the invalid selection. For WSL, configure tools.execution and WSL separately.',
                         evidence={'argv':argv,'runner':runner,'requested':requested,'PATH':os.environ.get('PATH',''),'registered_selection':selected})
        events.emit(stage,'missing_dependency',issue_id=issue.issue_id,executable=argv[0])
        return {'status':'UNAVAILABLE','argv':argv,'issue_id':issue.issue_id}
    started=time.monotonic()
    events.emit(stage,'start',argv=argv,requested_argv=requested,runner=runner,cwd=str(cwd),timeout=timeout)
    logpath=Path(logs)/(stage+'.log')
    logpath.parent.mkdir(parents=True,exist_ok=True)
    stdout_tail=collections.deque(maxlen=100)
    stderr_tail=collections.deque(maxlen=100)
    file_lock=threading.Lock()
    try:
        with logpath.open('w',encoding='utf-8',errors='replace') as log:
            log.write(f'$ {" ".join(argv)}\n\n--- LIVE TOOL OUTPUT ---\n')
            log.flush()
            proc=subprocess.Popen(argv,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                  text=True,encoding='utf-8',errors='replace',bufsize=1,
                                  env=dependency_environment() if runner=='native' else None)
            def consume(stream,label,tail):
                try:
                    for line in stream:
                        with file_lock:
                            log.write(f'[{label}] {line}');log.flush()
                        tail.append(line)
                        if re.search(r'(?i)(error:|\[error\]|fatal:|warning:|\[warn\])',line):
                            events.emit(stage,'tool_line',stream=label,
                                        severity='ERROR' if re.search(r'(?i)(error:|\[error\]|fatal:)',line) else 'WARNING',
                                        line=line[-1200:].rstrip('\r\n'))
                except Exception as exc:
                    events.emit(stage,'stream_reader_failure',stream=label,error=repr(exc))
                finally:
                    stream.close()
            threads=[threading.Thread(target=consume,args=(proc.stdout,'STDOUT',stdout_tail),daemon=True),
                     threading.Thread(target=consume,args=(proc.stderr,'STDERR',stderr_tail),daemon=True)]
            for th in threads:th.start()
            timed_out=False
            try:proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                proc.kill();proc.wait()
            for th in threads:th.join(timeout=5)
            with file_lock:
                log.write(f'\nReturn code: {proc.returncode}\nTimeout: {timed_out}\n')
                log.flush()
        result={'status':'TIMEOUT' if timed_out else 'PASS' if proc.returncode==0 else 'FAIL',
                'returncode':proc.returncode,'elapsed_seconds':round(time.monotonic()-started,3),
                'argv':argv,'log':str(logpath),
                'stdout_tail':''.join(stdout_tail)[-2500:], 'stderr_tail':''.join(stderr_tail)[-2500:]}
        if timed_out:
            i=issues.add('TOOL.TIMEOUT','ERROR','TOOL',stage,f'{argv[0]} exceeded {timeout}s timeout.',
                         cause='Tool did not complete within configured limit.',
                         remedy='Inspect live captured log and process resource usage before changing timeout.',
                         evidence=result)
            result['issue_id']=i.issue_id
        elif proc.returncode:
            i=issues.add('TOOL.EXIT_NONZERO','ERROR','TOOL',stage,
                         f'{argv[0]} exited with code {proc.returncode}.',
                         cause='External tool rejected input or failed; inspect its native stderr and full log.',
                         remedy='Start with this tool log; identify the first native error before changing source or PDK.',
                         evidence=result)
            result['issue_id']=i.issue_id
        events.emit(stage,'finish',**result)
        return result
    except DependencyConfigurationError as e:
        i=issues.add('TOOL.ENVIRONMENT_INVALID','ERROR','DEPENDENCY',stage,str(e),
                     cause='The selected portable Windows EDA bundle could not activate its required child-process environment.',
                     remedy='Open Settings and check the registered installation, environment.bat and bundled files; reinstall the affected optional package if necessary.')
        events.emit(stage,'environment_invalid',issue_id=i.issue_id)
        return {'status':'UNAVAILABLE','issue_id':i.issue_id}
    except OSError as e:
        i=issues.add('TOOL.LAUNCH_FAILED','ERROR','TOOL',stage,str(e),
                     cause='OS was unable to launch the external executable.',
                     remedy='Check platform compatibility, executable permissions and paths.')
        events.emit(stage,'launch_failed',issue_id=i.issue_id)
        return {'status':'FAIL','issue_id':i.issue_id}

def write_librelane_config(design_name:str,clock_port:str|None,clock_period:float|None,path:Path,
                           extra:dict|None=None):
    """Write a real LibreLane 2 JSON config using one generated Verilog file.

    Additional constraints must already be validated by physical_flow; fail if
    they try to override the top module or selected RTL file.
    """
    config={'DESIGN_NAME':design_name,'VERILOG_FILES':['dir::'+design_name+'.v']}
    if clock_port and clock_period:
        config['CLOCK_PORT']=clock_port;config['CLOCK_PERIOD']=clock_period
    if extra:
        if not isinstance(extra,dict):raise ValueError('LibreLane extra settings must be a mapping')
        immutable={'DESIGN_NAME','VERILOG_FILES'}
        if set(extra) & immutable:
            raise ValueError('LibreLane extras cannot override RTL identity')
        config.update(extra)
    atomic_write(path,json.dumps(config,indent=2))
    return config
