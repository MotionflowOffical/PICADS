"""Physical Docker diagnostics must fail closed and expose real tool errors."""
import json
from types import SimpleNamespace
from chipcompiler import wsl_backend, physical_flow


def _fixture(tmp_path):
    p=tmp_path/'backend_smoke_passed.txt'
    p.write_text('LIBRELANE_SMOKE_TEST_PASS\n')
    (tmp_path/'backend_smoke_receipt.json').write_text(json.dumps({'status':'PASS','distro':'Ubuntu'}))


def test_live_docker_failure_reveals_original_error(tmp_path):
    _fixture(tmp_path)
    def run(args, **kwargs):
        if 'docker info' in args[-1]:
            return SimpleNamespace(returncode=1,stdout='',stderr='Cannot connect to the Docker daemon at unix:///var/run/docker.sock')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    got=wsl_backend.backend_status(root=tmp_path,live=True,run=run,which=lambda _: 'wsl.exe')
    assert got['status']=='UNAVAILABLE' and got['recorded_smoke_pass']
    d=got['checks']['docker']
    assert d['status']=='UNAVAILABLE' and d['returncode']==1
    assert 'Cannot connect' in d['stderr']
    assert 'Start Docker Desktop' in d['detail']
    assert d['command'][0]=='wsl.exe'


def test_missing_docker_command_is_not_treated_as_an_older_smoke_success(tmp_path):
    _fixture(tmp_path)
    def run(args, **kwargs):
        if 'docker info' in args[-1]:
            return SimpleNamespace(returncode=127,stdout='',stderr='bash: docker: command not found')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    got=wsl_backend.backend_status(root=tmp_path,live=True,run=run,which=lambda _: 'wsl.exe')
    assert 'WSL Integration' in got['checks']['docker']['detail']
    assert not got['available']


def test_preflight_propagates_docker_diagnostic(monkeypatch):
    monkeypatch.setattr(wsl_backend, 'backend_status',lambda *args,**kwargs: {
       'status':'UNAVAILABLE','recorded_smoke_pass':True,'distribution':'Ubuntu',
       'detail':'Something failed','checks':{
          'yosys': {'status':'PASS','detail':''},'librelane': {'status':'PASS','detail':''},
          'docker':{'status':'UNAVAILABLE','detail':'Daemon not running','returncode':1,
                    'stdout':'','stderr':'Cannot connect','command':['wsl.exe','--exec','docker','info']}
       }})
    r=physical_flow.physical_preflight({'enabled':True,'pdk':'sky130A'},False,
                                        execution='wsl',wsl_distribution='Ubuntu')
    d=r.checks['docker_wsl']
    assert r.status=='PARTIAL'
    assert d['reason']=='Daemon not running'
    assert d['stderr']=='Cannot connect'
    assert d['returncode']==1
    assert d['command'][0]=='wsl.exe'


def test_succeeded_docker_probe_records_server_version(tmp_path):
    _fixture(tmp_path)
    def run(args, **kwargs):
        return SimpleNamespace(returncode=0,stdout='29.8.2\n' if 'docker info' in args[-1] else '',stderr='')
    got=wsl_backend.backend_status(root=tmp_path,live=True,run=run,which=lambda _: 'wsl.exe')
    assert got['status']=='READY'
    assert got['checks']['docker']['stdout']=='29.8.2'
