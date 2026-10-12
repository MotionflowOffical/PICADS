"""PICADS v0.9.0 tagged concurrent service and restricted MCD binding tests."""
import copy,json,shutil
from pathlib import Path
import pytest
from chipcompiler.tagged import TaggedFabricConfig,tagged_fabric
from chipcompiler.tagged_verify import check_tagged_protocol,randomized_tagged_check
from chipcompiler.source_binding import infer_bindings,bound_source_fabric
from chipcompiler.pipeline import BuildSession
from chipcompiler.rtl_check import make_tagged_vectors,make_testbench
from chipcompiler.ir import DLS
from chipcompiler.export import export_verilog

SRC='''def add_unit(a: u4, b: u4) -> u4:
    return a + b

def mult_unit(a: u4, b: u4) -> u4:
    return a * b
'''
BIND=[{'name':'first','function':'add_unit'},{'name':'second','function':'mult_unit'}]

@pytest.mark.parametrize('operator',['builtin','external'])
@pytest.mark.parametrize('slots',[1,2,3])
def test_tagged_directed_and_random_oracle(operator,slots):
    cfg=TaggedFabricConfig(slots_per_client=slots,operator=operator)
    d=tagged_fabric(cfg)
    assert d.validate() is True
    assert d.requires_clock()
    verdict=check_tagged_protocol(d,cfg)
    assert verdict['status']=='PASS',verdict
    for seed in (17,927):
        result=randomized_tagged_check(d,cfg,cycles=85,seed=seed)
        assert result['status']=='PASS',result
        assert result['coverage']['multi_outstanding']
        assert result['coverage']['response_observed']


def test_tagged_response_mutation_is_caught():
    cfg=TaggedFabricConfig()
    d=tagged_fabric(cfg)
    d=copy.deepcopy(d)
    d.outputs['response_tag_0']=['@0']*cfg.tag_width
    assert d.validate()
    result=check_tagged_protocol(d,cfg)
    assert result['status']=='FAIL',result


def test_tagged_random_mutation_is_caught():
    cfg=TaggedFabricConfig()
    d=tagged_fabric(cfg)
    d=copy.deepcopy(d)
    d.outputs['response_data_0']=['@0']*cfg.width
    assert d.validate()
    result=randomized_tagged_check(d,cfg,cycles=80,seed=11)
    assert result['status']=='FAIL'
    assert result['replay_last_24']


def test_tagged_dls_roundtrip_rtl_vectors(tmp_path):
    cfg=TaggedFabricConfig()
    d=tagged_fabric(cfg)
    path=tmp_path/'tagged.dls';d.save(path)
    restored=DLS.load(path)
    assert restored.to_dict()==d.to_dict()
    rtl=tmp_path/'tagged.v';export_verilog(restored,rtl)
    verilog=rtl.read_text()
    assert 'module shared_resource_core' in verilog
    assert 'module tagged_resource_fabric' in verilog
    assert '.clk(clk)' in verilog
    assert 'response_tag_0' in verilog
    vectors=make_tagged_vectors(d,64)
    assert len(vectors)==64
    assert any(v['request_0'] for v in vectors)
    assert 'CCRTL_V1_END' in make_testbench(d,vectors)


def test_source_binding_and_rtl_vectors():
    cfg=TaggedFabricConfig()
    d=bound_source_fabric(SRC,BIND,cfg,'BoundTest')
    assert d.metadata['bindings'][0]['operation']=='ADD'
    assert d.metadata['bindings'][1]['operation']=='MUL'
    assert 'opcode_0' not in d.inputs
    assert randomized_tagged_check(d,cfg,cycles=120,seed=731)['status']=='PASS'
    assert len(make_tagged_vectors(d,64))==64


@pytest.mark.parametrize('source,binding,reason',[
    (SRC, [{'name':'first','function':'unknown'},BIND[1]],'FUNCTION'),
    (SRC, [{'name':'dup','function':'add_unit'},{'name':'dup','function':'mult_unit'}],'NAME'),
    (SRC.replace('a + b','a - b'),BIND,'OPERATOR'),
    (SRC.replace('a + b','a + a'),BIND,'OPERATOR'),
    (SRC.replace('return a + b','value = a\n    return value'),BIND,'BODY'),
    (SRC.replace('a: u4','a: u5',1),BIND,'WIDTH'),
])
def test_source_binding_rejects_unsupported(source,binding,reason):
    with pytest.raises(ValueError,match=f'MCD.BINDING_{reason}'):
        infer_bindings(source,binding,TaggedFabricConfig())


@pytest.mark.parametrize('cfg',[
    TaggedFabricConfig(clients=1),TaggedFabricConfig(clients=9),
    TaggedFabricConfig(clients=3,slots_per_client=3),
    TaggedFabricConfig(slots_per_client=0),TaggedFabricConfig(slots_per_client=5),
    TaggedFabricConfig(slots_per_client=4,tag_width=1),
    TaggedFabricConfig(tag_width=0),TaggedFabricConfig(width=17),
])
def test_tagged_rejects_invalid_configuration(cfg):
    with pytest.raises(ValueError,match='CO.'):
        tagged_fabric(cfg)


@pytest.mark.parametrize('example,expected_mode',[
    ('tagged_fabric','tagged_fabric'),('mcd_bound_fabric','bound_fabric')])
def test_project_build_and_evidence(tmp_path,example,expected_mode):
    src=Path(__file__).resolve().parents[1]/'examples'/example
    target=tmp_path/example;shutil.copytree(src,target,ignore=shutil.ignore_patterns('build'))
    result=BuildSession(target).run()
    assert result.status=='SUCCESS_WITH_WARNINGS',result.as_dict()
    assert result.stages['generate']['status']=='PASS'
    assert result.stages['protocol_check']['status']=='PASS'
    assert result.stages['equivalence']['status']=='NOT_APPLICABLE'
    d=DLS.load(target/'build'/'latest'/('TaggedFabric.dls' if example=='tagged_fabric' else 'BoundArithmeticFabric.dls'))
    assert d.metadata['schedule']['mode']==expected_mode
    evidence=json.loads((target/'build'/'latest'/'fabric_protocol.json').read_text())
    assert len(evidence['randomized_scoreboards'])==3
    assert all(e['status']=='PASS' for e in evidence['randomized_scoreboards'])


def test_invalid_bound_mcd_blocks_without_generator_crash(tmp_path):
    src=Path(__file__).resolve().parents[1]/'examples'/'mcd_bound_fabric'
    target=tmp_path/'project';shutil.copytree(src,target,ignore=shutil.ignore_patterns('build'))
    mcd=target/'design.mcd'
    mcd.write_text(mcd.read_text().replace('sum_word','nonexistent'))
    result=BuildSession(target).run()
    assert result.status=='FAILED'
    assert 'MCD.CONCURRENT_BINDING' in [i['code'] for i in result.issues]
    assert result.stages['generate']['status']=='BLOCKED'
    assert not [i for i in result.issues if i['code']=='INTERNAL.UNEXPECTED']

@pytest.mark.parametrize('operator',['builtin','external'])
@pytest.mark.parametrize('tagged',[False,True])
def test_external_memory_ready_valid_device(operator,tagged):
    from chipcompiler.concurrent import FabricConfig,concurrent_fabric
    from chipcompiler.memory_verify import check_external_memory
    if tagged:
        cfg=TaggedFabricConfig(2,2,4,4,4,operator,'external')
        d=tagged_fabric(cfg)
    else:
        cfg=FabricConfig(2,4,4,operator,'external')
        d=concurrent_fabric(cfg)
    assert d.validate()
    proof=check_external_memory(d,tagged)
    assert proof['status']=='PASS',proof
    assert proof['memory_requests']>=5
    assert proof['backpressured_cycles']>=1


@pytest.mark.parametrize('depth,width',[(1,2),(2,2),(4,4),(16,4)])
def test_external_memory_address_model(depth,width):
    from chipcompiler.memory_verify import check_external_memory
    config=TaggedFabricConfig(2,2,width,depth,2,'builtin','external')
    design=tagged_fabric(config)
    assert check_external_memory(design,True)['status']=='PASS'


def test_external_memory_mutation_detected():
    from chipcompiler.memory_verify import check_external_memory
    cfg=TaggedFabricConfig(2,2,4,4,4,'builtin','external')
    design=tagged_fabric(cfg)
    design=copy.deepcopy(design)
    design.outputs['memory_request_address']=['@0']*cfg.width
    assert design.validate()
    assert check_external_memory(design,True)['status']=='FAIL'


def test_external_memory_co_project(tmp_path):
    src=Path(__file__).resolve().parents[1]/'examples'/'tagged_fabric'
    target=tmp_path/'project';shutil.copytree(src,target,ignore=shutil.ignore_patterns('build'))
    path=target/'architecture.co'
    path.write_text(path.read_text()+'  memory_backend: external\n')
    result=BuildSession(target).run()
    assert result.status=='SUCCESS_WITH_WARNINGS',result.as_dict()
    assert result.stages['protocol_check']['status']=='PASS'
    assert 'memory_request_valid' in DLS.load(target/'build'/'latest'/'TaggedFabric.dls').outputs


def test_invalid_external_memory_backend_project(tmp_path):
    src=Path(__file__).resolve().parents[1]/'examples'/'tagged_fabric'
    target=tmp_path/'project';shutil.copytree(src,target,ignore=shutil.ignore_patterns('build'))
    path=target/'architecture.co'
    path.write_text(path.read_text()+'  memory_backend: unknown\n')
    result=BuildSession(target).run()
    assert result.status=='FAILED'
    assert 'CO.FABRIC_CONFIG' in [issue['code'] for issue in result.issues]
    assert result.stages['generate']['status']=='BLOCKED'


def test_formal_collateral_generation_not_claimed_as_proof(tmp_path):
    from chipcompiler.formal import prepare_tagged_formal
    d=tagged_fabric(TaggedFabricConfig())
    report=prepare_tagged_formal(d,tmp_path,depth=8)
    assert report['status']=='GENERATED_UNVERIFIED'
    assert '[engines]' in (tmp_path/'safety.sby').read_text()
    sv=(tmp_path/'properties.sv').read_text()
    assert '$past(response_tag_0)' in sv
    assert 'assume(reset)' in sv
    assert 'assert(!request_ready_0)' in sv
    with pytest.raises(ValueError,match='FORMAL.DEPTH'):
        prepare_tagged_formal(d,tmp_path,depth=1)


def test_diagnostics_output_filename_preserves_dotted_version():
    import inspect
    from chipcompiler import system_validation
    source=inspect.getsource(system_validation.run_validation)
    assert "output.with_name(output.name+'.zip')" in source
    assert str(Path('/tmp/PICADS_v0.9.0_diagnostics').with_name('PICADS_v0.9.0_diagnostics.zip')) == '/tmp/PICADS_v0.9.0_diagnostics.zip'
