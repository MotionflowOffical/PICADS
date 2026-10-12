"""Offscreen smoke test of the real Settings installer interface."""
import os
import pytest


def test_installer_dialog_has_explicit_opt_in_and_no_automatic_network(monkeypatch,tmp_path):
    pytest.importorskip('PySide6',reason='GUI dependencies are not available')
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from chipcompiler.gui import WindowsInstallerDialog
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    monkeypatch.setenv('PICADS_DEPENDENCY_ROOT',str(tmp_path/'dependencies'))
    app = QApplication.instance() or QApplication([])
    dialog = WindowsInstallerDialog()
    assert not any(box.isChecked() for box in dialog.choices.values())
    assert dialog.choices['oss-cad-suite'].isEnabled()
    assert not dialog.choices['librelane'].isEnabled()
    assert not dialog.choices['kicad'].isEnabled()
    dialog.close()
    app.processEvents()
