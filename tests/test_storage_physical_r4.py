"""Safety and interop tests for storage lifecycle and PICADS physical artifacts."""
import json
import shutil
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from chipcompiler.cli import init_project, main
from chipcompiler import dependency_storage as ds
from chipcompiler.physical_setup import configure_physical_project
from chipcompiler.pipeline import BuildSession
from chipcompiler.tools import wsl_working_directory


def test_configuration_preserves_settings_and_original_yaml(tmp_path):
    root=tmp_path/'chip';init_project(root)
    path=root/'chip.yaml';path.write_text(path.read_text()+'\n# KEEP_THIS_COMMENT\nverification:\n  external_rtl: false\n')
    out=configure_physical_project(root,distribution='Ubuntu',pdk='sky130A')
    cfg=yaml.safe_load(path.read_text())
    assert cfg['physical']['enabled'] is True
    assert cfg['physical']['pdk']=='sky130A'
    assert cfg['tools']=={'execution':'wsl','wsl_distribution':'Ubuntu'}
    assert cfg['verification']['external_rtl'] is False
    assert 'KEEP_THIS_COMMENT' in Path(out['original_backup']).read_text()
    assert out['status']=='CONFIGURED_NOT_VERIFIED'


def test_configuration_rejects_bad_input_without_mutation(tmp_path):
    root=tmp_path/'chip';init_project(root)
    raw=(root/'chip.yaml').read_bytes()
    with pytest.raises(ValueError): configure_physical_project(root, distribution='Ubuntu\nother')
    assert (root/'chip.yaml').read_bytes()==raw


def test_wsl_path_conversion_is_argv_based_and_checks_visibility(tmp_path):
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if 'wslpath' in args:
            return subprocess.CompletedProcess(args,0,'/mnt/c/Chip Software/build/latest\n','')
        return subprocess.CompletedProcess(args,0,'','')
    actual=wsl_working_directory('wsl.exe','Ubuntu',tmp_path,runner=run)
    assert actual=='/mnt/c/Chip Software/build/latest'
    assert all(cmd[:3]==['wsl.exe','--distribution','Ubuntu'] for cmd in calls)
    assert calls[0][-2]=='-u'
    assert calls[1][-3:]==['test','-d',actual]


def test_wsl_unmapped_folder_does_not_succeed(tmp_path):
    def run(args,**kwargs):
        if 'wslpath' in args:
            return subprocess.CompletedProcess(args,0,'/mnt/c/whatever\n','')
        return subprocess.CompletedProcess(args,1,'','not mounted')
    with pytest.raises(ValueError,match='not visible'):
        wsl_working_directory('wsl.exe','Ubuntu',tmp_path,runner=run)


def _gds(top='calculate'):
    def rec(t,d=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,t,d)+payload
    return (rec(0,2,b'\x02\x58')+rec(1,2,b'\0'*24)+rec(2,6,b'PICADS')+
            rec(5,2,b'\0'*24)+rec(6,6,top.encode())+
            rec(8)+rec(13,2,b'\0\x01')+rec(17)+rec(7)+rec(4))


def test_successful_external_layout_is_discoverable_without_large_copy(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    cfg=root/'chip.yaml';cfg.write_text(cfg.read_text().replace('enabled: false','enabled: true\n  pdk: sky130A'))
    from chipcompiler import pipeline
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kwargs):
        if stage=='yosys':
            (cwd/'synthesized.v').write_text('module calculate(); endmodule')
        elif stage=='physical':
            tag=argv[argv.index('--run-tag')+1]
            folder=cwd/'runs'/tag/'final'/'gds'
            folder.mkdir(parents=True)
            (folder/'calculate.gds').write_bytes(_gds())
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    report=BuildSession(root,'physical').run()
    assert report.stages['physical']['status']=='PASS', report.as_dict()
    manifest=json.loads((root/'build/latest/layout_artifacts.json').read_text())
    assert manifest['status']=='LAYOUT_GENERATED_NOT_MASK_SIGNOFF'
    assert manifest['layers']=={'1':1}
    assert not (root/'build/latest/calculate.gds').exists() # No storage-wasting duplicate
    assert Path(report.files['gds']).exists()
    assert manifest['duplicated_large_files'] is False


def test_disabled_physical_fails_before_invoking_yosys(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    from chipcompiler import pipeline
    monkeypatch.setattr(pipeline,'run_external', lambda *args,**kw:pytest.fail('No tool should start'))
    report=BuildSession(root,'physical').run()
    assert report.stages['physical']['status']=='BLOCKED'
    assert 'PHYSICAL.DISABLED' in [e['code'] for e in report.issues]


def test_generated_history_cleanup_preserves_sources_and_latest(tmp_path):
    root=tmp_path/'chip';init_project(root)
    BuildSession(root,'compile').run()
    BuildSession(root,'compile').run()
    archive=root/'build/history'
    assert any(archive.iterdir())
    inventory=ds.storage_inventory(root=tmp_path/'deps',project=root,include_wsl=False)
    ids={item['id'] for item in inventory['entries']}
    assert 'project:build-history' in ids and 'project:build-latest' in ids
    with pytest.raises(ds.StorageSafetyError):
        ds.apply_storage_cleanup(['project:build-history'], root=tmp_path/'deps',project=root,include_wsl=False)
    removed=ds.apply_storage_cleanup(['project:build-history'],root=tmp_path/'deps',project=root,
                                    confirmed=True,include_wsl=False)
    assert removed['status']=='PASS'
    assert (root/'chip.yaml').is_file() and (root/'build/latest/report.json').is_file()
    assert not archive.exists()


def test_manual_unknown_history_blocks_automatic_cleanup(tmp_path):
    root=tmp_path/'chip';init_project(root)
    history=root/'build/history';history.mkdir(parents=True)
    (history/'my_file.txt').write_text('IMPORTANT')
    info=ds.storage_inventory(root=tmp_path/'deps',project=root,include_wsl=False)
    assert 'project:build-history' not in {e['id'] for e in info['entries']}
    assert (history/'my_file.txt').exists()


def test_wsl_scoped_pip_cache_is_managed_without_touching_shared_cache(tmp_path):
    dependencies = tmp_path/'dependencies'
    librelane = dependencies/'librelane';librelane.mkdir(parents=True)
    (librelane/'wsl_distribution.txt').write_text('Ubuntu')
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if 'du -sk' in args[-1]:
            return subprocess.CompletedProcess(args,0,'100\n','')
        return subprocess.CompletedProcess(args,0,'','')
    inventory=ds.storage_inventory(root=dependencies,run=run)
    row=next(x for x in inventory['entries'] if x['id']=='wsl:picads-pip-cache')
    assert row['bytes']==102400
    result=ds.apply_storage_cleanup(['wsl:picads-pip-cache'],root=dependencies,run=run,confirmed=True)
    assert result['status']=='PASS'
    assert any('rm -rf' in x[-1] and 'picads-librelane-pip' in x[-1] for x in calls)
    assert not any('~/.cache/pip' in x[-1] or 'docker image' in x[-1] for x in calls)
    assert (librelane/'wsl_distribution.txt').is_file()


def test_cli_configure_physical(tmp_path,capsys):
    root=tmp_path/'chip';init_project(root)
    result=main(['configure-physical',str(root),'--wsl-distribution','Ubuntu'])
    assert result==0
    assert json.loads(capsys.readouterr().out)['status']=='CONFIGURED_NOT_VERIFIED'
    assert yaml.safe_load((root/'chip.yaml').read_text())['physical']['enabled'] is True


def test_existing_or_unowned_kicad_never_uninstalled(tmp_path):
    root=tmp_path/'dep';kicad=root/'kicad';kicad.mkdir(parents=True)
    receipt=kicad/'picads_install_receipt.json'
    receipt.write_text(json.dumps({'package':'kicad','method':'found-existing'}))
    ids={entry['id'] for entry in ds.storage_inventory(root=root,include_wsl=False)['entries']}
    assert 'package:kicad-winget' not in ids
    with pytest.raises(ds.StorageSafetyError):
        ds.apply_storage_cleanup(['package:kicad-winget'],root=root,include_wsl=False,confirmed=True)
    assert receipt.is_file()


def test_kicad_winget_uninstaller_is_receipt_gated_and_uses_package_manager(tmp_path,monkeypatch):
    root=tmp_path/'dep';kicad=root/'kicad';kicad.mkdir(parents=True)
    receipt=kicad/'picads_install_receipt.json'
    receipt.write_text(json.dumps({'package':'kicad','method':'winget',
            'package_id':'KiCad.KiCad','registered_tools':{}}))
    called=[]
    def fake_run(args,**kwargs):
        called.append(args)
        return subprocess.CompletedProcess(args,0,'success','')
    monkeypatch.setattr(ds.shutil,'which',lambda x:'C:/Windows/winget.exe' if x=='winget' else None)
    inventory=ds.storage_inventory(root=root,include_wsl=False)
    assert 'package:kicad-winget' in {entry['id'] for entry in inventory['entries']}
    assert ds.apply_storage_cleanup(['package:kicad-winget'],root=root,include_wsl=False,
                                    confirmed=True,run=fake_run)['status']=='PASS'
    assert called[0][1:4]==['uninstall','--id','KiCad.KiCad']
    assert not receipt.exists()
    assert kicad.is_dir()
