"""Automated user journeys against the actual Qt window, not a mock GUI.

The tests run headless with Qt's offscreen plugin; they trigger real editor,
compile, simulation and Settings controls. User projects are copied into tmp.
"""
from __future__ import annotations
import json
import os
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPlainTextEdit
from PySide6.QtTest import QTest
from chipcompiler.gui import Window, CodeEditor

SAMPLE=Path(__file__).resolve().parents[1]/'examples'/'alu_slice_component'


@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setenv('PICADS_SETTINGS_DIR',str(tmp_path/'settings'))
    app=QApplication.instance() or QApplication([])
    root=tmp_path/'project'
    shutil.copytree(SAMPLE,root,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    window=Window(root)
    window.autosave.stop()
    window.build_timer.stop()
    window.show()
    app.processEvents()
    yield app,window,root
    if window.worker and window.worker.isRunning():
        assert window.worker.wait(30000), 'GUI background build never completed'
    app.processEvents()
    window.close()
    app.processEvents()
    assert not (window.root/'.chipcompiler'/'dirty_session.flag').exists()


def wait_for_build(app,window,limit=40):
    deadline=time.monotonic()+limit
    while time.monotonic()<deadline:
        app.processEvents()
        if window.last_report is not None and (window.worker is None or not window.worker.isRunning()):
            app.processEvents()
            return window.last_report
        QTest.qWait(25)
    pytest.fail('Build did not finish within timeout; last GUI log: '+window.logview.toPlainText()[-2000:])


def test_gui_edit_save_compile_visualize_simulate(gui,monkeypatch):
    app,win,root=gui
    path=root/'circuit.py'
    win.open_editor(path)
    editor=win.editors.currentWidget()
    assert isinstance(editor,CodeEditor)
    original=editor.toPlainText()
    # Simulate actual keyboard input. setPlainText() resets Qt's modified flag
    # because it is a programmatic document replacement, not an editor change.
    editor.setFocus()
    cursor=editor.textCursor();cursor.movePosition(cursor.MoveOperation.End);editor.setTextCursor(cursor)
    QTest.keyClicks(editor, '\n# Edited through the PICADS source editor.\n')
    app.processEvents()
    assert editor.document().isModified()
    win.save_all()
    assert path.read_text().endswith('# Edited through the PICADS source editor.\n')
    assert not editor.document().isModified()
    # Exercise the same action the user clicks in the Build panel.
    from PySide6.QtWidgets import QPushButton
    buttons=win.tabs.widget(4).findChildren(QPushButton)
    build=next(b for b in buttons if b.text()=='Generate & Verify DLS')
    build.click()
    report=wait_for_build(app,win)
    assert report.status in ('SUCCESS','SUCCESS_WITH_WARNINGS'),report.issues
    assert win.dls is not None
    assert win.artifacts.topLevelItemCount()>=3
    assert len(win.graph.graph.items())>0
    assert win.stage_list.topLevelItemCount()>0
    win.input_json.setText('{"a": 15, "b": 1, "op": 0}')
    win.simulate()
    assert win.simresults.rowCount()==1
    assert json.loads(win.simresults.item(0,2).text())=={'result':16}
    win.input_json.setText('{"a": 0, "b": 1, "op": 1}')
    win.simulate()
    assert json.loads(win.simresults.item(1,2).text())=={'result':15}
    evidence=os.getenv('PICADS_GUI_EVIDENCE_DIR')
    if evidence:
        output=Path(evidence);output.mkdir(parents=True,exist_ok=True)
        win.tabs.setCurrentIndex(0)
        assert win.grab().save(str(output/'gui_source_logic_graph.png'))
        win.tabs.setCurrentIndex(2)
        assert win.grab().save(str(output/'gui_simulation.png'))


def test_gui_fault_then_recovery_without_stale_success(gui,monkeypatch):
    app,win,root=gui
    source=root/'circuit.py'
    original=source.read_text()
    win.open_editor(source)
    editor=win.editors.currentWidget()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(editor, 'def alu_slice(\n')
    app.processEvents()
    assert editor.document().isModified()
    win.build('compile')
    report=wait_for_build(app,win)
    assert report.status=='FAILED'
    assert win.problem_tree.topLevelItemCount()>0
    assert win.dls is None, 'A failed build must not expose stale generated logic'
    assert report.stages['export']['status']=='BLOCKED'
    # Undo/replace through an editing operation, not setPlainText(): the
    # rebuild must actually read the recovered source from the editor.
    cursor=editor.textCursor();cursor.select(cursor.SelectionType.Document)
    cursor.insertText(original)
    app.processEvents()
    assert editor.document().isModified()
    win.last_report=None
    win.build('compile')
    good=wait_for_build(app,win)
    assert good.status in ('SUCCESS','SUCCESS_WITH_WARNINGS')
    assert win.problem_tree.topLevelItemCount()==0
    assert win.dls is not None
    assert (root/'build'/'history').exists()


def test_gui_dependency_choose_folder_and_clear(gui,monkeypatch,tmp_path):
    app,win,root=gui
    install=tmp_path/'bin';install.mkdir()
    fake=install/('yosys.exe' if os.name=='nt' else 'yosys')
    fake.write_text('test executable stub; never executed')
    if os.name!='nt':fake.chmod(0o755)
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a,**k:str(install))
    row=win.dependency_rows['yosys']
    win.dependency_table.cellWidget(row,3).click()
    assert 'AVAILABLE' in win.dependency_table.item(row,1).text()
    assert 'registered' in win.dependency_table.item(row,1).text()
    win.dependency_table.cellWidget(row,4).click()
    assert win.dependency_table.item(row,1).text().startswith('UNAVAILABLE'), (
        win.dependency_table.item(row,1).text())
    from chipcompiler.dependencies import read_settings
    assert 'yosys' not in read_settings()['tools']
    evidence=os.getenv('PICADS_GUI_EVIDENCE_DIR')
    if evidence:
        win.tabs.setCurrentIndex(6)
        output=Path(evidence);output.mkdir(parents=True,exist_ok=True)
        assert win.grab().save(str(output/'gui_dependencies.png'))


def test_gui_physical_preflight_unavailable_is_not_success(gui):
    app,win,root=gui
    win.preflight_physical()
    data=json.loads(win.physical_message.toPlainText())
    assert data['status'] in ('BLOCKED','UNAVAILABLE')
    assert data['status']!='PASS'
    assert win.tabs.currentIndex()==3


def test_gui_switching_projects_does_not_mix_open_source_or_state(gui,tmp_path):
    app,win,old=gui
    win.open_editor(old/'circuit.py')
    assert win.editors.count()==1
    another=tmp_path/'next_project'
    shutil.copytree(SAMPLE,another,ignore=shutil.ignore_patterns('build','.chipcompiler'))
    win._switch_project(another)
    assert win.root==another.resolve()
    assert win.editors.count()==0
    assert win.dls is None
    assert win.last_report is None
    assert not (old/'.chipcompiler'/'dirty_session.flag').exists()
    assert (another/'.chipcompiler'/'dirty_session.flag').is_file()
    win.open_editor(another/'circuit.py')
    assert win.editors.count()==1
    assert win.editors.currentWidget().path==another/'circuit.py'
