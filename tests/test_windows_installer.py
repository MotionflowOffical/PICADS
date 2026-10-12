"""Offline tests for Windows native dependency download, registration and archive safety."""
import io
import json
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from chipcompiler import windows_installer as wi
from chipcompiler.dependencies import resolve_tool, dependency_environment


def _fake_zip(target: Path, entries: dict[str, bytes]):
    with zipfile.ZipFile(target, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)


def _asset(name: str = 'mock-windows-x64.zip') -> dict:
    return {'name':name, 'url':'https://github.com/YosysHQ/oss-cad-suite-build/releases/download/test/'+name,
            'version':'test', 'digest':None,'allowed_hosts':wi._GITHUB_HOSTS}


def test_native_portable_windows_bundle_installs_only_selected(tmp_path,monkeypatch):
    root=tmp_path/'dependencies'
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(root))
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'user'))
    archive=tmp_path/'fixture.zip'
    _fake_zip(archive, {
        'oss-cad-suite/bin/yosys.exe':b'fake yosys',
        'oss-cad-suite/bin/iverilog.exe':b'fake iverilog',
        'oss-cad-suite/bin/vvp.exe':b'fake vvp',
        'oss-cad-suite/environment.bat':b'@echo off',
        'other/non-essential.txt':b'test'})
    original_download=wi._download
    def local_download(asset,path,progress):
        import shutil
        shutil.copyfile(archive,path)
        return 'a'*64
    monkeypatch.setattr(wi,'_download',local_download)
    # On Linux, fake .exe files need execute permission to satisfy the existing
    # cross-platform registry contract. This test exercises Windows selection
    # through monkeypatched _executable, with no actual code execution.
    from chipcompiler import dependencies
    monkeypatch.setattr(dependencies,'_executable',lambda file:file.is_file() and file.suffix.lower()=='.exe')
    result=wi.install_package('oss-cad-suite',asset_override=_asset())
    assert result['status']=='INSTALLED'
    assert (root/'oss-cad-suite/oss-cad-suite/bin/yosys.exe').is_file()
    assert Path(resolve_tool('yosys')).name=='yosys.exe'
    assert Path(resolve_tool('iverilog')).name=='iverilog.exe'
    assert Path(resolve_tool('vvp')).name=='vvp.exe'
    assert json.loads((root/'oss-cad-suite/picads_install_receipt.json').read_text())['upstream_digest_checked'] is False
    assert not (root/'klayout').exists()
    with pytest.raises(wi.PackageInstallError,match='already exists'):
        wi.install_package('oss-cad-suite',asset_override=_asset())


def test_install_rejects_archive_traversal(tmp_path):
    archive=tmp_path/'bad.zip'
    _fake_zip(archive,{'../outside.txt':b'escaped'})
    with pytest.raises(wi.PackageInstallError,match='traversal'):
        wi._extract(archive,tmp_path/'unpack',lambda message:None)
    assert not (tmp_path/'outside.txt').exists()


def test_installer_rejects_unexpected_origins():
    for url in ('http://github.com/a','https://evil.example.com/a',
                'https://github.com.evil.example.com/a'):
        with pytest.raises(wi.PackageInstallError):
            wi._ensure_allowed_url(url, wi._GITHUB_HOSTS)


def test_installer_rejects_tar_traversal_and_external_links(tmp_path):
    tar=tmp_path/'archive.tgz'
    with tarfile.open(tar,'w:gz') as t:
        info=tarfile.TarInfo('a/../../outside');info.size=3
        t.addfile(info,io.BytesIO(b'bad'))
    with pytest.raises(wi.PackageInstallError,match='traversal'):
        wi._extract(tar,tmp_path/'out',lambda _:None)
    assert not (tmp_path/'outside').exists()


def test_selection_avoids_unrequested_packages(monkeypatch,tmp_path):
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path))
    seen=[]
    def fake(package,**kwargs):
        seen.append(package)
        return {'status':'INSTALLED','package':package}
    monkeypatch.setattr(wi,'install_package',fake)
    result=wi.install_selected(['klayout','klayout'])
    assert seen==['klayout']
    assert result['status']=='PASS'
    assert 'oss-cad-suite' not in result['packages']


def test_optional_packages_use_explicit_windows_installers(monkeypatch):
    from chipcompiler import windows_optional_install as optional
    calls=[]
    monkeypatch.setattr(optional,'install_kicad',lambda root,progress: calls.append('kicad') or {'status':'INSTALLED'})
    monkeypatch.setattr(optional,'stage_librelane',lambda root,progress: calls.append('librelane') or {'status':'SETUP_STARTED'})
    assert wi.install_package('kicad')['status']=='INSTALLED'
    assert wi.install_package('librelane')['status']=='SETUP_STARTED'
    assert calls==['kicad','librelane']


def test_windows_exe_activation_is_child_only(monkeypatch,tmp_path):
    from chipcompiler import dependencies as deps
    fake=tmp_path/'environment.bat'
    fake.write_text('@echo off')
    monkeypatch.setattr(deps,'managed_cad_activation',lambda:fake)
    monkeypatch.setattr(deps,'_portable_windows_environment',lambda _:{'PATH':'native;tool','PYTHONPATH':'nativepython'})
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'config'))
    untouched=os.environ.get('PATH')
    result=dependency_environment({'PATH':'ORIGINAL','PICADS_CUSTOM':'retained'})
    assert result['PICADS_CUSTOM']=='retained'
    assert 'native;tool' in result['PATH']
    assert os.environ.get('PATH')==untouched


def test_gui_exposes_real_install_dialog_and_cli_catalog():
    import ast
    root=Path(__file__).parents[1]
    code=(root/'src/chipcompiler/gui.py').read_text()
    tree=ast.parse(code)
    names={n.name for n in ast.walk(tree) if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
    assert {'WindowsInstallerDialog','WindowsInstallWorker','open_windows_installer','begin_install'} <= names
    from chipcompiler.cli import main
    from contextlib import redirect_stdout
    out=io.StringIO()
    with redirect_stdout(out):
        assert main(['dependencies','catalog'])==0
    catalog=json.loads(out.getvalue())
    assert catalog['packages'][0]['id']=='oss-cad-suite'


def test_github_release_selects_windows_x64_only(monkeypatch):
    import contextlib
    release = {'tag_name':'2026-10-11','assets':[
        {'name':'oss-cad-suite-linux-x64-20261011.tgz','browser_download_url':'https://github.com/linux','size':21},
        {'name':'oss-cad-suite-windows-x64-20261011.tgz',
         'browser_download_url':'https://github.com/YosysHQ/oss-cad-suite-build/releases/download/x/win.tgz',
         'digest':'sha256:'+'a'*64,'size':31}]}
    monkeypatch.setattr(wi,'_open',lambda url, allowed:contextlib.closing(io.BytesIO(json.dumps(release).encode())))
    asset=wi._oss_asset()
    assert 'windows-x64' in asset['name']
    assert asset['version']=='2026-10-11'
    assert asset['bytes']==31


def test_klayout_official_links_numeric_version_order(monkeypatch):
    import contextlib
    html='''<a href="/downloads/windows/klayout-0.30.9-win64-ucrt.zip">old</a>
    <a href="https://evil.example.com/klayout-99.9.9-win64-ucrt.zip">evil</a>
    <a href="/downloads/windows/klayout-0.30.12-win64-ucrt.zip">new</a>'''
    monkeypatch.setattr(wi,'_open',lambda url, allowed:contextlib.closing(io.BytesIO(html.encode())))
    assert wi._klayout_asset()['name']=='klayout-0.30.12-win64-ucrt.zip'


def test_upstream_hash_failure_rejects_download(tmp_path,monkeypatch):
    import contextlib
    monkeypatch.setattr(wi,'_open',lambda url, allowed, timeout=60:contextlib.closing(io.BytesIO(b'bad asset')))
    asset=_asset();asset['digest']='sha256:'+'0'*64
    with pytest.raises(wi.PackageInstallError,match='digest mismatch'):
        wi._download(asset,tmp_path/'download',lambda _:None)


def test_archive_failure_does_not_register_tool(monkeypatch,tmp_path):
    from chipcompiler import dependencies
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'deps'))
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'registry'))
    bad=tmp_path/'bad.zip';_fake_zip(bad,{'../escape':b'no'})
    def fake_download(asset,path,progress):
        import shutil
        shutil.copyfile(bad,path)
        return 'a'*64
    monkeypatch.setattr(wi,'_download',fake_download)
    with pytest.raises(wi.PackageInstallError,match='traversal'):
        wi.install_package('oss-cad-suite',asset_override=_asset())
    assert not (tmp_path/'deps/oss-cad-suite').exists()
    assert not dependencies.settings_file().exists()


def test_install_catalog_respects_optional_binaries_and_managed_paths(tmp_path, monkeypatch):
    """A correctly installed synthesis suite needn't include every formal tool."""
    from chipcompiler import dependencies
    root = tmp_path / 'deps'
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT', str(root))
    monkeypatch.setenv('PICADS_SETTINGS_DIR', str(tmp_path / 'settings'))
    managed = root / 'oss-cad-suite'
    bindir = managed / 'oss-cad-suite' / 'bin'
    bindir.mkdir(parents=True)
    for name in ('yosys', 'iverilog', 'vvp'):
        (bindir / (name + '.exe')).write_bytes(b'example')
    (managed / 'picads_install_receipt.json').write_text(json.dumps({
        'package': 'oss-cad-suite',
        'resolved_tools': {t: 'oss-cad-suite/bin/' + t + '.exe' for t in ('yosys', 'iverilog', 'vvp')}
    }))
    catalog = {r['id']: r for r in wi.install_catalog()}
    assert catalog['oss-cad-suite']['installed'] is True
    assert catalog['oss-cad-suite']['can_install'] is False
    assert catalog['klayout']['installed'] is False
    assert catalog['klayout']['can_install'] is True
    assert catalog['librelane']['can_install'] is True
    assert catalog['kicad']['can_install'] is True
    # Deleting a managed executable should never make the UI advertise a
    # successful install or overwrite its directory without permission.
    (bindir / 'yosys.exe').unlink()
    state = {r['id']: r for r in wi.install_catalog()}['oss-cad-suite']
    assert not state['installed']
    assert state['managed_path_exists']
    assert not state['can_install']


def test_klayout_native_windows_archive_registers_klayout_app(tmp_path, monkeypatch):
    """KLayout's official portable archive uses klayout_app.exe, not klayout.exe."""
    from chipcompiler import dependencies
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT', str(tmp_path / 'dependencies'))
    monkeypatch.setenv('PICADS_SETTINGS_DIR', str(tmp_path / 'settings'))
    archive = tmp_path / 'klayout.zip'
    _fake_zip(archive, {'klayout-0.30.12-win64-ucrt/klayout_app.exe': b'example executable',
                        'klayout-0.30.12-win64-ucrt/QtCore.dll': b'dll'})
    def fake_download(asset, path, progress):
        import shutil
        shutil.copyfile(archive, path)
        return 'b' * 64
    monkeypatch.setattr(wi, '_download', fake_download)
    monkeypatch.setattr(dependencies, '_executable',
                        lambda file: file.is_file() and file.suffix.lower() == '.exe')
    result = wi.install_package('klayout', asset_override={
        'name': 'klayout-0.30.12-win64-ucrt.zip', 'version': '0.30.12',
        'url': 'https://www.klayout.de/downloads/klayout-0.30.12-win64-ucrt.zip',
        'allowed_hosts': wi._KLAYOUT_HOSTS, 'digest': None})
    assert result['status'] == 'INSTALLED'
    assert Path(resolve_tool('klayout')).name == 'klayout_app.exe'
    assert (tmp_path / 'dependencies' / 'klayout' / 'picads_install_receipt.json').exists()
    status = {r['id']: r for r in wi.install_catalog()}['klayout']
    assert status['installed'] and not status['can_install']
