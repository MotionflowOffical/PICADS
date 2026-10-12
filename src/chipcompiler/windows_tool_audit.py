"""Read-only Windows dependency audit; one ZIP containing launch evidence.

No installations, PATH modification, privilege escalation, or physical flow
execution occur. Designed for users to upload a single diagnostic file.
"""
from __future__ import annotations

import argparse
import ctypes
from contextlib import contextmanager
import json
import os
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .dependencies import TOOLS, tool_status, dependency_environment, DependencyConfigurationError
from .windows_installer import dependency_root, install_catalog

# Executables requiring GUI sessions or unusual subcommands should be checked
# only by path here. The full automatic validator exercises their workflows.
_VERSION_ARGS = {
    'yosys': ['-V'], 'iverilog': ['-V'], 'vvp': ['-V'],
    'verilator': ['--version'], 'gcc': ['--version'],
    'g++': ['--version'], 'z3': ['--version'],
    'openroad': ['-version'], 'magic': ['--version'],
    'netgen': ['-version'], 'klayout': ['-v'],
    'kicad-cli': ['version'],
}


_WINDOWS_LOADER_ERRORS = {
    0xC0000135: ('MISSING_RUNTIME_DLL', 'A required runtime DLL could not be found. '
                  'Check the tool-specific runtime PATH, not just the executable path.'),
    0xC0000139: ('DLL_ENTRY_POINT_NOT_FOUND', 'A loaded DLL is incompatible with this executable. '
                  'A different toolchain DLL may have been selected from PATH.'),
    0xC0000142: ('DLL_INITIALIZATION_FAILED', 'A required DLL was found but failed to initialize.'),
    0xC000007B: ('INVALID_IMAGE_FORMAT', 'The program loaded an incompatible 32/64-bit DLL or binary.'),
}


@contextmanager
def _no_windows_loader_dialogs():
    """Make the audit non-interactive even when the Windows DLL loader fails.

    SetErrorMode applies to the current process and is inherited by children.
    This is limited to a synchronous CLI audit, never the GUI's launch thread.
    Restore the original setting immediately after the probe.
    """
    if sys.platform != 'win32':
        yield
        return
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetErrorMode.argtypes = [ctypes.c_uint]
        kernel32.SetErrorMode.restype = ctypes.c_uint
        old = kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except (AttributeError, OSError):
        yield
        return
    try:
        yield
    finally:
        kernel32.SetErrorMode(old)


def _version_probe(tool: str, path: str, *, runner=None, env=None) -> dict:
    runner = runner or subprocess.run
    try:
        with _no_windows_loader_dialogs():
            proc = runner([path, *_VERSION_ARGS[tool]], capture_output=True,
                          text=True, errors='replace', timeout=20,
                          check=False, env=env)
        output = ((proc.stdout or '')+'\n'+(proc.stderr or '')).strip()
        result = {'status': 'PASS' if proc.returncode == 0 else 'FAILED',
                  'exit_code': proc.returncode, 'output': output[-3000:]}
        code = int(proc.returncode or 0) & 0xFFFFFFFF
        if code in _WINDOWS_LOADER_ERRORS:
            kind, diagnosis = _WINDOWS_LOADER_ERRORS[code]
            result.update({'windows_loader_error': f'0x{code:08X}',
                           'failure_kind': kind, 'diagnosis': diagnosis})
        return result
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status':'FAILED','error':f'{type(exc).__name__}: {exc}'}


def audit(*, runner=None) -> dict:
    root=dependency_root()
    packages=install_catalog()
    errors=[]
    tools={}
    # Every tool needs an isolated Windows DLL environment. A global union
    # of KiCad/OSS/MSYS2/KLayout PATH directories causes loader collisions.
    for name in TOOLS:
        try:
            item=tool_status(name)
            status={'registered_or_found':item['available'],
                    'source':item['source'], 'path':item.get('path'),
                    'error':item.get('error')}
            if item['available'] and name in _VERSION_ARGS:
                try:
                    environment=dependency_environment(tool=name)
                except DependencyConfigurationError as exc:
                    status['startup_probe']={
                        'status':'ENVIRONMENT_ERROR',
                        'error':str(exc),
                        'remedy':'Check PICADS Windows CAD environment activation. '
                                 'Do not reinstall large archives until repaired.'}
                    errors.append(f'{name}: {exc}')
                else:
                    status['startup_probe']=_version_probe(
                        name,item['path'],runner=runner,env=environment)
                    path_key=next((k for k in environment if k.upper()=='PATH'),'PATH')
                    separator=';' if sys.platform=='win32' else os.pathsep
                    status['startup_probe']['runtime_path_head']=[
                        v for v in environment.get(path_key,'').split(separator)[:6] if v]
            elif item['available']:
                status['startup_probe']={'status':'NOT_RUN',
                                        'reason':'GUI or no safe version option'}
            else:
                status['startup_probe']={'status':'UNAVAILABLE'}
            tools[name]=status
        except Exception as exc:
            tools[name]={'registered_or_found':False, 'status':'ERROR',
                         'error':f'{type(exc).__name__}: {exc}'}
    marker = root / 'librelane' / 'backend_smoke_passed.txt'
    backend={
        'status': 'SMOKE_MARKER_PRESENT' if marker.is_file() else 'NOT_VERIFIED',
        'marker': str(marker) if marker.is_file() else None,
        'explanation': 'OpenROAD, Magic, Netgen belong to the optional LibreLane container/WSL backend; no standalone Windows EXEs are implied by setup.',
    }
    physical = {n: {'method':'LibreLane WSL2/Docker',
                     'availability':'CONFIGURED_BACKEND_NOT_INDEPENDENTLY_VERIFIED' if marker.is_file() else 'NOT_VERIFIED'}
                for n in ('openroad','magic','netgen')}
    failed=[name for name,state in tools.items() if state.get('startup_probe',{}).get('status') in ('FAILED','ENVIRONMENT_ERROR')]
    report = {'schema':1,'generated_utc':datetime.now(timezone.utc).isoformat(),
              'application':'PICADS', 'release':'0.16.4', 'platform':platform.platform(),
              'python':sys.version.split()[0], 'dependency_root':str(root),
              'packages':[{'name':x['id'], 'mode':x['mode'], 'installed':x['installed'],
                           'can_install':x['can_install']} for x in packages],
              'tools':tools, 'backend':backend, 'physical_backend_tools':physical,
              'overall':'TOOL_STARTUP_FAILURES' if failed else 'AVAILABLE_TOOL_PROBES_COMPLETE',
              'failed_startups':failed, 'errors':errors}
    return report


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description='PICADS installed Windows tools audit (read-only)')
    parser.add_argument('--output', default='validation/PICADS_v0.16.4_tools_diagnostics.zip')
    args=parser.parse_args(argv)
    result=audit()
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(result,indent=2)+'\n'
    readme=('PICADS v0.16.4 dependency audit\n'
            'Read tools.json for registered executable paths and startup results.\n'
            'NOT_VERIFIED does not mean a tool is broken.\n'
            'A LibreLane backend marker is not manufacturing signoff.\n')
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('tools.json',payload)
        archive.writestr('README.txt',readme)
    print('Dependency audit created:', path)
    for name in ('yosys','z3','iverilog','vvp','verilator','pcbnew','gcc','g++','openroad','magic','netgen'):
        state=result['tools'][name]
        probe=state.get('startup_probe',{})
        print(name+':', 'FOUND' if state.get('registered_or_found') else 'UNAVAILABLE',
              probe.get('status',''), probe.get('failure_kind',''))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
