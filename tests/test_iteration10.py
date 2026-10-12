"""PICADS 1.0 registered EDA dependencies, PDK preflight and source-selected ALU."""
from __future__ import annotations
import json,os,subprocess,sys
from pathlib import Path
import pytest

from chipcompiler.dependencies import (register_tool,unregister_tool,tool_status,
    resolve_tool,probe_tools,settings_file,DependencyConfigurationError,dependency_environment,auto_detect_tool)
from chipcompiler.pdk import inspect_pdk,register_pdk,clear_pdk,pdk_status
from chipcompiler.tools import run_external,probe
from chipcompiler.diagnostics import IssueCollector,EventLog
from chipcompiler.source_binding import infer_bindings,bound_source_fabric
from chipcompiler.tagged import TaggedFabricConfig
from chipcompiler.tagged_verify import randomized_tagged_check
from chipcompiler.pipeline import BuildSession

@pytest.fixture
def registry(tmp_path,monkeypatch):
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'user_settings'))
    return tmp_path


def fake_app(path:Path,stdout='PICADS_TOOL_PROBE'):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('#!/bin/sh\necho '+stdout+'\n',encoding='utf-8')
    path.chmod(0o755)
    return path


def test_choose_application_folder_and_clear(registry):
    root=registry/'kicad_install'
    app=fake_app(root/'bin'/'kicad-cli')
    status=register_tool('kicad-cli',root,'folder')
    assert status['available'] and status['path']==str(app.resolve())
    assert status['source']=='registered' and status['kind']=='folder'
    assert read_registry_path(settings_file())['tools']['kicad-cli']['path']==str(root.resolve())
    assert resolve_tool('kicad-cli')==str(app.resolve())
    assert probe_tools()['kicad-cli']['available']
    app2=fake_app(registry/'different'/'kicad-cli','ALT')
    assert register_tool('kicad-cli',app2,'app')['path']==str(app2.resolve())
    assert unregister_tool('kicad-cli')['source'] in ('PATH','unavailable')
    assert 'kicad-cli' not in read_registry_path(settings_file())['tools']


def read_registry_path(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_registration_rejects_incompatible_paths_and_is_atomic(registry):
    missing=registry/'unknown'
    with pytest.raises(DependencyConfigurationError,match='not found'):
        register_tool('yosys',missing,'folder')
    assert not settings_file().exists()
    bad=fake_app(registry/'bin'/'klayout')
    with pytest.raises(DependencyConfigurationError,match='not found'):
        register_tool('yosys',bad,'app')
    good=fake_app(registry/'bin'/'yosys')
    register_tool('yosys',good)
    with pytest.raises(DependencyConfigurationError,match='not found'):
        register_tool('yosys',bad)
    assert tool_status('yosys')['path']==str(good.resolve())
    good.unlink()
    status=tool_status('yosys')
    assert not status['available'] and status['source']=='registered' and resolve_tool('yosys') is None


def test_invalid_registry_is_not_silently_ignored(registry):
    path=settings_file();path.parent.mkdir(parents=True)
    path.write_text('{broken')
    with pytest.raises(DependencyConfigurationError,match='Cannot read'):
        tool_status('yosys')
    assert path.read_text()=='{broken'


def test_external_runner_uses_registered_executable(registry):
    app=fake_app(registry/'my_install'/'bin'/'yosys')
    register_tool('yosys',app)
    issues=IssueCollector();events=EventLog(registry/'events.jsonl')
    result=run_external(['yosys','--version'],registry,registry,issues,events,'demo',timeout=4)
    assert result['status']=='PASS',result
    assert result['argv'][0]==str(app.resolve())
    assert 'PICADS_TOOL_PROBE' in result['stdout_tail']
    assert not issues.issues
    app.unlink()
    result2=run_external(['yosys','--version'],registry,registry,issues,events,'missing',timeout=4)
    assert result2['status']=='UNAVAILABLE'


def test_kicad_not_signoff_and_pdk_inventory(registry):
    root=registry/'custom-pdk'
    (root/'libs').mkdir(parents=True)
    (root/'libs'/'logic.lef').write_text('')
    (root/'libs'/'std.lib.gz').write_text('')
    (root/'checks').mkdir()
    (root/'checks'/'tech.lydrc').write_text('')
    assert inspect_pdk(root)['status']=='INVENTORIED'
    state=register_pdk(root)
    assert state['qualified_for_manufacturing'] is False
    assert state['drc_candidates']==['checks/tech.lydrc']
    assert pdk_status()['status']=='INVENTORIED'
    assert clear_pdk()['status']=='NOT_CONFIGURED'
    assert inspect_pdk(registry/'missing')['status']=='UNAVAILABLE'
    assert inspect_pdk(registry/'user_settings')['status']=='INCOMPLETE'


SRC='''def choose(a: u4, b: u4, multiply: bool) -> u4:
    if multiply:
        return a * b
    return a + b

def reverse(a: u4, b: u4, add: bool) -> u4:
    return a + b if add else a * b
'''
CLIENTS=[{'name':'chosen','function':'choose'},{'name':'reversed','function':'reverse'}]

@pytest.mark.parametrize('operator',['builtin','external'])
def test_dynamic_conditional_mcd_binding(operator):
    cfg=TaggedFabricConfig(operator=operator)
    bindings=infer_bindings(SRC,CLIENTS,cfg)
    assert bindings[0]['operation']=='SELECT'
    assert bindings[0]['true_opcode']==1
    assert bindings[1]['false_opcode']==1
    d=bound_source_fabric(SRC,CLIENTS,cfg,'DynamicBound')
    assert d.validate()
    assert set(['select_0','select_1'])<=set(d.inputs)
    assert any(node.op=='NOT' for node in d.nodes)
    for seed in (37,93,811):
        result=randomized_tagged_check(d,cfg,cycles=180,seed=seed)
        assert result['status']=='PASS',result


@pytest.mark.parametrize('source,reason',[
    (SRC.replace('multiply: bool','multiply: u1'), 'WIDTH'),
    (SRC.replace('if multiply:', 'if a:'), 'SELECTOR'),
    (SRC.replace('return a * b','return a - b',1), 'OPERATOR'),
    (SRC.replace('return a * b','print(a)\n        return a * b',1), 'BODY'),
])
def test_dynamic_binding_rejects_unsafe_source(source,reason):
    with pytest.raises(ValueError,match='MCD.BINDING_'+reason):
        infer_bindings(source,CLIENTS,TaggedFabricConfig())


def test_mcd_conditional_full_project(registry):
    base=Path(__file__).resolve().parents[1]/'examples'/'mcd_conditional_fabric'
    import shutil
    target=registry/'project';shutil.copytree(base,target)
    report=BuildSession(target).run()
    assert report.stages['generate']['status']=='PASS',report.as_dict()
    assert report.stages['protocol_check']['status']=='PASS',report.as_dict()
    assert report.stages['equivalence']['status']=='NOT_APPLICABLE'


def test_cli_dependency_and_pdk_commands(registry,capsys):
    from chipcompiler.cli import main
    p=fake_app(registry/'app'/'klayout')
    assert main(['dependencies','set','klayout',str(p)])==0
    assert main(['dependencies','list'])==0
    output=capsys.readouterr().out
    assert str(p.resolve()) in output
    assert main(['dependencies','clear','klayout'])==0
    assert main(['pdk','status'])==0


def test_registered_directories_prepend_child_path(registry):
    alpha=fake_app(registry/'aaa'/'bin'/'yosys')
    beta=fake_app(registry/'bbb'/'bin'/'z3')
    register_tool('yosys',alpha)
    register_tool('z3',beta)
    env=dependency_environment({'PATH':'/default/path','UNRELATED':'retained'})
    segments=env['PATH'].split(os.pathsep)
    assert str(alpha.parent.resolve()) in segments[:-1]
    assert str(beta.parent.resolve()) in segments[:-1]
    assert env['UNRELATED']=='retained'
    assert segments[-1]=='/default/path'


def test_registered_binary_child_can_spawn_related_tool(registry):
    app=fake_app(registry/'install'/'bin'/'yosys')
    helper=fake_app(registry/'install'/'bin'/'z3','HELPER_FOUND')
    app.write_text('#!/bin/sh\nz3 --version\n',encoding='utf-8')
    register_tool('yosys',app)
    register_tool('z3',helper)
    issues=IssueCollector();events=EventLog(registry/'events.jsonl')
    result=run_external(['yosys'],registry,registry,issues,events,'spawn',timeout=4)
    assert result['status']=='PASS',result
    assert 'HELPER_FOUND' in result['stdout_tail']


def test_autodetect_finds_versioned_windows_layout_and_preserves_manual(registry):
    root=registry/'Program Files'
    executable=fake_app(root/'KiCad'/'9.0'/'bin'/'kicad-cli')
    discovered=auto_detect_tool('kicad-cli',roots=[root])
    assert discovered['available']
    assert discovered['auto_detect_action']=='FOUND_IN_INSTALLATION'
    assert discovered['path']==str(executable.resolve())
    second=auto_detect_tool('kicad-cli',roots=[])
    assert second['auto_detect_action']=='PRESERVED_MANUAL_SELECTION'
    executable.unlink()
    missing=auto_detect_tool('kicad-cli',roots=[root])
    assert missing['source']=='registered' and not missing['available']
