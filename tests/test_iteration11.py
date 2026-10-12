"""PICADS v0.11: AXI4-Lite gate-level master and tagged fabric validation."""
import copy, json, subprocess,sys
from pathlib import Path
import pytest
from chipcompiler.axi_lite import AXILiteConfig,axi_lite_master,axi_tagged_fabric
from chipcompiler.axi_verify import check_axi_lite_protocol,randomized_axi_lite_check
from chipcompiler.tagged import TaggedFabricConfig
from chipcompiler.ir import DLS,DLSSimulator
from chipcompiler.export import export_verilog
from chipcompiler.pipeline import BuildSession

@pytest.mark.parametrize('width,address',[ (4,4),(8,6),(12,8),(16,16) ])
def test_axi_master_configurations(width,address,tmp_path):
    d=axi_lite_master(AXILiteConfig(width,address))
    d.validate();p=tmp_path/'axi.dls';d.save(p)
    assert DLS.load(p).to_dict()==d.to_dict()
    assert len(d.outputs['axi_awaddr'])==32
    assert len(d.outputs['axi_wdata'])==32
    assert d.requires_clock()
    rtl=tmp_path/'axi.v';export_verilog(d,rtl)
    content=rtl.read_text()
    assert 'axi_awaddr' in content and 'posedge clk' in content
    assert check_axi_lite_protocol(d)['status']=='PASS'
    assert randomized_axi_lite_check(d,seed=103,transactions=8)['status']=='PASS'

@pytest.mark.parametrize('operator',['builtin','external'])
def test_tagged_axi_protocol_and_random_slave(operator,tmp_path):
    cfg=TaggedFabricConfig(2,2,4,8,4,operator,'external')
    d=axi_tagged_fabric(cfg,'TaggedAXI')
    assert d.validate();assert 'axi_awvalid' in d.outputs
    assert 'memory_request_ready' not in d.inputs
    assert len(d.instances)==1
    assert d.requires_clock()
    d.save(tmp_path/'fabric.dls')
    assert DLS.load(tmp_path/'fabric.dls').validate()
    export_verilog(d,tmp_path/'tagged.v')
    for seed in (103,1291,9019):
        result=randomized_axi_lite_check(d,True,seed=seed)
        assert result['status']=='PASS',result
    result=check_axi_lite_protocol(d,True)
    assert result['status']=='PASS',result

@pytest.mark.parametrize('width,address,error',[ (0,4,'AXI.DATA_WIDTH'),(17,4,'AXI.DATA_WIDTH'),
    (4,0,'AXI.ADDRESS_WIDTH'),(4,17,'AXI.ADDRESS_WIDTH') ])
def test_axi_rejects_invalid_width(width,address,error):
    with pytest.raises(ValueError,match=error):axi_lite_master(AXILiteConfig(width,address))

def test_axi_requires_external_memory_backend():
    with pytest.raises(ValueError,match='AXI.FABRIC_MEMORY'):
        axi_tagged_fabric(TaggedFabricConfig(memory_backend='builtin'))

def test_mutated_axi_write_strobe_is_detected():
    d=axi_lite_master()
    broken=copy.deepcopy(d);broken.outputs['axi_wstrb']=['@0']*4
    broken.validate()
    verdict=check_axi_lite_protocol(broken)
    assert verdict['status']=='FAIL'
    assert 'strobe' in verdict['reason'].lower()
    assert verdict['counterexample']

def test_mutated_read_payload_is_detected():
    d=axi_lite_master()
    broken=copy.deepcopy(d);broken.outputs['memory_response_data']=['@0']*4
    broken.validate()
    verdict=randomized_axi_lite_check(broken,seed=129,transactions=15)
    assert verdict['status']=='FAIL',verdict
    assert 'response mismatch' in verdict['reason']


def test_axi_project_build(tmp_path):
    import shutil
    base=Path(__file__).resolve().parents[1]/'examples'/'axi_lite_fabric'
    dest=tmp_path/'axi';shutil.copytree(base,dest,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    report=BuildSession(dest).run()
    assert report.stages['generate']['status']=='PASS',report.as_dict()
    assert report.stages['protocol_check']['status']=='PASS',report.as_dict()
    assert report.stages['export']['status']=='PASS',report.as_dict()
    assert report.stages['equivalence']['status']=='NOT_APPLICABLE'
    protocol=json.loads((dest/'build'/'latest'/'fabric_protocol.json').read_text())
    assert len(protocol['randomized_scoreboards'])==3
    assert all(x['status']=='PASS' for x in protocol['randomized_scoreboards'])

@pytest.mark.parametrize('replacement',[ 'memory_backend: builtin','memory_backend: invalid' ])
def test_axi_project_configuration_errors_block_generation(tmp_path,replacement):
    import shutil
    base=Path(__file__).resolve().parents[1]/'examples'/'axi_lite_fabric'
    dest=tmp_path/'axi';shutil.copytree(base,dest,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    p=dest/'architecture.co';p.write_text(p.read_text().replace('memory_backend: external',replacement))
    report=BuildSession(dest).run()
    assert report.stages['generate']['status']=='BLOCKED'
    assert 'CO.AXI_MEMORY_BACKEND' in [i["code"] for i in report.issues] or 'CO.FABRIC_CONFIG' in [i["code"] for i in report.issues]


def test_axi_formal_harness_is_safety_only(tmp_path):
    from chipcompiler.formal import prepare_axi_lite_formal
    d=axi_tagged_fabric(TaggedFabricConfig(memory_backend='external'))
    info=prepare_axi_lite_formal(d,tmp_path,depth=14)
    assert info['status']=='GENERATED_UNVERIFIED'
    assert 'assert(axi_awaddr == $past(axi_awaddr))' in (tmp_path/'properties.sv').read_text()
    assert 'depth 14' in (tmp_path/'safety.sby').read_text()
    with pytest.raises(ValueError,match='FORMAL.AXI_DEPTH'):
        prepare_axi_lite_formal(d,tmp_path,depth=2)

PROCESS_SOURCE='''def branch(a: u4, b: u4, choose: bool) -> u8:
    if choose:
        result: u8 = a * b
    else:
        result: u8 = a + b
    return result

def repeated(a: u4, b: u4) -> u8:
    result: u8 = a + b
    result = result + a
    return result
'''


def test_parallel_source_fsm_generation_and_state_isolation(tmp_path):
    from chipcompiler.processes import compile_source_processes,check_source_processes
    from chipcompiler.diagnostics import IssueCollector
    clients=[{'name':'alpha','function':'branch'}, {'name':'beta','function':'branch'},
             {'name':'gamma','function':'repeated'}]
    issues=IssueCollector()
    design=compile_source_processes(PROCESS_SOURCE,clients,{'schedule':{'latencies':{'MUL':3}}},
                                   'ParallelSource',issues)
    assert design.validate();assert len(design.instances)==3
    assert len(design.submodules)==2  # repeated function uses one definition with independent instances
    assert design.metadata['schedule']['resource_sharing_across_processes'] is False
    assert design.requires_clock()
    assert 'alpha_start' in design.inputs and 'beta_start' in design.inputs
    assert 'alpha_result' in design.outputs and 'beta_result' in design.outputs
    evidence=check_source_processes(PROCESS_SOURCE,design,issues,random_vectors=7)
    assert evidence['status']=='PASS',evidence
    design.save(tmp_path/'parallel.dls')
    assert DLS.load(tmp_path/'parallel.dls').validate()
    export_verilog(design,tmp_path/'parallel.v')
    assert (tmp_path/'parallel.v').read_text().count('module branch')==1


def test_parallel_fsm_memory_is_private():
    from chipcompiler.processes import compile_source_processes,check_source_processes
    from chipcompiler.diagnostics import IssueCollector
    source='''def local_store(addr: u4, value: u4) -> u4:
    mem_write(addr, value)
    return mem_read(addr)
'''
    cfg={'memory':{'depth':4,'data_width':4}}
    d=compile_source_processes(source,[{'name':'left','function':'local_store'},
                                      {'name':'right','function':'local_store'}],cfg,'RamParallel')
    evidence=check_source_processes(source,d,IssueCollector(),random_vectors=5)
    assert evidence['status']=='PASS',evidence
    # Independent instance RAMs are maintained beneath the same DLS module definition.
    sim=d.new_simulator()
    p={key:0 for key in d.inputs}
    p['reset']=1;sim.step(p)
    p.update({'reset':0,'left_start':1,'right_start':1,
              'left_addr':1,'right_addr':1,'left_value':7,'right_value':12})
    sim.step(p)
    p['left_start']=p['right_start']=0
    final=None
    for _ in range(40):
        out=sim.step(p)
        if out['left_done'] and out['right_done']:
            final=out;break
    assert final and final['left_result']==7 and final['right_result']==12


def test_parallel_process_project_build(tmp_path):
    import shutil
    base=Path(__file__).resolve().parents[1]/'examples'/'source_processes'
    dest=tmp_path/'demo';shutil.copytree(base,dest,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    report=BuildSession(dest).run()
    assert report.stages['generate']['status']=='PASS',report.as_dict()
    assert report.stages['equivalence']['status']=='PASS_SAMPLED',report.as_dict()
    assert report.stages['export']['status']=='PASS',report.as_dict()
    ev=json.loads((dest/'build'/'latest'/'process_verification.json').read_text())
    assert ev['status']=='PASS' and ev['concurrent_processes']==3

@pytest.mark.parametrize('bad',[[],[{'name':'x','function':'does_not_exist'},{'name':'y','function':'branch'}],
    [{'name':'x','function':'branch'},{'name':'x','function':'repeated'}]])
def test_parallel_rejects_missing_unsafe_bindings(bad):
    from chipcompiler.processes import compile_source_processes
    with pytest.raises(ValueError,match='MCD.PROCESS'):
        compile_source_processes(PROCESS_SOURCE,bad,name='ParallelBad')


def test_one_command_validator_reports_new_hardware_stages(tmp_path,monkeypatch):
    from chipcompiler import system_validation
    def disabled_external_execution(argv,cwd,log,timeout=180,env=None):
        log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text('NOT_EXECUTED_IN_UNIT_TEST\n',encoding='utf-8')
        return {'status':'NOT_APPLICABLE','log':log.name,
                'reason':'Tool process intentionally not executed by validator-unit test'}
    monkeypatch.setattr(system_validation,'_run',disabled_external_execution)
    result=system_validation.run_validation(tmp_path/'validation',False)
    status=result['statuses']
    assert status['dls_axi_lite']['status']=='PASS',status.get('dls_axi_lite')
    assert status['dls_source_processes']['status']=='PASS',status.get('dls_source_processes')
    assert status['axi_formal_collateral']['status']=='NOT_APPLICABLE'
    assert status['axi_formal_safety_bmc']['status']=='UNAVAILABLE'
    assert (tmp_path/'validation.zip').exists()
    assert result['overall']=='PARTIAL'
