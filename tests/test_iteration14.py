"""v0.14: v1-scope freeze, LibreLane target preflight and physical provenance."""
from __future__ import annotations
import json
import shutil
import pytest
from pathlib import Path
from chipcompiler.physical_flow import (normalize_physical_settings, physical_preflight,
                                         make_physical_handoff, verify_handoff_inputs)
from chipcompiler.tools import write_librelane_config
from chipcompiler.pipeline import BuildSession
from chipcompiler.cli import init_project, main


def test_future_features_is_scope_control_document():
    text=(Path(__file__).parent.parent/'docs/FUTURE_FEATURES.md').read_text()
    assert 'v1.0' in text and 'AXI4' in text and 'GDSII' in text
    assert 'post-v1.0' in text


def test_physical_settings_mapped_to_librelane():
    cfg, converted=normalize_physical_settings({
        'enabled':True,'pdk':'sky130A','std_cell_library':'sky130_fd_sc_hd',
        'clock_period_ns':20,'core_utilization':35, 'placement_density':50,
        'die_area_um':[0,0,210.5,300],'timeout_s':1200,'dockerized':False,
    },True)
    assert converted=={'CLOCK_PERIOD':20.0,'CLOCK_PORT':'clk','FP_CORE_UTIL':35.0,
                       'PL_TARGET_DENSITY_PCT':50.0, 'DIE_AREA':[0.0,0.0,210.5,300.0],
                       'FP_SIZING':'absolute','STD_CELL_LIBRARY':'sky130_fd_sc_hd'}
    assert cfg['pdk']=='sky130A'


@pytest.mark.parametrize('config,clocked,match',[ 
    ({'enabled':True,'pdk':'../secret'},False,'PDK'),
    ({'enabled':True,'pdk':'sky130A','foo':'bar'},False,'UNKNOWN'),
    ({'enabled':True,'pdk':'sky130A'},True,'CLOCK_PERIOD'),
    ({'enabled':True,'clock_period_ns':True},False,'CLOCK_PERIOD'),
    ({'enabled':True,'clock_period_ns':float('nan')},False,'CLOCK_PERIOD'),
    ({'enabled':True,'core_utilization':91},False,'CORE_UTILIZATION'),
    ({'enabled':True,'die_area_um':[0,0,0,10]},False,'DIE_AREA'),
    ({'enabled':True,'die_area_um':[0,3,10]},False,'DIE_AREA'),
    ({'enabled':True,'placement_density':99},False,'PLACEMENT_DENSITY'),
    ({'enabled':'true'},False,'ENABLED'),
    ({'enabled':True,'timeout_s':10.5},False,'TIMEOUT'),
    ({'enabled':True,'pdk_root':''},False,'PDK_ROOT'),
])
def test_reject_invalid_physical_contract(config,clocked,match):
    with pytest.raises(ValueError,match=match):normalize_physical_settings(config,clocked)


def test_preflight_reports_real_constraints_and_missing_pdk_root(tmp_path,monkeypatch):
    monkeypatch.delenv('PDK_ROOT',raising=False)
    p=physical_preflight({'enabled':True,'pdk':'sky130A','pdk_root':str(tmp_path/'missing')},False,check_tools=False)
    assert p.status=='BLOCKED' and p.checks['pdk_root']['status']=='BLOCKED'
    root=tmp_path/'root';root.mkdir()
    p=physical_preflight({'enabled':True,'pdk':'sky130A','pdk_root':str(root)},False,check_tools=False)
    assert p.status=='READY_TO_ATTEMPT'
    assert any('not a PDK qualification' in s.lower() or 'not run synthesis' in s.lower() for s in p.notes)
    root.joinpath('sky130A').mkdir()
    p=physical_preflight({'enabled':True,'pdk':'sky130A','pdk_root':str(root)},False,check_tools=False)
    assert p.checks['pdk_root']['status']=='PASS'


def test_preflight_never_mistakes_installed_tool_for_actual_signoff(monkeypatch,tmp_path):
    import chipcompiler.dependencies as dep
    monkeypatch.setattr(dep,'tool_status',lambda name:{'available':True,'path':'/fake/'+name,'error':None})
    p=physical_preflight({'enabled':True,'pdk':'sky130A','pdk_root':str(tmp_path)},False)
    assert p.status=='READY_TO_ATTEMPT'
    assert p.as_dict()['status']=='READY_TO_ATTEMPT'
    assert p.checks['librelane']['path']=='/fake/librelane'


def test_librelane_config_rejects_overwriting_generated_top(tmp_path):
    f=tmp_path/'config.json'
    with pytest.raises(ValueError,match='override'):
        write_librelane_config('chip',None,None,f,extra={'DESIGN_NAME':'changed'})
    with pytest.raises(ValueError,match='override'):
        write_librelane_config('chip',None,None,f,extra={'VERILOG_FILES':['other.v']})
    config=write_librelane_config('chip','clk',10,f,extra={'FP_CORE_UTIL':35,'DIE_AREA':[0,0,100,100]})
    assert json.loads(f.read_text())==config
    assert config['VERILOG_FILES']==['dir::chip.v']


def test_provenance_hashes_detect_any_input_mutation(tmp_path):
    rtl=tmp_path/'chip.v';rtl.write_text('module chip; endmodule')
    cfg=tmp_path/'config.json';cfg.write_text('{}')
    record=make_physical_handoff(rtl,cfg,tmp_path/'handoff.json',pdk='sky130A',run_tag='test')
    assert verify_handoff_inputs(record)
    assert json.loads((tmp_path/'handoff.json').read_text())==record
    assert record['qualified_for_manufacturing'] is False
    rtl.write_text('module chAp; endmodule')
    assert not verify_handoff_inputs(record)
    rtl.write_text('module chip; endmodule')
    cfg.write_text('[]')
    assert not verify_handoff_inputs(record)


def test_cli_preflight_reports_missing_physical_settings(tmp_path,capsys):
    root=tmp_path/'chip';init_project(root)
    rc=main(['physical-preflight',str(root)])
    data=json.loads(capsys.readouterr().out)
    assert rc==2 and data['status']=='BLOCKED'
    assert data['checks']['enabled']['status']=='BLOCKED'
    assert (root/'build/latest/physical_preflight.json').exists()


def test_pipeline_preflight_blocks_invalid_pdk_without_running_flow(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    source=root/'chip.yaml';source.write_text(source.read_text().replace('enabled: false',
        'enabled: true\n  pdk: sky130A\n  pdk_root: /certainly/nonexistent/picads-pdk'))
    from chipcompiler import pipeline
    seen=[]
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kw):
        seen.append(stage)
        if stage=='yosys':(cwd/'synthesized.v').write_text('module calculate(); endmodule')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    result=BuildSession(root,'physical').run()
    assert result.status=='FAILED'
    assert seen==['yosys']
    assert any(item['code']=='PHYSICAL.PREFLIGHT_BLOCKED' for item in result.issues)
    assert result.stages['signoff']['status']=='BLOCKED'


def test_invalid_clocked_physical_config_cannot_fake_success(tmp_path,monkeypatch):
    root=tmp_path/'clocked'
    original=Path(__file__).parent.parent/'examples/clocked_hierarchy'
    shutil.copytree(original,root,ignore=shutil.ignore_patterns('build'))
    import yaml
    config=yaml.safe_load((root/'chip.yaml').read_text())
    config['physical']={'enabled':True,'pdk':'sky130A'}
    (root/'chip.yaml').write_text(yaml.safe_dump(config))
    from chipcompiler import pipeline
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kw):
        if stage=='yosys':(cwd/'synthesized.v').write_text('module accumulate_view(); endmodule')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    r=BuildSession(root,'physical').run()
    assert r.status=='FAILED'
    assert 'CLOCK_PERIOD' in r.stages['physical_preflight']['checks']['settings']['reason']


def test_pipeline_prepared_handoff_and_physical_constraints(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    config=root/'chip.yaml'
    config.write_text(config.read_text().replace('enabled: false','enabled: true\n  pdk: sky130A\n  core_utilization: 40\n  die_area_um: [0,0,120,100]'))
    from chipcompiler import pipeline
    seen=[]
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kw):
        seen.append((stage,argv))
        if stage=='yosys':(cwd/'synthesized.v').write_text('module calculate(); endmodule')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    report=BuildSession(root,'physical').run()
    assert [x[0] for x in seen]==['yosys','physical']
    build=root/'build/latest'
    cfg=json.loads((build/'config.json').read_text())
    assert cfg['FP_CORE_UTIL']==40 and cfg['DIE_AREA']==[0,0,120,100]
    assert cfg['VERILOG_FILES']==['dir::calculate.v']
    handoff=json.loads((build/'physical_handoff.json').read_text())
    assert verify_handoff_inputs(handoff)
    assert 'PHYSICAL.ARTIFACT_INVALID' in {v['code'] for v in report.issues}
    assert report.stages['signoff']['status']=='BLOCKED'


def test_physical_evidence_hashes_real_inputs_and_top(tmp_path):
    import struct
    from chipcompiler.physical import inspect_librelane
    from chipcompiler.physical_flow import artifact_hash
    def rec(t,d=0,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,t,d)+payload
    gds=(rec(0,2,b'\x02\x58')+rec(1,2,b'\0'*24)+rec(2,6,b'UNIT')+
         rec(5,2,b'\0'*24)+rec(6,6,b'first_chip')+rec(8)+rec(13,2,b'\0\x01')+
         rec(17)+rec(7)+rec(4))
    root=tmp_path/'run'/'final'
    (root/'gds').mkdir(parents=True)
    gdsfile=root/'gds'/'first_chip.gds';gdsfile.write_bytes(gds)
    ev=inspect_librelane(tmp_path/'run',expected_top='first_chip')
    assert ev.status=='LAYOUT_GENERATED'
    assert ev.checks['expected_top']['status']=='PASS'
    assert ev.artifacts['gds'][0]['sha256']==artifact_hash(gdsfile)
    assert ev.artifacts['missing_optional']
    failed=inspect_librelane(tmp_path/'run',expected_top='wrong_top')
    assert failed.status=='FAIL'
    assert failed.checks['expected_top']['status']=='FAIL'


def test_v1_acceptance_missing_tools_produces_reproducible_zip(tmp_path,monkeypatch):
    from chipcompiler import acceptance
    monkeypatch.setattr(acceptance,'resolve_tool',lambda n:None)
    monkeypatch.setattr(acceptance,'probe_tools',lambda:{})
    monkeypatch.setattr(acceptance,'selected_pdk_root',lambda p,r:None)
    summary=acceptance.run_acceptance(tmp_path/'v1_acceptance',gui=False)
    assert summary['overall']=='PARTIAL'
    assert summary['zip'].endswith('v1_acceptance.zip')
    assert summary['statuses']['source_to_dls_and_rtl']['status']=='PASS'
    assert summary['statuses']['native_rtl_equivalence']['status']=='UNAVAILABLE'
    assert summary['statuses']['native_yosys_synthesis']['status']=='UNAVAILABLE'
    assert summary['statuses']['real_placement_routing_gds']['status']=='UNAVAILABLE'
    assert summary['statuses']['foundry_signoff']['status']=='UNVERIFIED'
    assert summary['manufacturing_qualified'] is False
    import zipfile
    with zipfile.ZipFile(summary['zip']) as archive:
        assert 'summary.json' in archive.namelist()
        assert 'evidence/compile_report.json' in archive.namelist()
        assert 'evidence/physical_preflight.json' in archive.namelist()
        assert len(archive.namelist())<20  # excludes project sources, PDK, private designs


def test_first_physical_example_hardware_has_a_clock_and_verified_rtl(tmp_path):
    root=tmp_path/'chip';shutil.copytree(Path(__file__).parent.parent/'examples/first_physical_chip',root,
                   ignore=shutil.ignore_patterns('build'))
    session=BuildSession(root,'compile');out=session.run()
    assert out.status in ('SUCCESS','SUCCESS_WITH_WARNINGS')
    assert session.dls.requires_clock()
    assert out.stages['export']['status']=='PASS'
    assert out.stages['equivalence']['status'].startswith('PASS')
    assert (root/'build/latest/first_chip.v').is_file()


def test_physical_run_rejects_changed_inputs_even_when_tool_exits_zero(tmp_path,monkeypatch):
    root=tmp_path/'chip';init_project(root)
    cfg=root/'chip.yaml';cfg.write_text(cfg.read_text().replace('enabled: false',
        'enabled: true\n  pdk: sky130A'))
    from chipcompiler import pipeline
    def fake(argv,cwd,logs,issues,events,stage,timeout=600,**kw):
        if stage=='yosys':
            (cwd/'synthesized.v').write_text('module calculate(); endmodule')
        if stage=='physical':
            data=(cwd/'config.json')
            data.write_text(data.read_text()+' ')
        return {'status':'PASS','returncode':0}
    monkeypatch.setattr(pipeline,'run_external',fake)
    outcome=BuildSession(root,'physical').run()
    assert outcome.status=='FAILED'
    assert 'PHYSICAL.INPUTS_CHANGED' in {issue['code'] for issue in outcome.issues}
    assert outcome.stages['physical']['status']=='FAIL'
    assert outcome.stages['signoff']['status']=='BLOCKED'
