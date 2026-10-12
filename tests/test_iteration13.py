"""v0.13: expanded global arbitration, automatic operator choice and fail-closed cases."""
from __future__ import annotations
import json
import shutil
from pathlib import Path
import pytest
from chipcompiler.global_sharing import compile_global_source_processes, check_global_source_processes
from chipcompiler.shared_operators import SHARED_BINARY_OPS, resolve_shared_types
from chipcompiler.diagnostics import IssueCollector

CLIENTS = [{'name':'alpha','function':'compute'}, {'name':'beta','function':'compute'}]


@pytest.mark.parametrize('name,expr,expected', [
    ('SUB','a - b',7), ('AND','a & b',0), ('OR','a | b',15),
    ('XOR','a ^ b',15), ('EQ','a == b',0), ('NE','a != b',1),
    ('LT','a < b',0), ('LE','a <= b',0), ('GT','a > b',1), ('GE','a >= b',1),
    ('ADD','a + b',15), ('MUL','a * b',56),
])
def test_shared_operator_exhaustive_first_vectors(name,expr,expected):
    src=f'def compute(a: u4, b: u4) -> u8:\n    v: u8 = {expr}\n    return v\n'
    co={'schedule':{'global_shared_types':[name]}}
    issues=IssueCollector()
    d=compile_global_source_processes(src,CLIENTS,co,'Shared'+name,issues)
    assert d.metadata['schedule']['shared_physical_units']=={name:1}
    assert len([s for s in d.registers if s.startswith('rr_'+name.lower()+'_')])==2
    result=check_global_source_processes(src,d,issues,rounds=5,seed=1051)
    assert result['status']=='PASS',result
    assert 'arb_grant_'+name.lower()+'_alpha' in d.outputs
    assert d.validate()


def test_auto_selects_only_multi_client_ops():
    src='''def first(a:u5,b:u5)->u6:
    if a < b:
        v:u6=a+b
    else:
        v:u6=a-b
    return v

def second(a:u5,b:u5)->u6:
    if a < b:
        v:u6=a-b
    else:
        v:u6=a+b
    return v
'''
    clients=[{'name':'one','function':'first'},{'name':'two','function':'second'}]
    types=resolve_shared_types(src,clients,'auto')
    assert types==['ADD','SUB','LT']
    d=compile_global_source_processes(src,clients,{'schedule':{'global_shared_types':'auto'}},'AutoMixed')
    assert d.metadata['schedule']['operator_selection']=='auto'
    assert d.metadata['schedule']['global_shared_types']==types
    assert check_global_source_processes(src,d,IssueCollector(),rounds=12)['status']=='PASS'


def test_auto_single_source_instanced_twice():
    src='def compute(a:u4,b:u4)->u4:\n    return a ^ b\n'
    assert resolve_shared_types(src,CLIENTS,'auto')==['XOR']
    d=compile_global_source_processes(src,CLIENTS,{'schedule':{'global_shared_types':'auto'}},'AutoXor')
    assert check_global_source_processes(src,d,IssueCollector(),rounds=8)['status']=='PASS'


def test_auto_rejects_unshared_operators_without_inventing_units():
    src='''def one(a:u4,b:u4)->u4:
    return a-b

def two(a:u4,b:u4)->u4:
    return a^b
'''
    clients=[{'name':'a','function':'one'},{'name':'b','function':'two'}]
    with pytest.raises(ValueError,match='GLOBAL_AUTO_EMPTY'):
        compile_global_source_processes(src,clients,{'schedule':{'global_shared_types':'auto'}},'Empty')


def test_auto_rejects_invalid_declaration():
    src='def compute(a:u4,b:u4)->u4:\n    return a^b\n'
    for wrong in (None,[],['XOR','XOR'],['BAD'],['ADD',42],{}):
        with pytest.raises(ValueError,match='GLOBAL_SHARE_TYPES'):
            resolve_shared_types(src,CLIENTS,wrong)
    with pytest.raises(ValueError,match='PROCESS_FUNCTION'):
        resolve_shared_types(src,[{'name':'x','function':'unknown'}],'auto')


def test_mutated_new_shared_operator_is_detected():
    src='def compute(a:u4,b:u4)->u4:\n    return a ^ b\n'
    d=compile_global_source_processes(src,CLIENTS,{'schedule':{'global_shared_types':['XOR']}},'CorruptXor')
    assert check_global_source_processes(src,d,IssueCollector(),rounds=4)['status']=='PASS'
    node=next(n for n in d.nodes if n.name=='shared_xor_alpha_result_0')
    node.inputs=['@0']
    assert check_global_source_processes(src,d,IssueCollector(),rounds=64)['status']=='FAIL'


def test_auto_example_build(tmp_path):
    from chipcompiler.pipeline import BuildSession
    original=Path(__file__).resolve().parents[1]/'examples'/'global_auto_operators'
    target=tmp_path/'hardware'
    shutil.copytree(original,target,ignore=shutil.ignore_patterns('build'))
    report=BuildSession(target).run()
    assert report.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),report.as_dict()
    assert report.stages['equivalence']['status']=='PASS_SAMPLED'
    schedule=json.loads(Path(report.files['global_schedule']).read_text())
    assert schedule['operator_selection']=='auto'
    assert schedule['shared_physical_units']=={'ADD':1,'SUB':1,'LT':1}

SHARED_MEMORY_SOURCE='''def store(addr:u3,value:u8)->u8:
    mem_write(addr,value)
    result:u8=mem_read(addr)
    return result

def load(addr:u3)->u8:
    result:u8=mem_read(addr)
    return result
'''
MEM_CLIENTS=[{'name':'writer','function':'store'},{'name':'reader','function':'load'}]
MEM_CO={'schedule':{'global_shared_memory':True},'memory':{'depth':4,'data_width':8}}


def memory_design(source=SHARED_MEMORY_SOURCE, clients=MEM_CLIENTS, config=MEM_CO):
    return compile_global_source_processes(source,clients,config,'SharedSourceMemory')


def test_global_memory_one_bank_and_isolated_source_verification():
    d=memory_design()
    assert d.validate()
    assert d.metadata['schedule']['shared_physical_units']=={'MEMORY':1}
    assert sum(k.startswith('shared_mem_') and k.rsplit('_',1)[-1].isdigit() for k in d.registers)==4
    assert not any(k.startswith('p_writer__mem_') for k in d.registers)
    evidence=check_global_source_processes(SHARED_MEMORY_SOURCE,d,IssueCollector(),rounds=6)
    assert evidence['status']=='PASS',evidence
    assert evidence['write_grants']>=1 and evidence['read_grants']>=1
    assert evidence['concurrent_atomic_source_equivalence']=='NOT_PROVEN'


def test_global_shared_memory_cross_process_visibility():
    d=memory_design();s=d.new_simulator();inputs={k:0 for k in d.inputs}
    inputs['reset']=1;s.step(inputs);inputs['reset']=0
    # Write from the first source process, wait for completion.
    inputs.update(writer_addr=2,writer_value=191,writer_start=1)
    s.step(inputs);inputs['writer_start']=0
    for i in range(80):
        s.step(inputs)
        if s.step(inputs,clock=False)['writer_done']:break
    else:pytest.fail('writer did not finish')
    inputs.update(reader_addr=2,reader_start=1)
    s.step(inputs);inputs['reader_start']=0
    for i in range(80):
        s.step(inputs)
        response=s.step(inputs,clock=False)
        if response['reader_done']:
            assert response['reader_result']==191
            break
    else:pytest.fail('reader did not finish')
    assert s.register_snapshot()['SharedSourceMemory/r_shared_mem_2']==191


def test_shared_memory_detects_read_result_mutation():
    d=memory_design()
    assert check_global_source_processes(SHARED_MEMORY_SOURCE,d,IssueCollector(),rounds=3)['status']=='PASS'
    node=next(n for n in d.nodes if n.name=='shared_mem_reader_result_0')
    node.inputs=['@0']
    assert check_global_source_processes(SHARED_MEMORY_SOURCE,d,IssueCollector(),rounds=14)['status']=='FAIL'


def test_shared_memory_rejects_missing_technology_and_invalid_setting():
    with pytest.raises(ValueError,match='GLOBAL_MEMORY_SPEC'):
        memory_design(config={'schedule':{'global_shared_memory':True}})
    with pytest.raises(ValueError,match='GLOBAL_MEMORY_SETTING'):
        memory_design(config={'schedule':{'global_shared_memory':'true'},'memory':{'depth':4,'data_width':8}})


def test_shared_memory_plus_shared_alu():
    src='''def do_work(addr:u2,value:u5)->u6:
    mem_write(addr,value)
    current:u5=mem_read(addr)
    result:u6=current+value
    return result
'''
    config={'schedule':{'global_shared_memory':True,'global_shared_types':['ADD']},
            'memory':{'depth':4,'data_width':5}}
    clients=[{'name':'c0','function':'do_work'},{'name':'c1','function':'do_work'}]
    d=memory_design(source=src,clients=clients,config=config)
    assert d.metadata['schedule']['shared_physical_units']=={'ADD':1,'MEMORY':1}
    result=check_global_source_processes(src,d,IssueCollector(),rounds=3)
    assert result['status']=='PASS',result


def test_shared_memory_example_project(tmp_path):
    from chipcompiler.pipeline import BuildSession
    directory=tmp_path/'project'
    shutil.copytree(Path(__file__).resolve().parents[1]/'examples'/'global_shared_memory',directory,
                    ignore=shutil.ignore_patterns('build'))
    result=BuildSession(directory).run()
    assert result.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),result.as_dict()
    assert result.stages['equivalence']['status']=='PASS_PROTOCOL_AND_ISOLATED_SAMPLED'
    assert result.stages['equivalence']['concurrent_atomic_source_equivalence']=='NOT_PROVEN'
    schedule=json.loads(Path(result.files['global_schedule']).read_text())
    assert schedule['global_shared_memory'] is True


def test_shared_memory_formal_properties_generated_not_claimed_proven(tmp_path):
    from chipcompiler.formal import prepare_global_shared_formal
    d=memory_design()
    result=prepare_global_shared_formal(d,tmp_path,depth=16)
    assert result['status']=='GENERATED_UNVERIFIED'
    assert result['properties']>=3
    txt=(tmp_path/'properties.sv').read_text()
    assert 'assert(!(arb_grant_mem_writer && arb_grant_mem_reader));' in txt
    assert 'assert(!arb_grant_mem_writer || (arb_request_mem_writer && !reset));' in txt


def test_shared_memory_invalid_address_fault_and_no_side_effect():
    d=memory_design();sim=d.new_simulator()
    p={k:0 for k in d.inputs};p['reset']=1;sim.step(p);p['reset']=0
    p.update(writer_addr=7,writer_value=249,writer_start=1)
    sim.step(p);p['writer_start']=0
    for i in range(50):
        sim.step(p)
        v=sim.step(p,clock=False)
        if v['writer_done']:
            assert v['writer_fault']==1
            break
    else:pytest.fail('bad-address writer never finished')
    assert all(sim.register_snapshot()[f'SharedSourceMemory/r_shared_mem_{j}']==0 for j in range(4))


def test_shared_memory_two_writer_conflict_single_grant_and_reset():
    src='''def store(addr:u2, value:u8)->u8:
    mem_write(addr,value)
    out:u8=mem_read(addr)
    return out
'''
    d=memory_design(src,[{'name':'a','function':'store'},{'name':'b','function':'store'}])
    s=d.new_simulator();p={k:0 for k in d.inputs};p['reset']=1;s.step(p);p['reset']=0
    p.update(a_addr=1,b_addr=1,a_value=53,b_value=170,a_start=1,b_start=1)
    s.step(p);p['a_start']=p['b_start']=0
    last_write=None;served=[]
    for i in range(30):
        out=s.step(p,clock=False)
        assert out['arb_grant_mem_a']+out['arb_grant_mem_b']<=1
        for n in ('a','b'):
            if out[f'arb_grant_mem_{n}'] and out[f'arb_mem_write_{n}']:
                last_write=out[f'arb_mem_wdata_{n}'];served.append(n)
        s.step(p)
    assert served==['a','b']
    assert s.register_snapshot()['SharedSourceMemory/r_shared_mem_1']==last_write==170
    p['reset']=1;s.step(p);p['reset']=0
    assert s.register_snapshot()['SharedSourceMemory/r_shared_mem_1']==0
