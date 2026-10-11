"""Explicit wrappers for optional external tools. No silent fake success."""
from __future__ import annotations
import subprocess,shutil,os,json,time,threading,collections,re
from pathlib import Path
from .diagnostics import IssueCollector,EventLog
from .project import atomic_write

def probe()->dict[str,dict]:
    return {name:{'available':bool(shutil.which(name)),'path':shutil.which(name)}
            for name in ('yosys','iverilog','vvp','librelane','klayout','openroad','magic','netgen','wsl.exe','gcc','g++')}

def run_external(argv:list[str],cwd:Path,logs:Path,issues:IssueCollector,events:EventLog,
                 stage:str,timeout:int=600,runner:str='native',wsl_distribution:str|None=None)->dict:
    assert argv
    requested=list(argv)
    if runner=='wsl':
        executable=shutil.which('wsl.exe') or shutil.which('wsl')
        if executable:
            argv=[executable]+(['--distribution',wsl_distribution] if wsl_distribution else [])+[
                '--cd',str(Path(cwd).resolve()),'--exec',*argv]
        else:argv=['wsl.exe',*argv]
    elif runner=='native':
        executable=shutil.which(argv[0])
    else:
        i=issues.add('TOOL.RUNNER_INVALID','ERROR','CONFIG',stage,
            f'Unknown external execution backend {runner!r}.',remedy='Use native or wsl runner.')
        return {'status':'FAIL','issue_id':i.issue_id}
    if not executable:
        issue=issues.add('TOOL.MISSING','ERROR','DEPENDENCY',stage,
                         f'Required external tool runner for {requested[0]!r} is unavailable ({runner}).',
                         cause='EDA dependency or WSL executable is missing from the selected execution environment.',
                         remedy='Install the tool in the selected environment, or set tools.execution appropriately; run doctor.',
                         evidence={'argv':argv,'runner':runner,'requested':requested,'PATH':os.environ.get('PATH','')})
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
                                  text=True,encoding='utf-8',errors='replace',bufsize=1)
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
    except OSError as e:
        i=issues.add('TOOL.LAUNCH_FAILED','ERROR','TOOL',stage,str(e),
                     cause='OS was unable to launch the external executable.',
                     remedy='Check platform compatibility, executable permissions and paths.')
        events.emit(stage,'launch_failed',issue_id=i.issue_id)
        return {'status':'FAIL','issue_id':i.issue_id}

def write_librelane_config(design_name:str,clock_port:str|None,clock_period:float|None,path:Path):
    config={'DESIGN_NAME':design_name,'VERILOG_FILES':['dir::'+design_name+'.v']}
    if clock_port and clock_period:
        config['CLOCK_PORT']=clock_port;config['CLOCK_PERIOD']=clock_period
    atomic_write(path,json.dumps(config,indent=2))
    return config
