"""Offline tests for actual PICADS 0.16.3 missing-tool reports."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from chipcompiler import dependencies as deps
from chipcompiler import windows_installer as installer
from chipcompiler import windows_optional_install as optional
from chipcompiler import windows_tool_audit as audit


def _launcher(file):
    return file.is_file() and file.suffix.lower() in ('.exe','.cmd','.bat','.com')


def test_kicad_repair_registers_pcbnew_without_reinstall(tmp_path, monkeypatch):
    monkeypatch.setattr(optional.sys,'platform','win32')
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    monkeypatch.setattr(deps,'_executable',_launcher)
    apps=tmp_path/'deps'/'kicad'/'application'/'bin'
    apps.mkdir(parents=True)
    for name in ('kicad','kicad-cli','pcbnew'):
        (apps/(name+'.exe')).write_bytes(b'exe')
    def no_winget(*a,**kw):
        raise AssertionError('KiCad was already installed; do not run WinGet again')
    result=optional.install_kicad(tmp_path/'deps',lambda _:None,
                                  which=no_winget,run=no_winget)
    assert result['status']=='INSTALLED' and result['repaired']
    assert set(result['tools'])=={'kicad','kicad-cli','pcbnew'}
    assert deps.tool_status('pcbnew')['available']


def test_oss_cad_verilator_bin_gets_real_windows_wrapper(tmp_path,monkeypatch):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'deps'))
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    monkeypatch.setattr(deps,'_executable',_launcher)
    root=tmp_path/'deps'/'oss-cad-suite'
    bin=root/'oss-cad-suite'/'bin'
    share=root/'oss-cad-suite'/'share'/'verilator'
    bin.mkdir(parents=True);share.mkdir(parents=True)
    for n in ('yosys','iverilog','vvp','verilator_bin','gcc','g++'):
        (bin/(n+'.exe')).write_bytes(b'exe')
    (bin/'verilator').write_text('#!/usr/bin/perl')
    (root/'picads_install_receipt.json').write_text(json.dumps({'package':'oss-cad-suite'}))
    result=installer.repair_package('oss-cad-suite')
    assert result['status']=='INSTALLED'
    assert {'yosys','iverilog','vvp','gcc','g++','verilator'} <= set(result['tools'])
    wrapper=Path(result['tools']['verilator'])
    assert wrapper.name=='verilator.cmd'
    text=wrapper.read_text()
    assert 'verilator_bin.exe' in text and 'VERILATOR_ROOT' in text
    assert '%*' in text
    assert deps.resolve_tool('verilator')==str(wrapper)


def test_oss_cad_missing_verilator_binary_does_not_fake_install(tmp_path,monkeypatch):
    root=tmp_path/'deps'/'oss-cad-suite'
    (root/'oss-cad-suite'/'bin').mkdir(parents=True)
    assert installer._oss_verilator_wrapper(root,lambda _:None) is None
    assert not (root/'picads-launchers'/'verilator.cmd').exists()


def test_msys2_complete_install_is_registered_without_network(tmp_path,monkeypatch):
    monkeypatch.setattr(optional.sys,'platform','win32')
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    monkeypatch.setenv('MSYS2_ROOT',str(tmp_path/'msys64'))
    monkeypatch.setattr(deps,'_executable',_launcher)
    root=tmp_path/'msys64'
    for path in ('usr/bin/bash.exe','usr/bin/pacman.exe','usr/bin/perl.exe',
                 'ucrt64/bin/gcc.exe','ucrt64/bin/g++.exe',
                 'ucrt64/bin/verilator_bin.exe','ucrt64/bin/verilator'):
        file=root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'exe')
    def no_winget(*a,**kw):
        raise AssertionError('Do not call WinGet/pacman for an existing toolchain')
    result=optional.install_msys2_toolchain(tmp_path/'deps',lambda _:None,
                                           run=no_winget,which=no_winget)
    assert result['status']=='INSTALLED'
    assert set(result['tools'])=={'gcc','g++','verilator'}
    script=Path(result['tools']['verilator']).read_text()
    assert 'perl.exe' in script and 'ucrt64' in script
    assert deps.tool_status('gcc')['available']


def test_msys2_package_upgrade_error_never_claims_install(tmp_path,monkeypatch):
    monkeypatch.setattr(optional.sys,'platform','win32')
    monkeypatch.setenv('MSYS2_ROOT',str(tmp_path/'msys64'))
    msys=tmp_path/'msys64'
    bash=msys/'usr/bin/bash.exe';bash.parent.mkdir(parents=True)
    bash.write_bytes(b'exe')
    (msys/'usr/bin/pacman.exe').write_bytes(b'exe')
    events=[]
    def fail_pacman(cmd,**kw):
        events.append(cmd)
        return SimpleNamespace(returncode=11,stdout='update failed',stderr='')
    result=optional.install_msys2_toolchain(tmp_path/'deps',lambda _:None,
                                           run=fail_pacman, which=lambda _:None)
    assert result['status']=='SETUP_REQUIRED'
    assert any('pacman.exe' in str(path) for cmd in events for path in cmd)
    assert not (tmp_path/'deps'/'msys2-toolchain'/'picads_install_receipt.json').exists()


def test_catalog_has_msys2_and_kicad_pcbnew(tmp_path, monkeypatch):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'deps'))
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    cats={row['id']:row for row in installer.install_catalog()}
    assert 'pcbnew' in cats['kicad']['tools']
    assert set(cats['msys2-toolchain']['tools'])=={'gcc','g++','verilator'}
    assert cats['msys2-toolchain']['can_install']
    assert cats['msys2-toolchain']['mode']=='winget-msys2'


def test_audit_records_missing_and_failed_launches(tmp_path, monkeypatch):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'deps'))
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    exe=tmp_path/'fake.exe';exe.write_bytes(b'fake')
    monkeypatch.setattr(deps,'_executable',_launcher)
    deps.register_tool('gcc',exe,'app') if exe.name=='gcc.exe' else None
    calls=[]
    assert audit._version_probe('gcc',str(exe),runner=lambda *a,**kw:
             SimpleNamespace(returncode=1,stdout='',stderr='not started'))['status']=='FAILED'
    result=audit.audit(runner=lambda *a,**kw:SimpleNamespace(returncode=0,stdout='ok',stderr=''))
    assert result['tools']['pcbnew']['startup_probe']['status']=='UNAVAILABLE'
    assert result['backend']['status']=='NOT_VERIFIED'


def test_gui_displays_backend_not_native_tools():
    src=(Path(__file__).parents[1]/'src'/'chipcompiler'/'gui.py').read_text()
    assert 'BACKEND CONFIGURED' in src and "('openroad', 'magic', 'netgen')" in src
    assert 'winget-msys2' in src


def test_msys2_full_winget_and_pacman_mock_install(tmp_path,monkeypatch):
    monkeypatch.setattr(optional.sys,'platform','win32')
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    monkeypatch.delenv('MSYS2_ROOT',raising=False)
    monkeypatch.setattr(deps,'_executable',_launcher)
    root=tmp_path/'dependencies'
    calls=[]
    def fake_run(command,**kw):
        calls.append(command)
        chosen=root/'msys2-toolchain'/'application'
        if 'install' in command:
            for n in ('usr/bin/bash.exe','usr/bin/pacman.exe'):
                f=chosen/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'exe')
        if any('pacman.exe' in str(e) for e in command) and '-S' in command:
            for n in ('usr/bin/perl.exe','ucrt64/bin/gcc.exe','ucrt64/bin/g++.exe',
                      'ucrt64/bin/verilator_bin.exe','ucrt64/bin/verilator'):
                f=chosen/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'exe')
        return SimpleNamespace(returncode=0,stdout='ok',stderr='')
    result=optional.install_msys2_toolchain(root,lambda _:None,
                      run=fake_run,which=lambda n: str(tmp_path/'winget.exe'))
    assert result['status']=='INSTALLED' and not result['repaired']
    assert len(calls)==3
    assert 'MSYS2.MSYS2' in calls[0]
    assert result['tools']['gcc'].endswith('gcc.exe')
    assert (root/'msys2-toolchain'/'picads_install_receipt.json').exists()
    assert (root/'msys2-toolchain'/'pacman_toolchain_packages.log').exists()
