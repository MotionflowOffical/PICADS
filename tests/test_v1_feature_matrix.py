"""V1 capability acceptance, not an archive of historical implementation tests.

Each case checks an actual v1 user-facing contract with an isolated project.
Native EDA/Qt tests are handled by the feature runner and MUST remain explicit
UNAVAILABLE when their tools are missing (not silently mocked into success).
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from chipcompiler.dependencies import register_tool, tool_status, unregister_tool, read_settings
from chipcompiler.ir import DLS
from chipcompiler.pipeline import BuildSession
from chipcompiler.physical_flow import physical_preflight
from chipcompiler.feature_validation import _package_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'


def fresh_project(tmp_path, name):
    target = tmp_path / name
    shutil.copytree(EXAMPLES / name, target,
                    ignore=shutil.ignore_patterns('build', '.chipcompiler', '.pytest_cache'))
    return target


@pytest.mark.parametrize('example,required', [
    ('alu_slice_component', {'dls','verilog','equivalence'}),
    ('first_physical_chip', {'dls','verilog','equivalence'}),
    ('hierarchical_modules', {'dls','verilog','equivalence'}),
    ('explicit_network', {'dls','verilog','network_connections'}),
    ('transactional_controller', {'dls','verilog','co_schedule'}),
    ('transactional_memory', {'dls','verilog','co_schedule'}),
    ('c_arithmetic', {'dls','verilog','normalized_source'}),
    ('global_auto_operators', {'dls','verilog','global_schedule'}),
    ('global_shared_memory', {'dls','verilog','global_schedule'}),
])
def test_v1_compile_and_export_supported_hardware_families(tmp_path, example, required):
    """User-visible project import -> compiler -> executable hardware -> RTL."""
    project = fresh_project(tmp_path, example)
    report = BuildSession(project, 'compile').run()
    assert report.status in ('SUCCESS', 'SUCCESS_WITH_WARNINGS'), report.as_dict()
    for artifact in required:
        assert artifact in report.files, (example, artifact, report.as_dict())
        assert Path(report.files[artifact]).is_file(), (example, artifact)
    assert report.stages['equivalence']['status'].startswith('PASS'), report.as_dict()
    dls = DLS.load(report.files['dls'])
    assert dls.stats()['primitive_gates'] + dls.stats()['hierarchical_instances'] > 0
    rtl = Path(report.files['verilog']).read_text(encoding='utf-8')
    assert 'module ' in rtl and 'endmodule' in rtl
    assert not any(issue['code'].startswith('INTERNAL.') for issue in report.issues)


def alu_oracle(a, b, op):
    return (a + b) if op == 0 else ((a-b) & 15) if op == 1 else (a & b) if op == 2 else (a ^ b)


def test_v1_exhaustive_alu_semantics_from_independent_oracle(tmp_path):
    report = BuildSession(fresh_project(tmp_path, 'alu_slice_component'), 'compile').run()
    assert report.stages['equivalence']['status'] == 'PASS_EXHAUSTIVE'
    dls = DLS.load(report.files['dls'])
    simulator = dls.new_simulator()
    checked = 0
    for a, b, op in itertools.product(range(16), range(16), range(4)):
        output = simulator.step({'a': a, 'b': b, 'op': op})
        assert output == {'result': alu_oracle(a, b, op)}, (a, b, op, output)
        checked += 1
    assert checked == 1024


def test_v1_output_mutation_is_observable(tmp_path):
    report = BuildSession(fresh_project(tmp_path, 'alu_slice_component'), 'compile').run()
    dls = DLS.load(report.files['dls'])
    dls.outputs['result'][0] = '@0'
    assert dls.new_simulator().step({'a': 1, 'b': 0, 'op': 0}) != {'result': 1}


@pytest.mark.parametrize('bad_source,expected', [
    ('def alu_slice(\n', 'SOURCE.SYNTAX'),
    ('def alu_slice(a: u4, b: u4, op: u2) -> u5:\n    return unknown_bus\n', None),
])
def test_v1_source_errors_block_export_and_allow_recovery(tmp_path, bad_source, expected):
    project = fresh_project(tmp_path, 'alu_slice_component')
    source = project / 'circuit.py'
    original = source.read_text(encoding='utf-8')
    source.write_text(bad_source, encoding='utf-8')
    bad = BuildSession(project, 'compile').run()
    assert bad.status == 'FAILED', bad.as_dict()
    assert bad.stages['export']['status'] == 'BLOCKED'
    assert not list((project / 'build' / 'latest').glob('*.v'))
    assert bad.issues
    if expected:
        assert expected in [issue['code'] for issue in bad.issues]
    assert not any(issue['code'].startswith('INTERNAL.') for issue in bad.issues)
    source.write_text(original, encoding='utf-8')
    good = BuildSession(project, 'compile').run()
    assert good.status in ('SUCCESS', 'SUCCESS_WITH_WARNINGS'), good.as_dict()
    assert Path(good.files['verilog']).exists()


def test_v1_cli_project_entrypoint_compile_simulate(tmp_path):
    """The installed CLI, not only Python BuildSession imports, must work."""
    project = fresh_project(tmp_path, 'alu_slice_component')
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    def call(*args):
        done = subprocess.run([sys.executable, '-m', 'chipcompiler', *args],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr + done.stdout
        return json.loads(done.stdout)
    built = call('compile', str(project))
    assert built['status'] in ('SUCCESS', 'SUCCESS_WITH_WARNINGS')
    result = call('simulate', str(project), '--inputs', '{"a":15,"b":1,"op":0}')
    assert result['simulated_output'] == {'result': 16}


def test_v1_dependency_registration_is_isolated_and_reversible(tmp_path, monkeypatch):
    monkeypatch.setenv('PICADS_SETTINGS_DIR', str(tmp_path / 'settings'))
    bindir = tmp_path / 'tools'; bindir.mkdir()
    filename = 'yosys.exe' if sys.platform == 'win32' else 'yosys'
    executable = bindir / filename
    executable.write_text('test stub; not executed', encoding='utf-8')
    if sys.platform != 'win32':
        executable.chmod(0o755)
    assert register_tool('yosys', executable)['available']
    assert tool_status('yosys')['source'] == 'registered'
    assert 'yosys' in read_settings()['tools']
    unregister_tool('yosys')
    assert 'yosys' not in read_settings()['tools']
    # Do not require UNAVAILABLE: a legitimate Yosys on PATH should remain usable.
    assert tool_status('yosys')['source'] != 'registered'


def test_v1_physical_preflight_is_not_fake_signoff(tmp_path, monkeypatch):
    project = fresh_project(tmp_path, 'first_physical_chip')
    report = BuildSession(project, 'compile').run()
    assert report.status in ('SUCCESS', 'SUCCESS_WITH_WARNINGS')
    bad = physical_preflight({'enabled': False}, True)
    assert bad.status == 'BLOCKED'
    monkeypatch.delenv('PDK_ROOT', raising=False)
    missing = physical_preflight({'enabled': True, 'pdk': 'sky130A',
           'clock_period_ns': 20, 'pdk_root': str(tmp_path / 'not_a_pdk')}, True, check_tools=False)
    assert missing.status == 'BLOCKED'
    assert missing.checks['pdk_root']['status'] == 'BLOCKED'
    assert not missing.as_dict().get('manufacturing_qualified', False)


def test_v1_report_archive_has_integrity_manifest(tmp_path):
    out = tmp_path / 'diagnostics'
    (out / 'evidence').mkdir(parents=True)
    (out / 'summary.json').write_text('{"overall":"PARTIAL"}', encoding='utf-8')
    (out / 'evidence' / 'native.log').write_text('No physical tool installed', encoding='utf-8')
    archive = _package_report(out)
    assert archive.is_file()
    import zipfile
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert {'summary.json', 'evidence/native.log', 'FILE_MANIFEST.json'} <= set(bundle.namelist())
        manifest = json.loads(bundle.read('FILE_MANIFEST.json'))
        assert manifest['file_count'] == 2
        assert all(len(item['sha256']) == 64 for item in manifest['files'])


def test_v1_original_input_project_has_no_prebuilt_chip():
    root = EXAMPLES / 'alu_slice_component'
    paths = {p.relative_to(root).as_posix() for p in root.rglob('*')
             if p.is_file() and not {'build', '.chipcompiler', '.pytest_cache'} & set(p.relative_to(root).parts)}
    assert paths == {'chip.yaml', 'design.mcd', 'architecture.co', 'circuit.py'}
