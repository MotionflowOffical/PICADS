"""Regression tests for deferred signoff, immutable layout and KLayout layer loading."""
import json, struct, subprocess
from pathlib import Path
from types import SimpleNamespace
from chipcompiler.cli import init_project
from chipcompiler.pipeline import BuildSession
from chipcompiler import pipeline,klayout_layers


def _gds(top):
    def rec(t,d=0,data=b''):
        if len(data)%2:data+=b'\0'
        return struct.pack('>HBB',len(data)+4,t,d)+data
    return (rec(0,2,b'\x02\x58')+rec(1,2,b'\0'*24)+rec(2,6,b'PICADS')+
            rec(5,2,b'\0'*24)+rec(6,6,top.encode())+
            rec(8)+rec(13,2,b'\x00\x01')+rec(17)+rec(7)+rec(4))


def make_project(tmp_path):
    root=tmp_path/'demo';init_project(root)
    config=root/'chip.yaml';config.write_text(config.read_text().replace(
        'enabled: false','enabled: true\n  pdk: sky130A'))
    return root


def fake_flow(calls):
    def call(args,cwd,logs,issues,events,stage,timeout=600,**kwargs):
        calls.append((stage,list(args)))
        if stage=='yosys':
            (cwd/'synthesized.v').write_text('module calculate(); endmodule')
        if stage=='physical':
            assert args[-3:]==['--to','KLayout.StreamOut','config.json']
            tag=args[args.index('--run-tag')+1]
            dest=cwd/'runs'/tag/'final'/'gds';dest.mkdir(parents=True)
            (dest/'calculate.gds').write_bytes(_gds('calculate'))
        if stage=='layout_verification':
            assert args[-3:]==['--from','KLayout.Render','config.json']
        return {'status':'PASS','returncode':0}
    return call


def test_layout_mode_stops_before_checks_and_verification_reuses_gds(tmp_path,monkeypatch):
    root=make_project(tmp_path)
    calls=[];monkeypatch.setattr(pipeline,'run_external',fake_flow(calls))
    first=BuildSession(root,'layout').run()
    assert first.stages['physical']['status']=='PASS',first.as_dict()
    assert first.stages['equivalence']['status']=='DEFERRED'
    assert first.stages['signoff']['status']=='DEFERRED'
    original=Path(first.files['gds']);bytes_before=original.read_bytes()
    assert (root/'build/latest/layout_source_snapshot.py').is_file()
    second=BuildSession(root,'verify_layout').run()
    assert second.stages['layout_reuse']['status']=='PASS',second.as_dict()
    assert second.stages['equivalence']['status'] in ('PASS','PASS_SAMPLED','PASS_EXHAUSTIVE')
    assert [s for s,_ in calls]==['yosys','physical','layout_verification']
    assert original.read_bytes()==bytes_before
    assert (root/'build/latest/report.json').is_file()
    assert (root/'build/latest/layout_verification_report.json').is_file()
    assert not (root/'build/history').exists()


def test_verify_requires_a_layout(tmp_path):
    root=make_project(tmp_path)
    report=BuildSession(root,'verify_layout').run()
    assert report.stages['verification']['status']=='BLOCKED'
    assert 'VERIFY.NO_LAYOUT' in [i['code'] for i in report.issues]


def test_klayout_layer_file_detection(tmp_path,monkeypatch):
    project=tmp_path/'project'
    palette=project/'build/latest/klayout_layers.lyp'
    palette.parent.mkdir(parents=True)
    palette.write_text('<?xml version="1.0"?><layer-properties><properties/></layer-properties>')
    assert klayout_layers.acquire_lyp(project)==palette
    assert klayout_layers.klayout_open_argv('klayout.exe',tmp_path/'x.gds',palette=palette)==[
        'klayout.exe','-l',str(palette),str(tmp_path/'x.gds')]
    palette.write_text('not xml')
    monkeypatch.setattr(klayout_layers.shutil,'which',lambda x:None)
    assert klayout_layers.acquire_lyp(project)==None


def test_klayout_discovers_palette_in_wsl_without_modifying_gds(tmp_path,monkeypatch):
    monkeypatch.setattr(klayout_layers.shutil,'which',lambda name:'C:/Windows/System32/wsl.exe')
    calls=[]
    palette=b'<?xml version="1.0"?><layer-properties><properties><name>met1 - 68/20</name></properties></layer-properties>'
    def runner(args,**kwargs):
        calls.append(args)
        if args[-3:-1]==['sh','-c']:
            return subprocess.CompletedProcess(args,0,b'/home/test/.ciel/sky130A/sky130A.lyp\n',b'')
        if args[-2:]==['cat','/home/test/.ciel/sky130A/sky130A.lyp']:
            return subprocess.CompletedProcess(args,0,palette,b'')
        raise AssertionError(args)
    p=klayout_layers.acquire_lyp(tmp_path,pdk='sky130A',distribution='Ubuntu',runner=runner)
    assert p is not None and p.read_bytes()==palette
    assert p.name=='klayout_layers.lyp'
    assert calls[0][:4]==['wsl.exe','--distribution','Ubuntu','--exec']


def test_second_step_refuses_modified_rtl(tmp_path,monkeypatch):
    root=make_project(tmp_path)
    calls=[];monkeypatch.setattr(pipeline,'run_external',fake_flow(calls))
    first=BuildSession(root,'layout').run()
    assert first.stages['physical']['status']=='PASS'
    rtl=root/'build/latest/calculate.v';rtl.write_text(rtl.read_text()+'\n// tamper\n')
    second=BuildSession(root,'verify_layout').run()
    assert second.stages['verification']['status']=='BLOCKED'
    assert 'VERIFY.INPUT_CHANGED' in [i['code'] for i in second.issues]
    assert [stage for stage,_ in calls]==['yosys','physical']
