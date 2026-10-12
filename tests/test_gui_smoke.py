"""Runs only when Qt is installed. CI runs it on Windows and Linux."""
import os
import pytest

def test_qt_window_constructs_and_closes(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    qt=pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    from chipcompiler.cli import init_project
    from chipcompiler.gui import Window
    project=tmp_path/'chip';init_project(project)
    app=QApplication.instance() or QApplication([])
    window=Window(project)
    assert window.tabs.count()>=7
    assert window.graph is not None
    assert window.autosave.isActive()
    assert window.keep_versions.value()>0
    assert 'kicad-cli' in window.dependency_rows
    assert 'yosys' in window.dependency_rows
    assert window.dependency_table.cellWidget(window.dependency_rows['kicad-cli'],2).text()=='Choose App'
    assert window.dependency_table.cellWidget(window.dependency_rows['kicad-cli'],3).text()=='Choose Folder'
    assert window.pdk_label is not None
    window.close()
    assert not (project/'.chipcompiler'/'dirty_session.flag').exists()
