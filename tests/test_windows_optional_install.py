"""No network or OS modifications: fake all Windows process launches."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from chipcompiler import windows_installer as wi
from chipcompiler import windows_optional_install as opt


def test_kicad_is_selectable_in_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT', str(tmp_path/'deps'))
    rows={r['id']:r for r in wi.install_catalog()}
    assert rows['kicad']['can_install'] and rows['librelane']['can_install']
    assert rows['kicad']['mode']=='winget'
    assert rows['librelane']['mode']=='guided-wsl'


def test_kicad_winget_uses_exact_official_id_and_registers(monkeypatch,tmp_path):
    from chipcompiler import dependencies
    monkeypatch.setattr(opt.sys,'platform','win32')
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    fake_bin=tmp_path/'deps'/'kicad'/'application'/'bin'
    fake_bin.mkdir(parents=True)
    (fake_bin/'kicad.exe').write_bytes(b'exe')
    (fake_bin/'kicad-cli.exe').write_bytes(b'exe')
    monkeypatch.setattr(dependencies,'_executable',lambda f: f.is_file() and f.suffix=='.exe')
    cmds=[]
    def fake_run(argv,**kw):
        cmds.append(argv)
        (fake_bin/'pcbnew.exe').write_bytes(b'exe')
        return SimpleNamespace(stdout='ok',stderr='',returncode=0)
    result=opt.install_kicad(tmp_path/'deps', lambda _:None,run=fake_run,which=lambda x:'C:/winget.exe')
    assert result['status']=='INSTALLED'
    assert '--location' in cmds[0] and '--id' in cmds[0]
    assert cmds[0][cmds[0].index('--id')+1]=='KiCad.KiCad'
    assert dependencies.tool_status('kicad')['available']
    assert (tmp_path/'deps'/'kicad'/'winget_install.log').is_file()


def test_kicad_missing_winget_no_fake_install(monkeypatch,tmp_path):
    monkeypatch.setattr(opt.sys,'platform','win32')
    with pytest.raises(opt.GuidedSetupError,match='winget'):
        opt.install_kicad(tmp_path/'deps',lambda _:None,which=lambda x:None)
    assert not (tmp_path/'deps').exists()


def test_kicad_success_without_located_app_requires_manual_registration(monkeypatch,tmp_path):
    monkeypatch.setattr(opt.sys,'platform','win32')
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    result=opt.install_kicad(tmp_path/'deps',lambda _:None,which=lambda x:'winget.exe',
            run=lambda *args,**kwargs: SimpleNamespace(stdout='ok',stderr='',returncode=0))
    assert result['status']=='SETUP_REQUIRED'
    assert not (tmp_path/'settings'/'dependencies.json').exists()


def test_librelane_preparation_requires_explicit_launch(monkeypatch,tmp_path):
    monkeypatch.setattr(opt.sys,'platform','win32')
    started=[]
    result=opt.stage_librelane(tmp_path/'dependencies',lambda _:None,
                               popen=lambda *args,**kwargs:started.append((args,kwargs)))
    assert result['status']=='SETUP_STARTED'
    assert len(started)==1
    script=Path(result['launcher']).read_text()
    assert 'wsl.exe --install -d Ubuntu' in script
    assert 'Docker.DockerDesktop' in script
    assert '--smoke-test' in script
    assert 'backend_smoke_passed.txt' in script
    assert not Path(result['directory'],'backend_smoke_passed.txt').exists()


def test_librelane_does_not_launch_without_selection(monkeypatch,tmp_path):
    monkeypatch.setattr(opt.sys,'platform','win32')
    result=opt.stage_librelane(tmp_path,lambda _:None,launch=False)
    assert result['status']=='SETUP_REQUIRED'
    assert Path(result['launcher']).is_file()


def test_librelane_missing_windows_keeps_backend_unconfigured(tmp_path):
    if opt.sys.platform!='win32':
        with pytest.raises(opt.GuidedSetupError,match='Windows'):
            opt.stage_librelane(tmp_path,lambda _:None)


def test_winget_failure_does_not_register(monkeypatch,tmp_path):
    monkeypatch.setattr(opt.sys,'platform','win32')
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    with pytest.raises(opt.GuidedSetupError,match='returned 7'):
        opt.install_kicad(tmp_path/'deps',lambda _:None,which=lambda _: 'winget',
            run=lambda *a,**k:SimpleNamespace(stdout='error',stderr='no',returncode=7))
    assert not (tmp_path/'settings'/'dependencies.json').exists()


def test_install_selected_reports_pending_backend_not_pass(monkeypatch,tmp_path):
    monkeypatch.setattr(wi,'install_package', lambda package,**kw:
                        {'status':'SETUP_STARTED'} if package=='librelane' else {'status':'INSTALLED'})
    result=wi.install_selected(['kicad','librelane'])
    assert result['status']=='PARTIAL'


def test_librelane_catalog_requires_completed_smoke_marker(tmp_path,monkeypatch):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'dependencies'))
    directory=tmp_path/'dependencies'/'librelane'
    directory.mkdir(parents=True)
    before={r['id']:r for r in wi.install_catalog()}['librelane']
    assert not before['installed'] and before['can_install']
    (directory/'backend_smoke_passed.txt').write_text('LIBRELANE_SMOKE_TEST_PASS\n')
    after={r['id']:r for r in wi.install_catalog()}['librelane']
    assert after['installed'] and after['can_install']


def test_gui_checkbox_not_hard_disabled_in_source():
    src=(Path(__file__).parents[1]/'src'/'chipcompiler'/'gui.py').read_text()
    assert "check.setEnabled(spec['can_install'])" in src
    assert "spec['mode'] == 'winget'" in src
    assert 'LibreLane requires Windows backend setup' in src
