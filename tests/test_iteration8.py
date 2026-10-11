"""Gate-level concurrent transaction fabric and truthful integration diagnostics."""
import copy,json
from pathlib import Path
import pytest
from chipcompiler.concurrent import FabricConfig,concurrent_fabric
from chipcompiler.fabric_verify import check_fabric_protocol,randomized_fabric_check
from chipcompiler.pipeline import BuildSession
from chipcompiler.ir import DLS
from chipcompiler.export import export_verilog
from chipcompiler.rtl_check import make_fabric_vectors,make_testbench

@pytest.mark.parametrize('operator',('builtin','external'))
@pytest.mark.parametrize('clients', (2,3,4))
def test_protocol_and_random_oracle(operator,clients):
    c=FabricConfig(clients,4,4,operator)
    d=concurrent_fabric(c)
    checked=check_fabric_protocol(d,c)
    assert checked['status']=='PASS',checked
    for seed in (8291,29471):
        verdict=randomized_fabric_check(d,c,cycles=160,seed=seed)
        assert verdict['status']=='PASS',verdict
    assert all(n.op in ('AND','OR','XOR','NOT','MUX','BUF','NAND','NOR','XNOR') for n in d.nodes)

@pytest.mark.parametrize('operator',('builtin','external'))
def test_roundtrip_structural_and_simulator(operator,tmp_path):
    d=concurrent_fabric(FabricConfig(3,4,4,operator))
    path=tmp_path/'fabric.dls';d.save(path)
    restored=DLS.load(path)
    assert restored.to_dict()==d.to_dict()
    dest=tmp_path/'fabric.v';export_verilog(d,dest)
    rtl=dest.read_text()
    assert 'module concurrent_fabric' in rtl
    assert 'always @(posedge clk)' in rtl
    assert 'operator_request_valid' in rtl
    assert 'response_valid_0' in rtl
    assert restored.new_simulator().step({k:0 for k in d.inputs},clock=False)==d.new_simulator().step({k:0 for k in d.inputs},clock=False)

@pytest.mark.parametrize('bad',[
    FabricConfig(1,4,4),FabricConfig(9,4,4),FabricConfig(2,0,4),
    FabricConfig(2,17,4),FabricConfig(2,4,0),FabricConfig(2,4,33),
    FabricConfig(2,4,4,'made_up')])
def test_bad_config_is_rejected(bad):
    with pytest.raises(ValueError,match='CO.FABRIC_'):
        concurrent_fabric(bad)

@pytest.mark.parametrize('operator',('builtin','external'))
def test_mutation_detects_corrupt_response(operator):
    c=FabricConfig(3,4,4,operator)
    d=concurrent_fabric(c)
    assert check_fabric_protocol(d,c)['status']=='PASS'
    d=copy.deepcopy(d)
    d.outputs['response_data_0']=['@0']*4
    d.validate()
    checked=check_fabric_protocol(d,c)
    assert checked['status']=='FAIL'
    assert checked['scenario']
    assert checked['replay_last_24']

@pytest.mark.parametrize('operator',('builtin','external'))
def test_fabric_rtl_vectors(operator):
    d=concurrent_fabric(FabricConfig(3,4,4,operator))
    vectors=make_fabric_vectors(d,128)
    assert len(vectors)==128
    assert any(v['reset'] for v in vectors)
    assert any(v['stall'] for v in vectors)
    assert any(v['request_0'] for v in vectors)
    bench=make_testbench(d,vectors)
    assert 'cc_testbench' in bench
    assert 'CCRTL_V1_END' in bench


def test_compile_project_writes_evidence(tmp_path):
    import shutil
    source=Path(__file__).resolve().parents[1]/'examples'/'concurrent_fabric'
    project=tmp_path/'fabric';shutil.copytree(source,project,ignore=shutil.ignore_patterns('build'))
    result=BuildSession(project).run()
    assert result.status=='SUCCESS_WITH_WARNINGS',result.as_dict()
    assert result.stages['protocol_check']['status']=='PASS'
    assert result.stages['equivalence']['status']=='NOT_APPLICABLE'
    obj=json.loads((project/'build'/'latest'/'fabric_protocol.json').read_text())
    assert len(obj['randomized_scoreboards'])==3
    assert all(x['status']=='PASS' for x in obj['randomized_scoreboards'])
    assert (project/'build'/'latest'/'SharedFabric.v').stat().st_size>0

@pytest.mark.parametrize('invalid,bad_code',[
    ('schedule:\n  mode: concurrent_fabric\nfabric:\n  clients: 99\n','CO.FABRIC_CONFIG'),
    ('schedule:\n  mode: concurrent_fabric\nfabric:\n  clients: 2\n  impossible: 1\n','CO.FABRIC_UNKNOWN'),
    ('schedule:\n  mode: concurrent_fabric\nfabric:\n  clients: 2\n  width: 4\n  depth: 4\n  operator: other\n','CO.FABRIC_CONFIG'),
])
def test_config_error_is_origin_co_not_generator(tmp_path,invalid,bad_code):
    import shutil
    source=Path(__file__).resolve().parents[1]/'examples'/'concurrent_fabric'
    project=tmp_path/'fabric';shutil.copytree(source,project,ignore=shutil.ignore_patterns('build'))
    (project/'architecture.co').write_text(invalid)
    result=BuildSession(project).run()
    assert result.status=='FAILED'
    assert bad_code in [x['code'] for x in result.issues]
    assert result.stages['generate']['status']=='BLOCKED'
    assert not [x for x in result.issues if x['code']=='INTERNAL.UNEXPECTED']


def test_runner_stdlib_writes_zip_and_refuses_fake_success(tmp_path,monkeypatch):
    from chipcompiler.system_validation import run_validation
    from chipcompiler import system_validation
    def fake_run(argv,cwd,log,timeout=180,env=None):
        log.parent.mkdir(parents=True,exist_ok=True);log.write_text('mock not executed')
        return {'status':'PASS','log':log.name,'exit_code':0}
    # Test suite itself must not recursively start another pytest run.
    monkeypatch.setattr(system_validation,'_run',fake_run)
    import tempfile
    original=tempfile.TemporaryDirectory
    # Keep actual generated project tests in temp directories; no GUI side effects.
    target=tmp_path/'diag'
    result=run_validation(target,False)
    assert (tmp_path/'diag.zip').exists()
    assert json.loads((target/'summary.json').read_text())['statuses']['physical_flow']['status']=='NOT_REQUESTED'
    assert result['statuses']['dls_fabric_builtin']['status']=='PASS'
    assert result['statuses']['dls_fabric_external']['status']=='PASS'
    assert result['overall']!='PASS'
