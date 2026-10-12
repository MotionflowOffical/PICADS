"""One-ZIP diagnostic contract for v0.15.1 Windows feature robot."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

from chipcompiler.feature_validation import _package_report, _emergency_report


def test_single_diagnostic_zip_includes_all_files_and_checksums(tmp_path):
    report = tmp_path / 'PICADS_v0.15.1_automated_diagnostics'
    (report / 'evidence' / 'alu_generated').mkdir(parents=True)
    for filename, content in {
        'summary.json': b'{"overall":"PARTIAL"}',
        'launcher.log': b'Python was discovered',
        'evidence/cli.log': b'An expected compiler error was caught',
        'evidence/alu_generated/slice.v': b'module slice; endmodule\n',
        'evidence/alu_generated/trace.vcd': b'$enddefinitions $end\n',
    }.items():
        path = report / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    archive = _package_report(report)
    assert archive.name == report.name + '.zip'  # version dots are preserved
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert not any(name.endswith('.zip') for name in z.namelist())
        manifest = json.loads(z.read('FILE_MANIFEST.json'))
        assert manifest['file_count'] == 5
        for entry in manifest['files']:
            assert len(z.read(entry['path'])) == entry['size_bytes']
            assert hashlib.sha256(z.read(entry['path'])).hexdigest() == entry['sha256']


def test_crashed_runner_still_creates_one_uploadable_archive(tmp_path):
    out = tmp_path / 'diagnostics'
    try:
        raise RuntimeError('simulated unexpected robot failure')
    except RuntimeError as exc:
        archive = _emergency_report(out, exc)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert 'FATAL_ERROR.txt' in z.namelist()
        assert 'summary.json' in z.namelist()
        assert json.loads(z.read('summary.json'))['overall'] == 'FAIL'
