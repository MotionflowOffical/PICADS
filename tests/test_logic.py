import pytest, json, random
from chipcompiler.gates import gate
from chipcompiler.generator import HardwareCompiler
from chipcompiler.diagnostics import IssueCollector,DiagnosticException
from chipcompiler.ir import DLS,Node
from chipcompiler.verification import verify
from chipcompiler.export import verilog

@pytest.mark.parametrize('op,values,expected',[
 ('AND',(0,None),0),('AND',(1,None),None),('OR',(1,None),1),('OR',(0,None),None),
 ('XOR',(1,1),0),('XOR',(0,None),None),('XNOR',(1,1),1),('NAND',(1,1),0),
 ('NOT',(0,),1),('MUX',(None,1,1),1),('MUX',(None,1,0),None),('MUX',(0,0,1),0)])
def test_primitive_truth(op,values,expected): assert gate(op,values)==expected

@pytest.mark.parametrize('width',range(1,9))
@pytest.mark.parametrize('operation,expr',[
 ('add','a + b'),('mul','a * b'),('sub','a - b'),
 ('and','a & b'),('or','a | b'),('xor','a ^ b'),
 ('lt','a < b'),('gt','a > b'),('ge','a >= b'),('le','a <= b'),
 ('eq','a == b'),('ne','a != b')])
def test_bitvector_operations(width,operation,expr):
    source=f'def calc(a: u{width}, b: u{width}) -> u{2*width+1}:\n    return {expr}\n'
    issues=IssueCollector();dls=HardwareCompiler(issues).compile_source(source)
    result=verify(source,dls,issues,exhaustive_limit=256,random_vectors=90)
    assert result.status in ('PASS_EXHAUSTIVE','PASS_SAMPLED'), (operation,width,result.failures,issues.as_dict())

@pytest.mark.parametrize('width', [3,5,13,24])
def test_prefix_or_ripple(width):
    src=f'def add(a: u{width}, b: u{width}) -> u{width+1}:\n    return a + b\n'
    gate_counts=[]
    for strategy in ('ripple','prefix','auto'):
        issues=IssueCollector();dls=HardwareCompiler(issues,{'architecture':{'adder':strategy}}).compile_source(src)
        assert verify(src,dls,issues,random_vectors=150).status.startswith('PASS')
        gate_counts.append(dls.stats()['primitive_gates'])
    assert all(c>0 for c in gate_counts)

def test_conditional_alu_exhaustive():
    source='def calculate(a:u4,b:u4,d:bool)->u8:\n    if d:\n        return a*b\n    return a+b\n'
    i=IssueCollector();d=HardwareCompiler(i).compile_source(source)
    result=verify(source,d,i)
    assert result.status=='PASS_EXHAUSTIVE' and result.vectors==512
    assert set(d.stats()['gate_types']) <= {'AND','OR','XOR','NOT','MUX','BUF','NAND','NOR','XNOR'}
    assert 'assign ' in verilog(d) and '+' not in '\n'.join(x for x in verilog(d).splitlines() if x.startswith('  assign'))

def test_generated_dls_reloaded(tmp_path):
    src='def circuit(a:u4,b:u4)->u5:\n    return a+b\n'
    d=HardwareCompiler().compile_source(src)
    p=tmp_path/'test.dls';d.save(p);new=DLS.load(p)
    assert new.to_dict()==d.to_dict()
    assert new.new_simulator().step({'a':15,'b':15})=={'result':30}

def test_mutated_gate_is_detected():
    src='def circuit(a:u4,b:u4)->u5:\n    return a+b\n'
    d=HardwareCompiler().compile_source(src)
    # Break a live output net rather than relying on altered high-level operation semantics.
    d.outputs['result']=['@0']*5
    issues=IssueCollector();report=verify(src,d,issues)
    assert report.status=='FAIL'
    assert any(x.code=='VERIFY.MISMATCH' and 'first_counterexample' in x.evidence for x in issues.issues)

def test_invalid_dls_is_rejected(tmp_path):
    d=DLS('x',{'a':1},{'result':['g1']},[Node('g1','AND',['a[0]','undefined'])])
    with pytest.raises(ValueError,match='undefined'):d.validate()

def test_unsupported_source_caught():
    issues=IssueCollector()
    with pytest.raises(DiagnosticException):HardwareCompiler(issues).compile_source('def calc(a:u4)->u4:\n    return open("secret.txt")\n')
    assert issues.errors[0].code=='SOURCE.CALL_UNSUPPORTED'

@pytest.mark.parametrize('expr',[ 'a > b','a < b','a == b','a != b','a <= b','a >= b','a+b','a*b'])
def test_signed_arithmetic(expr):
    source=f'def calc(a:s4,b:s4)->s8:\n    return {expr}\n'
    issues=IssueCollector();d=HardwareCompiler(issues).compile_source(source)
    result=verify(source,d,issues,exhaustive_limit=300)
    assert result.status=='PASS_EXHAUSTIVE', (expr,result.failures)

def test_register_cycles():
    src='def sample(a:u4)->u4:\n    return reg("stored",a,init=2)\n'
    d=HardwareCompiler().compile_source(src)
    sim=d.new_simulator()
    assert sim.step({'a':7})=={'result':2}
    assert sim.step({'a':4})=={'result':7}
    assert sim.step({'a':1})=={'result':4}
    issues=IssueCollector();report=verify(src,d,issues)
    assert report.status=='PASS_SAMPLED',report.failures

def test_helper_function():
    src='''def pair_sum(a:u4,b:u4)->u5:
    return a+b

def calculate(a:u4,b:u4)->u5:
    return pair_sum(a,b)
'''
    issues=IssueCollector();d=HardwareCompiler(issues).compile_source(src,top='calculate')
    assert verify(src,d,issues).status=='PASS_EXHAUSTIVE'


def test_bad_type_is_user_source_error():
    issues=IssueCollector()
    with pytest.raises(DiagnosticException):HardwareCompiler(issues).compile_source('def calc(a: float)->u8:\n return a\n')
    assert issues.errors[0].origin=='SOURCE' and issues.errors[0].code=='SOURCE.INVALID_TYPE'
