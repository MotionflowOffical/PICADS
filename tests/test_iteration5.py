"""v0.5 clocked hierarchies and independently clocked submodule instances."""
from pathlib import Path
import pytest

from chipcompiler.generator import HardwareCompiler
from chipcompiler.diagnostics import IssueCollector,DiagnosticException
from chipcompiler.verification import verify
from chipcompiler.export import verilog
from chipcompiler.ir import DLS

TWO_CHILDREN = '''def delay(x:u4)->u4:
    return reg("q", x, init=0)

def top(a:u4,b:u4)->u5:
    left=delay(a)
    right=delay(b)
    return left+right
'''

NESTED_CLOCK = '''def delay(x:u4)->u4:
    return reg("q", x, init=0)

def middle(x:u4)->u5:
    return delay(x)+1

def top(a:u4,b:u4)->u6:
    return middle(a)+middle(b)
'''


def test_stateful_children_two_separate_states(tmp_path):
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(TWO_CHILDREN,top='top')
    assert not d.registers
    assert d.requires_clock()
    assert d.submodules['delay'].requires_clock()
    assert len(d.instances)==2
    v=verilog(d)
    assert 'module top(clk, a, b, result);' in v
    assert '.clk(clk)' in v
    assert v.count('delay u_')==2
    sim=d.new_simulator()
    assert sim.step({'a':3,'b':12})=={'result':0}
    assert sim.step({'a':8,'b':7})=={'result':15}
    assert sim.step({'a':1,'b':2})=={'result':15}
    assert sim.step({'a':0,'b':0})=={'result':3}
    result=verify(TWO_CHILDREN,d,IssueCollector(),cycles=128)
    assert result.status=='PASS_SAMPLED',result.failures
    f=tmp_path/'nested.dls'
    d.save(f)
    assert DLS.load(f).new_simulator().step({'a':3,'b':12})=={'result':0}


def test_clock_is_propagated_through_pure_wrappers():
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(NESTED_CLOCK,top='top')
    assert d.requires_clock()
    assert not d.registers
    assert not d.submodules['middle'].registers
    assert d.submodules['middle'].requires_clock()
    v=verilog(d)
    assert 'module middle(clk, x, result);' in v
    assert 'module top(clk, a, b, result);' in v
    assert v.count('.clk(clk)')==3 # top has two middle, middle has one delay
    result=verify(NESTED_CLOCK,d,IssueCollector(),cycles=128)
    assert result.status=='PASS_SAMPLED',result.failures


def test_unknown_values_and_nonclocked_peek_do_not_advance_child_state():
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(TWO_CHILDREN,top='top')
    sim=d.new_simulator()
    assert sim.step({'a':9,'b':2},clock=False)=={'result':0}
    assert sim.step({'a':9,'b':2},clock=False)=={'result':0}
    sim.step({'a':9,'b':2})
    assert sim.step({'a':7,'b':3},clock=False)=={'result':11}
    assert sim.step({'a':None,'b':3},clock=False)=={'result':11}
    assert sim.step({'a':7,'b':3})=={'result':11}
    assert sim.step({'a':0,'b':0},clock=False)=={'result':10}


def test_implicit_clock_collision_with_sequential_descendant_is_rejected():
    src='''def delay(x:u4)->u4:\n return reg("q",x,init=0)\ndef top(clk:u1)->u4:\n return delay(clk)\n'''
    with pytest.raises(DiagnosticException,match='MCD.CLOCK_PORT_COLLISION'):
        HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(src,top='top')


def test_clocked_mcd_named_submodule_and_project_build(tmp_path):
    from chipcompiler.cli import init_project
    from chipcompiler.pipeline import BuildSession
    root=tmp_path/'clocked_modules'
    init_project(root)
    (root/'circuit.py').write_text(TWO_CHILDREN)
    (root/'design.mcd').write_text('top: top\nmodules:\n  - name: DelayCell\n    function: delay\n')
    (root/'architecture.co').write_text('modules:\n  hierarchy: preserve\n  naming: mcd\n')
    result=BuildSession(root).run()
    assert result.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),result.issues
    assert result.stages['equivalence']['status']=='PASS_SAMPLED'
    rtl=Path(result.files['verilog']).read_text()
    assert 'module DelayCell(clk, x, result)' in rtl
    assert rtl.count('DelayCell u_')==2
    assert '.clk(clk)' in rtl
    d=DLS.load(Path(result.files['dls']))
    assert d.requires_clock()
    assert set(d.submodules)=={'DelayCell'}
    assert len(d.instances)==2
    # Cross-instance isolation is preserved after MCD renaming and disk roundtrip.
    sim=d.new_simulator()
    assert sim.step({'a':1,'b':9})=={'result':0}
    assert sim.step({'a':6,'b':5})=={'result':10}
    assert sim.step({'a':0,'b':0})=={'result':11}


@pytest.mark.parametrize('src', [
    '''def top(a:u4,d:bool)->u4:\n return reg("r",a) if d else a\n''',
    '''def delay(x:u4)->u4:\n return reg("q",x)\ndef top(a:u4,b:u4,d:bool)->u4:\n return delay(a) if d else delay(b)\n''',
    '''def delay(x:u4)->u4:\n return reg("q",x)\ndef wrapper(x:u4)->u4:\n return delay(x)\ndef top(a:u4,b:u4,d:bool)->u4:\n if d:\n  return wrapper(a)\n else:\n  return b\n''',
])
def test_unsafe_conditional_state_rejected_with_specific_diagnostic(src):
    with pytest.raises(DiagnosticException,match='SOURCE.CONDITIONAL_STATE') as exc:
        HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(src,top='top')
    assert exc.value.issue.origin=='SOURCE'
    assert 'conditional' in exc.value.issue.message
    assert exc.value.issue.remedy


def test_conditional_select_before_stateful_helper_is_legal():
    src='''def delay(x:u4)->u4:\n return reg("q",x)\ndef top(a:u4,b:u4,d:bool)->u4:\n return delay(a if d else b)\n'''
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(src,top='top')
    result=verify(src,d,IssueCollector(),cycles=100)
    assert result.status=='PASS_SAMPLED',result.failures


def test_independent_source_reference_register_scopes():
    from chipcompiler.reference import SourceInterpreter
    src='''def delay(x:u4)->u4:\n return reg("q",x)\ndef top(a:u4,b:u4)->u5:\n return delay(a)+delay(b)\n'''
    ref=SourceInterpreter(src,'top')
    assert ref.step({'a':1,'b':8})=={'result':0}
    assert ref.step({'a':3,'b':7})=={'result':9}
    assert ref.step({'a':0,'b':0})=={'result':10}
    assert len(ref.registers)==2


def test_pure_hierarchy_does_not_expose_unnecessary_clock():
    src='''def leaf(x:u4)->u4:\n return x ^ 1\ndef top(x:u4)->u4:\n return leaf(x)\n'''
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(src,top='top')
    assert not d.requires_clock()
    v=verilog(d)
    assert '.clk(clk)' not in v
    assert 'module top(x, result);' in v


def test_hierarchical_register_debug_and_vcd(tmp_path):
    from chipcompiler.waveform import export_vcd
    d=HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(TWO_CHILDREN,top='top')
    sim=d.new_simulator()
    start=sim.register_snapshot()
    assert len(start)==2
    assert set(start.values())=={0}
    assert all(name.startswith('top/u_') and name.endswith('/r_q') for name in start)
    sim.step({'a':4,'b':12})
    states=sim.register_snapshot()
    assert sorted(states.values())==[4,12]
    filename=tmp_path/'wave.vcd'
    report=export_vcd(d,[{'a':4,'b':12},{'a':7,'b':2}],filename)
    assert report['hierarchical_registers_exported']==2
    text=filename.read_text()
    assert 'state_top__u_000000__r_q' in text
    assert 'state_top__u_000001__r_q' in text
    assert 'NOT physical gate timing' in text


def test_waveform_does_not_hide_input_clock_name_or_collide(tmp_path):
    from chipcompiler.waveform import export_vcd
    d=HardwareCompiler().compile_source('def top(clk:u1)->u1:\n return clk\n',top='top')
    filename=tmp_path/'clock_data.vcd'
    export_vcd(d,[{'clk':1}],filename)
    vcd=filename.read_text()
    assert 'chipcompiler_cycle_clock' in vcd
    assert ' clk $end' in vcd

    # A colliding register name must fail instead of hiding an input value.
    d=HardwareCompiler().compile_source('def top(reg_q:u1)->u1:\n return reg("q",reg_q)\n',top='top')
    with pytest.raises(ValueError,match='VCD signal name collision'):
        export_vcd(d,[{'reg_q':1}],tmp_path/'collision.vcd')
    assert not (tmp_path/'collision.vcd').exists()


def test_short_circuit_stateful_call_rejected_not_silently_evaluated():
    src='''def delay(x:u1)->u1:\n return reg("q",x)\ndef top(x:u1,d:bool)->u1:\n return d and delay(x)\n'''
    with pytest.raises(DiagnosticException,match='SOURCE.SHORTCIRCUIT_STATE') as exc:
        HardwareCompiler(co={'modules':{'hierarchy':'preserve'}}).compile_source(src,top='top')
    assert 'short-circuit' in exc.value.issue.message
