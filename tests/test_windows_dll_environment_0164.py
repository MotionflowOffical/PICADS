"""Regression tests based on real Windows audit 2026-10-12.

Windows OSS CAD Suite can fail with 0xC0000135 (DLL not found) or
0xC0000139 (wrong DLL entrypoint) when unrelated KiCad/MSYS2 paths have
priority, or when environment.bat is invoked incorrectly through cmd /c.
These tests intentionally do not download executables or load platform DLLs.
"""
import os
from pathlib import Path
from types import SimpleNamespace
from chipcompiler import dependencies as deps
from chipcompiler import windows_tool_audit as audit
from chipcompiler import system_validation


def test_oss_activation_handles_windows_path_with_spaces(tmp_path, monkeypatch):
    directory = tmp_path / 'PICADS Build' / 'oss-cad-suite'
    directory.mkdir(parents=True)
    activation = directory / 'environment.bat'
    activation.write_bytes(b'@echo off\r\nset "PATH=%~dp0bin;%PATH%"\r\n')
    captured = {}
    def fake_run(command, **kwargs):
        captured['command'] = command
        captured['script'] = next(tmp_path.parent.glob('nonexistent')) if False else None
        # Locate the temporary .cmd file created by the environment loader.
        import re
        name = re.search(r'/c ""(.+\.cmd)""$', command).group(1)
        captured['name'] = name
        captured['contents'] = Path(name).read_text()
        return SimpleNamespace(returncode=0, stdout='PATH=C:\\PICADS\\bin;C:\\Windows\\System32\nCUSTOM=value\n', stderr='')
    monkeypatch.setattr(deps.subprocess, 'run', fake_run)
    result = deps._portable_windows_environment(str(activation))
    assert result['CUSTOM'] == 'value'
    assert f'call "{activation}" >nul' in captured['contents']
    assert '""' in captured['command']
    assert ' /d /s /c ' in captured['command']
    assert not Path(captured['name']).exists(), 'temporary launcher must be deleted'


def test_portable_activation_reports_errors_and_cleans_up(tmp_path, monkeypatch):
    activation = tmp_path / 'PICADS Build' / 'environment.bat'
    activation.parent.mkdir(parents=True)
    activation.write_text('@exit /b 3')
    paths=[]
    def fail(command, **kwargs):
        import re
        paths.append(Path(re.search(r'/c ""(.+\.cmd)""$', command).group(1)))
        return SimpleNamespace(returncode=3, stdout='', stderr='ACTIVATION_FAILED')
    monkeypatch.setattr(deps.subprocess, 'run', fail)
    import pytest
    with pytest.raises(deps.DependencyConfigurationError, match='ACTIVATION_FAILED'):
        deps._portable_windows_environment(str(activation))
    assert not paths[0].exists()


def test_windows_isolation_keeps_kicad_out_of_yosys_dll_path(monkeypatch, tmp_path):
    """There were DLL popups because PICADS put KiCad ahead of Yosys."""
    monkeypatch.setattr(deps.sys, 'platform', 'win32')
    cad = tmp_path / 'PICADS Build' / 'dependencies' / 'oss-cad-suite' / 'oss-cad-suite'
    kicad = tmp_path / 'PICADS Build' / 'dependencies' / 'kicad' / 'application' / 'bin'
    klayout = tmp_path / 'KLayout' / 'bin'
    msys = tmp_path / 'msys64' / 'ucrt64' / 'bin'
    paths = {'yosys': cad/'bin/yosys.exe', 'z3':cad/'bin/z3.exe',
             'iverilog':cad/'bin/iverilog.exe', 'vvp':cad/'bin/vvp.exe',
             'verilator':cad/'bin/verilator.exe', 'kicad':kicad/'kicad.exe',
             'kicad-cli':kicad/'kicad-cli.exe', 'pcbnew':kicad/'pcbnew.exe',
             'klayout':klayout/'klayout_app.exe', 'gcc':msys/'gcc.exe',
             'g++':msys/'g++.exe'}
    monkeypatch.setattr(deps, 'resolve_tool', lambda n: str(paths[n]) if n in paths else None)
    monkeypatch.setattr(deps, 'managed_cad_activation', lambda:cad/'environment.bat')
    monkeypatch.setattr(deps, '_portable_windows_environment',
                        lambda _: {'PATH':str(cad/'bin')+';C:\\Windows\\System32'})
    os_environ = {'PATH':'C:\\Windows\\System32','CUSTOM_KEEP':'yes'}
    yosys = deps.dependency_environment(os_environ, tool='yosys')
    assert str(cad/'bin') in yosys['PATH']
    for other in (kicad, klayout, msys):
        assert str(other) not in yosys['PATH']
    assert yosys['CUSTOM_KEEP'] == 'yes'
    assert yosys['PATH'].split(';')[0] == str(cad/'bin')
    z3 = deps.dependency_environment(os_environ, tool='z3')
    assert str(cad/'bin') in z3['PATH'] and str(kicad) not in z3['PATH']
    kicad_env = deps.dependency_environment(os_environ, tool='kicad-cli')
    assert kicad_env['PATH'].split(';')[0] == str(kicad)
    assert str(cad/'bin') not in kicad_env['PATH']
    klayout_env = deps.dependency_environment(os_environ, tool='klayout')
    assert klayout_env['PATH'].split(';')[0] == str(klayout)
    assert str(kicad) not in klayout_env['PATH']
    neutral = deps.dependency_environment(os_environ)
    assert neutral['PATH'] == os_environ['PATH']
    assert os_environ['PATH'] == 'C:\\Windows\\System32'


def test_windows_verilator_can_see_cpp_but_not_kicad(monkeypatch,tmp_path):
    monkeypatch.setattr(deps.sys, 'platform', 'win32')
    suite=tmp_path/'oss';mingw=tmp_path/'msys/ucrt/bin';kicad=tmp_path/'kicad/bin'
    installed={'verilator':suite/'launcher/verilator.cmd','yosys':suite/'bin/yosys.exe',
               'gcc':mingw/'gcc.exe','g++':mingw/'g++.exe', 'kicad':kicad/'kicad.exe'}
    monkeypatch.setattr(deps,'resolve_tool',lambda n:str(installed[n]) if n in installed else None)
    monkeypatch.setattr(deps,'managed_cad_activation',lambda:None)
    e=deps.dependency_environment({'PATH':'C:\\Windows\\System32'}, tool='verilator')
    assert str(mingw) in e['PATH'] and str(kicad) not in e['PATH']


def test_loader_error_codes_are_explained():
    z3=audit._version_probe('z3','z3.exe',runner=lambda *a,**k:SimpleNamespace(
        returncode=3221225785,stdout='',stderr=''))
    yosys=audit._version_probe('yosys','yosys.exe',runner=lambda *a,**k:SimpleNamespace(
        returncode=3221225781,stdout='',stderr=''))
    assert z3['failure_kind']=='DLL_ENTRY_POINT_NOT_FOUND'
    assert z3['windows_loader_error']=='0xC0000139'
    assert yosys['failure_kind']=='MISSING_RUNTIME_DLL'
    assert yosys['windows_loader_error']=='0xC0000135'


def test_audit_uses_tool_specific_environment(monkeypatch,tmp_path):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'dependencies'))
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    env_calls=[]
    def scoped_env(base=None, *, tool=None):
        env_calls.append(tool)
        return {'PATH':'isolated-for-'+str(tool)}
    monkeypatch.setattr(audit,'dependency_environment',scoped_env)
    monkeypatch.setattr(audit,'tool_status',lambda n:{'available':n in ('yosys','z3'),
                'path':'C:/mock/'+n+'.exe' if n in ('yosys','z3') else None,
                'source':'registered' if n in ('yosys','z3') else 'unavailable',
                'error':None})
    result=audit.audit(runner=lambda cmd,**kw:SimpleNamespace(returncode=0,stdout='started',stderr=''))
    assert set(env_calls)=={'yosys','z3'}
    assert result['tools']['yosys']['startup_probe']['status']=='PASS'
    assert result['tools']['z3']['startup_probe']['runtime_path_head']==['isolated-for-z3']


def test_native_validator_scopes_environment_to_original_tool(tmp_path,monkeypatch):
    trace=[]
    def fake_run(argv,**kw):
        trace.append((argv,kw.get('env',{}).get('TOOL')))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(system_validation,'resolve_tool',lambda name:'C:/mock/yosys.exe')
    monkeypatch.setattr(system_validation,'dependency_environment',lambda env,*,tool=None:{**env,'TOOL':tool})
    monkeypatch.setattr(system_validation.subprocess,'run',fake_run)
    report=system_validation._run(['yosys','-V'],tmp_path,tmp_path/'probe.log',env={'PATH':'base'})
    assert report['status']=='PASS'
    assert trace[0][1]=='yosys', 'must pass logical tool ID before replacing argv[0]'

