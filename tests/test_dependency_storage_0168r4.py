"""Regression tests for reversible managed dependencies and protected user data."""
import json
import os
import time
import subprocess
from pathlib import Path

import pytest

from chipcompiler import dependency_storage as ds
from chipcompiler.cli import main
from chipcompiler.dependencies import register_tool, tool_status


def fixture_root(tmp_path, monkeypatch):
    root = tmp_path / 'dependencies'
    root.mkdir()
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT', str(root))
    monkeypatch.setenv('PICADS_SETTINGS_DIR', str(tmp_path / 'registry'))
    return root


def portable(root, key='oss-cad-suite'):
    directory = root / key
    directory.mkdir()
    file = directory / 'bin' / 'yosys.exe'
    file.parent.mkdir(); file.write_bytes(b'YOSYS' * 42)
    (directory / 'picads_install_receipt.json').write_text(json.dumps({
        'package': key, 'resolved_tools': {'yosys':'bin/yosys.exe', 'iverilog':'bin/yosys.exe', 'vvp':'bin/yosys.exe'}}))
    return directory


def test_inventory_only_and_deletion_requires_confirmation(tmp_path, monkeypatch):
    root = fixture_root(tmp_path, monkeypatch)
    directory = portable(root)
    outside = tmp_path / 'projects' / 'important.chip'; outside.parent.mkdir()
    outside.write_text('my work')
    info = ds.storage_inventory(root=root, include_wsl=False)
    assert 'package:oss-cad-suite' in [e['id'] for e in info['entries']]
    assert directory.exists()
    with pytest.raises(ds.StorageSafetyError, match='confirmation'):
        ds.apply_storage_cleanup(['package:oss-cad-suite'], root=root, include_wsl=False)
    assert directory.exists() and outside.exists()


def test_portable_removal_forgets_only_selected_managed_paths(tmp_path, monkeypatch):
    root = fixture_root(tmp_path, monkeypatch)
    directory = portable(root)
    other = tmp_path / 'outside' / 'klayout.exe';other.parent.mkdir()
    other.write_text('other')
    from chipcompiler import dependencies
    monkeypatch.setattr(dependencies, '_executable', lambda f: f.is_file())
    register_tool('yosys', directory / 'bin' / 'yosys.exe')
    register_tool('klayout', other)
    removed = ds.apply_storage_cleanup(['package:oss-cad-suite'], root=root, include_wsl=False, confirmed=True)
    assert removed['status'] == 'PASS'
    assert not directory.exists() and other.exists()
    assert dependencies.read_settings()['tools'] == {'klayout': {'kind':'app','path':str(other)}}
    assert 'yosys' in removed['results'][0]['cleared_tools']


def test_untracked_or_wrong_receipt_preserved(tmp_path, monkeypatch):
    root = fixture_root(tmp_path, monkeypatch)
    one = root / 'oss-cad-suite';one.mkdir()
    (one / 'user_file').write_text('keep')
    assert all(e['id'] != 'package:oss-cad-suite' for e in ds.storage_inventory(root=root,include_wsl=False)['entries'])
    with pytest.raises(ds.StorageSafetyError, match='Not found'):
        ds.apply_storage_cleanup(['package:oss-cad-suite'], root=root, confirmed=True,include_wsl=False)
    (one / 'picads_install_receipt.json').write_text('{"package":"wrong"}')
    assert 'package:oss-cad-suite' not in [e['id'] for e in ds.storage_inventory(root=root,include_wsl=False)['entries']]
    assert (one / 'user_file').exists()


def test_install_leftovers_older_than_one_day_only(tmp_path, monkeypatch):
    root = fixture_root(tmp_path, monkeypatch)
    old = root / '.picads-install-old';old.mkdir()
    (old / 'download.tar.gz').write_bytes(b'junk' * 200)
    os.utime(old, (time.time()-172800,time.time()-172800))
    fresh = root / '.picads-install-current';fresh.mkdir()
    (fresh / 'download.zip').write_text('busy')
    ids = {r['id'] for r in ds.storage_inventory(root=root,include_wsl=False)['entries']}
    assert 'cache:staging:.picads-install-old' in ids
    assert 'cache:staging:.picads-install-current' not in ids
    result=ds.apply_storage_cleanup(['cache:staging:.picads-install-old'],root=root,
                                    confirmed=True,include_wsl=False)
    assert result['status']=='PASS' and not old.exists() and fresh.exists()


def test_managed_docker_download_only_not_real_docker(tmp_path, monkeypatch):
    root = fixture_root(tmp_path, monkeypatch)
    cache = root / 'librelane' / 'docker-installer-cache';cache.mkdir(parents=True)
    (cache / 'Docker Desktop Installer.exe').write_bytes(b'cache')
    precious = tmp_path / 'Docker' / 'images';precious.parent.mkdir()
    precious.write_text('never delete')
    result=ds.apply_storage_cleanup(['cache:docker-installer'], root=root,
                                    confirmed=True,include_wsl=False)
    assert result['status']=='PASS'
    assert precious.read_text()=='never delete' and not cache.exists()


def test_symlinked_package_refused(tmp_path, monkeypatch):
    root=fixture_root(tmp_path,monkeypatch)
    target=tmp_path/'external_oss'
    target.mkdir()
    (target/'picads_install_receipt.json').write_text('{"package":"oss-cad-suite"}')
    try:
        (root/'oss-cad-suite').symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation forbidden by OS')
    assert 'package:oss-cad-suite' not in [r['id'] for r in ds.storage_inventory(root=root,include_wsl=False)['entries']]
    with pytest.raises(ds.StorageSafetyError):
        ds.apply_storage_cleanup(['package:oss-cad-suite'],root=root,
                                 confirmed=True,include_wsl=False)
    assert (target/'picads_install_receipt.json').exists()


def test_traversal_and_duplicated_selection_rejected(tmp_path, monkeypatch):
    root=fixture_root(tmp_path,monkeypatch)
    portable(root)
    with pytest.raises(ds.StorageSafetyError):
        ds.apply_storage_cleanup(['package:../../home'],root=root,confirmed=True,include_wsl=False)
    with pytest.raises(ds.StorageSafetyError):
        ds.apply_storage_cleanup(['package:oss-cad-suite']*2,root=root,confirmed=True,include_wsl=False)
    assert (root/'oss-cad-suite').exists()


def test_wsl_venv_removes_only_own_env_and_receipt(tmp_path,monkeypatch):
    root=fixture_root(tmp_path,monkeypatch)
    backend = root / 'librelane';backend.mkdir()
    (backend/'backend_smoke_passed.txt').write_text('LIBRELANE_SMOKE_TEST_PASS')
    (backend/'backend_smoke_receipt.json').write_text(json.dumps({'status':'PASS','distro':'Ubuntu'}))
    (backend/'wsl_distribution.txt').write_text('Ubuntu')
    calls=[]
    def fake_run(args,**kw):
        calls.append(args)
        if 'du -sk' in args[-1]:
            return subprocess.CompletedProcess(args,0,'1024\n','')
        return subprocess.CompletedProcess(args,0,'','')
    entries=ds.storage_inventory(root=root,run=fake_run)['entries']
    row=next(e for e in entries if e['id']=='wsl:librelane-venv')
    assert row['bytes']==1024*1024
    result=ds.apply_storage_cleanup(['wsl:librelane-venv'],root=root,confirmed=True,run=fake_run)
    assert result['status']=='PASS'
    assert not (backend/'backend_smoke_receipt.json').exists()
    assert (backend/'wsl_distribution.txt').read_text()=='Ubuntu'
    assert any(a[:4]==['wsl.exe','--distribution','Ubuntu','--exec'] and 'venv' in a[-1] for a in calls)
    assert not any('docker' in ' '.join(a) or 'wsl --unregister' in ' '.join(a) for a in calls)


def test_failed_wsl_command_preserves_verification_receipt(tmp_path,monkeypatch):
    root=fixture_root(tmp_path,monkeypatch)
    backend=root/'librelane';backend.mkdir()
    receipt=backend/'backend_smoke_receipt.json'
    receipt.write_text('{"status":"PASS","distro":"Ubuntu"}')
    def fails(args,**kw):return subprocess.CompletedProcess(args,6,'','permission denied')
    result=ds.apply_storage_cleanup(['wsl:librelane-venv'],root=root,confirmed=True,run=fails)
    assert result['status']=='PARTIAL' and receipt.exists()
    assert 'permission denied' in result['results'][0]['error']


def test_cli_preview_without_apply(tmp_path,monkeypatch,capsys):
    root=fixture_root(tmp_path,monkeypatch)
    folder=portable(root)
    assert main(['dependencies','uninstall','oss-cad-suite'])==0
    text=capsys.readouterr().out
    assert 'PREVIEW_ONLY' in text and folder.exists()
    assert main(['dependencies','uninstall','oss-cad-suite','--apply'])==0
    assert not folder.exists()


def test_gui_implementation_is_real_and_exposes_cleanup():
    import ast
    code=(Path(__file__).resolve().parents[1] / 'src/chipcompiler/gui.py').read_text()
    names={n.name for n in ast.walk(ast.parse(code)) if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
    assert {'DependencyStorageDialog','DependencyStorageWorker','open_dependency_storage',
            'remove_selected','scanned','removed'} <= names
