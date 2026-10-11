"""PySide6 all-in-one desktop shell for the verified core.

No fake tool status, area/timing estimates or mask previews. Each view displays
actual project data, or explains which prerequisite is unavailable.
"""
from __future__ import annotations
from pathlib import Path
import json,subprocess,shutil,zipfile,difflib,traceback,re,datetime
from .pipeline import BuildSession
from .project import open_project,atomic_write,snapshot,restore
from .diagnostics import IssueCollector
from .ir import DLS
from .waveform import export_vcd
from .maskinspect import inspect_gds
from .maskrender import render_gds_svg

try:
    from PySide6.QtCore import Qt,QTimer,QThread,Signal,QRegularExpression
    from PySide6.QtGui import QAction,QColor,QFont,QSyntaxHighlighter,QTextCharFormat,QBrush,QPen,QPainter
    from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QSplitter,QVBoxLayout,QHBoxLayout,
        QTreeWidget,QTreeWidgetItem,QTabWidget,QPlainTextEdit,QDockWidget,QLabel,QPushButton,QLineEdit,
        QGraphicsScene,QGraphicsView,QGraphicsRectItem,QGraphicsTextItem,QGraphicsLineItem,
        QMessageBox,QFileDialog,QComboBox,QToolBar,QInputDialog,QTableWidget,QTableWidgetItem,QHeaderView,
        QMenu,QCheckBox,QListWidget,QListWidgetItem,QStyle,QFormLayout,QSpinBox)
except ImportError as exc:
    raise ImportError('The GUI requires PySide6. Install with: pip install "chipcompiler[gui]"') from exc

STYLE='''
QWidget { background:#101923; color:#dce8ef; font-family: Segoe UI, sans-serif; font-size: 12px; }
QMainWindow,QSplitter,QDockWidget { background:#0b131b; }
QToolBar,QMenuBar,QStatusBar { background:#0d1923; border-bottom:1px solid #223543; }
QPushButton { background:#193044; border:1px solid #31516a; border-radius:5px; padding:7px 12px; }
QPushButton:hover {background:#22506d;} QPushButton:pressed{background:#13647f;}
QLineEdit,QPlainTextEdit,QComboBox,QSpinBox { background:#0b141d; color:#dfebf1; border:1px solid #274052; border-radius:4px; padding:5px; }
QTabWidget::pane {border:1px solid #213949;} QTabBar::tab {background:#152533;padding:9px 15px;border:1px solid #243b4b;}
QTabBar::tab:selected{background:#17384c;color:#7bdff0;border-bottom:2px solid #39b9da;}
QTreeWidget,QTableWidget,QListWidget {background:#0e1821;alternate-background-color:#142431;border:1px solid #274052;}
QTreeWidget::item:selected,QTableWidget::item:selected,QListWidget::item:selected {background:#1b4b64;}
QHeaderView::section {background:#1b2a36;border:1px solid #284152;padding:5px;}
QLabel#section {color:#71ccdf;font-weight:600;font-size:14px;}
QDockWidget::title {background:#152633;padding:6px;text-align:left;}
'''

class Syntax(QSyntaxHighlighter):
    def __init__(self,document):
        super().__init__(document)
        self.rules=[]
        patterns=[(r'\b(def|return|if|else|elif|for|in|range|True|False|and|or|not|reg)\b','#64b5f6'),
                  (r'\b(u\d+|s\d+|bool|top|source|modules|architecture|adder|description)\b','#9d8af6'),
                  (r'\b\d+\b','#eac477'),(r'"[^"\n]*"|\'[^\'\n]*\'','#8edca6'),(r'#[^\n]*','#579a82')]
        for regex,color in patterns:
            fmt=QTextCharFormat();fmt.setForeground(QColor(color))
            self.rules.append((QRegularExpression(regex),fmt))
    def highlightBlock(self,text):
        for expression,fmt in self.rules:
            it=expression.globalMatch(text)
            while it.hasNext():
                m=it.next();self.setFormat(m.capturedStart(),m.capturedLength(),fmt)

class CodeEditor(QPlainTextEdit):
    def __init__(self,path:Path):
        super().__init__()
        self.path=Path(path)
        self.setFont(QFont('Consolas',11));self.setTabStopDistance(28)
        self.setPlainText(self.path.read_text(encoding='utf-8'))
        self.syntax=Syntax(self.document());self.document().setModified(False)

class GraphView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.graph=QGraphicsScene(self);self.setScene(self.graph)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor('#0a151d'))
        self.scale(0.95,0.95)
    def wheelEvent(self,event):
        factor=1.12 if event.angleDelta().y()>0 else 1/1.12
        self.scale(factor,factor)
    def show_dls(self,dls:DLS|None):
        self.graph.clear()
        if dls is None:
            self.graph.addText('Generate DLS to view the actual logic graph.').setDefaultTextColor(QColor('#94abba'))
            return
        # Render actual instance boundaries as well as primitive gates.
        # Rendering is capped for responsiveness, with explicit clipping notices.
        cap=180
        nodes=dls.nodes[:cap]
        instances=[x for x in dls.instances if x['at']<=cap][:48]
        by_at={}
        for inst in instances:by_at.setdefault(inst['at'],[]).append(inst)
        levels={'@0':0,'@1':0}
        for name,width in dls.inputs.items():
            for j in range(width):levels[f'{name}[{j}]']=0
        for name,desc in dls.registers.items():
            for j in range(len(desc['next'])):levels[f'${name}[{j}]']=0
        bylevel={}
        for at in range(len(nodes)+1):
            for inst in by_at.get(at,[]):
                ins=[p for bits in inst['inputs'].values() for p in bits]
                level=1+max((levels.get(p,0) for p in ins),default=0)
                bylevel.setdefault(level,[]).append(('module',inst))
                for bits in inst['outputs'].values():
                    for name in bits:levels[name]=level
            if at<len(nodes):
                node=nodes[at]
                level=1+max((levels.get(x,0) for x in node.inputs),default=0)
                levels[node.name]=level
                bylevel.setdefault(level,[]).append(('gate',node))
        pos={};render=[]
        for lvl,items in bylevel.items():
            for i,(kind,obj) in enumerate(items):
                x=lvl*160;y=i*70+75
                key=obj['name'] if kind=='module' else obj.name
                pos[key]=(x,y);render.append((kind,obj,x,y))
                if kind=='module':
                    for bits in obj['outputs'].values():
                        for signal in bits:pos[signal]=(x,y)
        edgepen=QPen(QColor('#28657c'),1.1)
        for kind,obj,x,y in render:
            incoming=[p for bits in obj['inputs'].values() for p in bits] if kind=='module' else obj.inputs
            for pin in incoming:
                if pin in pos:
                    sx,sy=pos[pin]
                    if (sx,sy)!=(x,y):self.graph.addLine(sx+112,sy+19,x,y+19,edgepen)
        for kind,obj,x,y in render:
            if kind=='module':
                rect=self.graph.addRect(x,y,112,40,QPen(QColor('#dcac61'),1.5),QBrush(QColor('#3a3029')))
                rect.setToolTip(f'Instantiated {obj["module"]}\n{obj["name"]}\n'
                                f'Input ports: {list(obj["inputs"])}\nOutput ports: {list(obj["outputs"])}\n'
                                f'Source: {obj.get("source_location","")}')
                label=f'MODULE {obj["module"]}'
                color='#f8d18c'
            else:
                rect=self.graph.addRect(x,y,112,40,QPen(QColor('#3e829e')),QBrush(QColor('#172d40')))
                rect.setToolTip(f'{obj.name}: {obj.op}\nInputs: {obj.inputs}\nSource: {obj.origin}')
                label=f'{obj.op} {obj.name}';color='#d7edf5'
            txt=self.graph.addText(label);txt.setDefaultTextColor(QColor(color))
            txt.setPos(x+4,y+9);txt.setScale(.72)
        mode=dls.metadata.get('schedule',{}).get('mode') if isinstance(dls.metadata.get('schedule'),dict) else None
        pipe=dls.metadata.get('pipeline',{})
        subtitle=(f' • TIME-SHARED FSM ({dls.metadata["schedule"]["execution_cycles"]} execution cycles)'
                  if mode=='time_share' else f' • {pipe["stages"]}-stage pipeline'
                  if pipe else '')
        header=self.graph.addText(f'{dls.name} • {len(dls.nodes)} gates • '
                                  f'{len(dls.registers)} registers • {len(dls.instances)} instances{subtitle}')
        header.setDefaultTextColor(QColor('#82d8e8'));header.setPos(10,0)
        if len(dls.nodes)>cap or len(dls.instances)>48:
            notice=self.graph.addText(f'PARTIAL VIEW: {len(nodes)}/{len(dls.nodes)} gates, '
                f'{len(instances)}/{len(dls.instances)} instances. Full design in saved DLS.')
            notice.setDefaultTextColor(QColor('#ffbc71'));notice.setPos(10,30)
        if not render:
            message=self.graph.addText('No intermediate gates: direct connections or registers only.')
            message.setDefaultTextColor(QColor('#cbdfe7'));message.setPos(10,75)
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-30,-20,60,30))

class BuildWorker(QThread):
    finished_report=Signal(object)
    def __init__(self,path:Path,mode:str):super().__init__();self.path=path;self.mode=mode
    def run(self):
        try:self.finished_report.emit(BuildSession(self.path,self.mode).run())
        except BaseException as exc:self.finished_report.emit({'gui_worker_error':traceback.format_exc()})

class Window(QMainWindow):
    def __init__(self,root:Path):
        super().__init__()
        self.root=root.resolve();self.setWindowTitle('Chip Compiler — Procedural Chip Design Suite')
        self.resize(1560,940);self.setStyleSheet(STYLE)
        self.dls=None;self.last_report=None;self.worker=None
        self.sim_vectors=[];self.sim_outputs=[]
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks|QMainWindow.DockOption.AllowTabbedDocks)
        self.editors=QTabWidget();self.editors.setTabsClosable(True);self.editors.tabCloseRequested.connect(self.close_editor)
        self.graph=GraphView()
        split=QSplitter(Qt.Orientation.Horizontal);split.addWidget(self.editors);split.addWidget(self.graph);split.setSizes([670,750])
        self.tabs=QTabWidget();self.tabs.addTab(split,'Code + Logic Graph')
        self.tabs.addTab(self._architecture_page(),'Architecture / Dependencies')
        self.tabs.addTab(self._simulation_page(),'Simulate / Debug')
        self.tabs.addTab(self._physical_page(),'Physical / Masks')
        self.tabs.addTab(self._build_page(),'Build / Export')
        self.tabs.addTab(self._history_page(),'History / Recovery')
        self.tabs.addTab(self._settings_page(),'Settings')
        self.setCentralWidget(self.tabs)
        self.project_tree=QTreeWidget();self.project_tree.setHeaderLabels(['Project files']);self.project_tree.itemDoubleClicked.connect(self.open_tree_item)
        self._dock('Project Explorer',self.project_tree,Qt.DockWidgetArea.LeftDockWidgetArea)
        self.inspector=QTreeWidget();self.inspector.setHeaderLabels(['Attribute','Value']);self.inspector.setColumnWidth(0,115)
        self._dock('Inspector',self.inspector,Qt.DockWidgetArea.RightDockWidgetArea)
        diagnostic_widget=QWidget();dv=QVBoxLayout(diagnostic_widget);dv.setContentsMargins(2,2,2,2)
        self.problem_tree=QTreeWidget();self.problem_tree.setHeaderLabels(['Severity','Code','Origin / Stage','Message','Location']);self.problem_tree.itemDoubleClicked.connect(self.on_problem)
        self.problem_tree.setColumnWidth(0,105);self.problem_tree.setColumnWidth(1,180);self.problem_tree.setColumnWidth(2,160)
        self.logview=QPlainTextEdit();self.logview.setReadOnly(True);self.logview.setMaximumHeight(105)
        dv.addWidget(self.problem_tree);dv.addWidget(self.logview)
        self._dock('Problems / Causal Diagnostics',diagnostic_widget,Qt.DockWidgetArea.BottomDockWidgetArea)
        self._toolbar();self._menubar()
        self.statusBar().showMessage('No design generated. Physical and signoff results unavailable.')
        self.autosave=QTimer(self);self.autosave.timeout.connect(self.auto_save)
        self.apply_autosave_settings()
        self.build_timer=QTimer(self);self.build_timer.timeout.connect(self.refresh_build_log)
        self.build_timer.start(1500)
        self.populate_tree();self.refresh_history();self.graph.show_dls(None)
        marker=self.root/'.chipcompiler'/'dirty_session.flag'
        if marker.exists():
            self.statusBar().showMessage('RECOVERY: Previous session ended without clean shutdown; see History / Recovery.')
            self.logview.appendPlainText(f'WARNING: crash marker detected at {marker}. Restore autosave snapshot if needed.')
        marker.parent.mkdir(parents=True,exist_ok=True)
        atomic_write(marker,datetime.datetime.now(datetime.timezone.utc).isoformat())

    def _dock(self,name,widget,area):
        dock=QDockWidget(name,self);dock.setObjectName(name);dock.setWidget(widget)
        self.addDockWidget(area,dock)
        return dock
    def action(self,name,handler,toolbar=None,shortcut=None):
        a=QAction(name,self);a.triggered.connect(handler)
        if shortcut:a.setShortcut(shortcut)
        if toolbar:toolbar.addAction(a)
        return a
    def _toolbar(self):
        tool=QToolBar('Main',self);tool.setMovable(False);self.addToolBar(tool)
        self.action('New Project',self.new_project,tool)
        self.action('Open Project',self.select_project,tool)
        self.action('Save All',self.save_all,tool,'Ctrl+S')
        tool.addSeparator()
        self.action('Generate DLS',lambda:self.build('compile'),tool,'F5')
        self.action('Simulate',self.simulate,tool,'F6')
        self.action('Synthesize',lambda:self.build('build'),tool,'F7')
        self.action('Physical Flow',lambda:self.build('physical'),tool,'F8')
        self.action('Mask Viewer',self.open_mask,tool)
        tool.addSeparator()
        self.action('Snapshot',self.make_snapshot,tool)
        self.action('Restore Backup',self.restore_backup,tool)
    def _menubar(self):
        m=self.menuBar();file=m.addMenu('File')
        for label,fn in [('New Project',self.new_project),('Open Project',self.select_project),('Save All',self.save_all),('Snapshot',self.make_snapshot),('Restore',self.restore_backup)]:self.action(label,fn,file)
        build=m.addMenu('Build');self.action('Compile & Verify',lambda:self.build('compile'),build)
        self.action('Synthesize with Yosys',lambda:self.build('build'),build)
        self.action('Physical Implement',lambda:self.build('physical'),build)
        view=m.addMenu('View')
        for idx,text in enumerate(['Code + Logic Graph','Architecture / Dependencies','Simulate / Debug','Physical / Masks','Build / Export','History / Recovery','Settings']):
            self.action(text,lambda checked=False,i=idx:self.tabs.setCurrentIndex(i),view)

    def populate_tree(self):
        self.project_tree.clear();rootitem=QTreeWidgetItem([self.root.name]);rootitem.setData(0,Qt.ItemDataRole.UserRole,str(self.root));self.project_tree.addTopLevelItem(rootitem)
        def insert(parent,path,level):
            if level>7:return
            for p in sorted(path.iterdir(),key=lambda x:(x.is_file(),x.name.lower())):
                if p.name in ('.chipcompiler','build','.git','__pycache__','.pytest_cache'):continue
                item=QTreeWidgetItem([p.name]);item.setData(0,Qt.ItemDataRole.UserRole,str(p));parent.addChild(item)
                if p.is_dir():insert(item,p,level+1)
        if self.root.exists():insert(rootitem,self.root,0)
        rootitem.setExpanded(True)
    def open_tree_item(self,item,col):
        path=Path(item.data(0,Qt.ItemDataRole.UserRole))
        if path.is_file() and path.suffix.lower() in ('.py','.mcd','.co','.yaml','.yml','.json','.dls','.v','.txt','.md','.log','.tcl'):
            self.open_editor(path)
    def open_editor(self,path:Path):
        for i in range(self.editors.count()):
            w=self.editors.widget(i)
            if isinstance(w,CodeEditor) and w.path==path:self.editors.setCurrentIndex(i);self.tabs.setCurrentIndex(0);return
        try:e=CodeEditor(path)
        except Exception as exc:QMessageBox.critical(self,'Open failed',str(exc));return
        index=self.editors.addTab(e,path.name);self.editors.setCurrentIndex(index)
        e.document().modificationChanged.connect(lambda dirty,w=e:self.mark_editor(w,dirty))
        self.tabs.setCurrentIndex(0)
    def mark_editor(self,editor,dirty):
        i=self.editors.indexOf(editor)
        if i>=0:self.editors.setTabText(i,editor.path.name+('*' if dirty else ''))
    def close_editor(self,index):
        e=self.editors.widget(index)
        if e.document().isModified():
            answer=QMessageBox.question(self,'Unsaved changes',f'Save {e.path.name} before closing?',
                 QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel)
            if answer==QMessageBox.StandardButton.Cancel:return
            if answer==QMessageBox.StandardButton.Yes:self.save_editor(e)
        self.editors.removeTab(index);e.deleteLater()
    def save_editor(self,e):
        try:atomic_write(e.path,e.toPlainText());e.document().setModified(False)
        except OSError as exc:QMessageBox.critical(self,'Save failed',str(exc))
    def save_all(self):
        for i in range(self.editors.count()):
            e=self.editors.widget(i)
            if e.document().isModified():self.save_editor(e)
        self.statusBar().showMessage('Saved all open modified files.')
    def auto_save(self):
        dirty=any(self.editors.widget(i).document().isModified() for i in range(self.editors.count()))
        if dirty:
            # Save recovery copies of unsaved buffers before overwriting working sources.
            rec=self.root/'.chipcompiler'/'unsaved';rec.mkdir(parents=True,exist_ok=True)
            for i in range(self.editors.count()):
                e=self.editors.widget(i)
                if e.document().isModified():
                    relative=e.path.relative_to(self.root)
                    atomic_write(rec/relative,e.toPlainText())
            self.save_all()
        try:
            # Avoid rotating away useful snapshots when nothing has changed.
            import hashlib
            entries=[]
            for p in sorted(self.root.rglob('*')):
                if not p.is_file() or any(x in ('.chipcompiler','build','.git') for x in p.relative_to(self.root).parts):continue
                stat=p.stat();entries.append(f'{p.relative_to(self.root)}:{stat.st_size}:{stat.st_mtime_ns}')
            digest=hashlib.sha256('\n'.join(entries).encode()).hexdigest()
            statefile=self.root/'.chipcompiler'/'autosave.last_digest'
            if statefile.is_file() and statefile.read_text()==digest:return
            snap=snapshot(self.root,'autosave',max_versions=self.keep_versions.value())
            atomic_write(statefile,digest)
            self.statusBar().showMessage('Autosave + recovery snapshot: '+Path(snap['file']).name)
            if snap['excluded']:
                self.logview.appendPlainText(f'[WARNING] Snapshot excluded {len(snap["excluded"])} items: {snap["excluded"]}')
        except Exception as exc:self.logview.appendPlainText(f'[WARNING] Autosave failed: {exc}')
    def select_project(self):
        path=QFileDialog.getExistingDirectory(self,'Open Chip Compiler project',str(self.root))
        if path:
            self.save_all();self.root=Path(path).resolve();self.dls=None;self.graph.show_dls(None)
            self.populate_tree();self.refresh_history()
    def new_project(self):
        path=QFileDialog.getExistingDirectory(self,'Choose new project folder',str(self.root.parent))
        if path:
            from .cli import init_project
            init_project(Path(path));self.root=Path(path).resolve();self.populate_tree();self.graph.show_dls(None)
    def build(self,mode):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self,'Build running','Existing build must finish before starting a new one.');return
        self.save_all()
        self.problem_tree.clear();self.logview.appendPlainText(f'--- {mode.upper()} started, source files saved ---')
        self.worker=BuildWorker(self.root,mode)
        self.worker.finished_report.connect(self.build_finished)
        self.worker.start();self.statusBar().showMessage('Running '+mode+'…')
        self.tabs.setCurrentIndex(4)
    def build_finished(self,report):
        if isinstance(report,dict):
            self.logview.appendPlainText(report.get('gui_worker_error',str(report)));return
        self.last_report=report
        self.statusBar().showMessage(f'Build {report.status}; run ID {report.run_id}. See Problems for cause IDs.')
        self.problem_tree.clear()
        for issue in report.issues:
            loc=(str(issue.get('file') or '')+(':'+str(issue.get('line')) if issue.get('line') else ''))
            item=QTreeWidgetItem([issue['severity'],issue['code'],f"{issue['origin']} / {issue['stage']}",issue['message'],loc])
            item.setToolTip(3,json.dumps(issue,indent=2))
            item.setData(0,Qt.ItemDataRole.UserRole,issue)
            self.problem_tree.addTopLevelItem(item)
        self.stage_list.clear()
        for name,stage in report.stages.items():
            item=QTreeWidgetItem([name,stage['status'],str(stage.get('upstream_issue_ids',''))]);self.stage_list.addTopLevelItem(item)
        self.artifacts.clear()
        for label,file in report.files.items():
            item=QTreeWidgetItem([label,file]);item.setData(0,Qt.ItemDataRole.UserRole,file);self.artifacts.addTopLevelItem(item)
        if 'dls' in report.files:
            try:
                self.dls=DLS.load(Path(report.files['dls']));self.graph.show_dls(self.dls)
                self._fill_inspector();self._fill_architecture();self._fill_simulation_signals()
            except Exception as exc:
                self.logview.appendPlainText(f'[ERROR] GUI could not load generated DLS: {exc}')
        self.populate_tree();self.refresh_history()
        self.logview.appendPlainText(f'[{report.status}] report: {report.files.get("report")}')
    def on_problem(self,item,col):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data:return
        text=json.dumps(data,indent=2)
        QMessageBox.information(self,f"{data['code']} • {data['issue_id']}",text[:10000])
        if data.get('file') and Path(data['file']).is_file():
            self.open_editor(Path(data['file']))
            if data.get('line'):
                editor=self.editors.currentWidget()
                cursor=editor.textCursor();cursor.movePosition(cursor.MoveOperation.Start)
                cursor.movePosition(cursor.MoveOperation.Down,cursor.MoveMode.MoveAnchor,max(0,data['line']-1))
                editor.setTextCursor(cursor)
    def refresh_build_log(self):
        log=self.root/'build'/'latest'/'events.jsonl'
        if self.worker and self.worker.isRunning() and log.is_file():
            try:
                lines=log.read_text(encoding='utf-8').splitlines()[-6:]
                if lines:
                    e=json.loads(lines[-1]);self.statusBar().showMessage('Build: '+e.get('stage','')+' / '+e.get('action',''))
            except Exception:pass
    def _fill_inspector(self):
        self.inspector.clear()
        if not self.dls:return
        for name,value in self.dls.stats().items():self.inspector.addTopLevelItem(QTreeWidgetItem([name,str(value)]))
        for name,value in self.dls.metadata.items():
            if name in ('co','source_sha256'):continue
            self.inspector.addTopLevelItem(QTreeWidgetItem([name,str(value)]))

    def _architecture_page(self):
        w=QWidget();layout=QHBoxLayout(w)
        self.hierarchy=QTreeWidget();self.hierarchy.setHeaderLabels(['Module / Signal','Detail']);layout.addWidget(self.hierarchy,2)
        right=QWidget();v=QVBoxLayout(right)
        title=QLabel('Module, Variable & Dependency Explorer');title.setObjectName('section');v.addWidget(title)
        self.arch_graph=QTreeWidget();self.arch_graph.setHeaderLabels(['Resource / Relationship','Resolved to']);v.addWidget(self.arch_graph)
        self.arch_graph.itemDoubleClicked.connect(self.arch_double_click)
        layout.addWidget(right,3)
        return w
    def arch_double_click(self,item,col):
        path=item.data(0,Qt.ItemDataRole.UserRole)
        if path and Path(path).is_file():self.open_editor(Path(path))
    def _fill_architecture(self):
        self.hierarchy.clear();self.arch_graph.clear()
        if not self.dls:return
        d=self.dls
        top=QTreeWidgetItem([d.name,'Top procedural circuit']);self.hierarchy.addTopLevelItem(top)
        for label,values in [('Inputs',d.inputs),('Outputs',d.outputs),('Registers',d.registers)]:
            parent=QTreeWidgetItem([label,str(len(values))]);top.addChild(parent)
            for name,value in values.items():parent.addChild(QTreeWidgetItem([name,str(value)]))
        gates=QTreeWidgetItem(['Generated logic',f'{len(d.nodes)} primitive gates']);top.addChild(gates)
        for op,count in sorted(d.stats()['gate_types'].items()):gates.addChild(QTreeWidgetItem([op,str(count)]))
        if d.instances:
            instances=QTreeWidgetItem(['Actual DLS instances',str(len(d.instances))]);top.addChild(instances)
            def populate(parent,module,depth=0):
                if depth>25:return
                for inst in module.instances:
                    child=module.submodules[inst['module']]
                    label=f'{inst["name"]}: {inst["module"]}'
                    item=QTreeWidgetItem([label,f'{len(child.nodes)} gates / {len(child.registers)} registers / clock: {child.requires_clock()}'])
                    parent.addChild(item)
                    for key,pins in inst['inputs'].items():
                        item.addChild(QTreeWidgetItem(['Input '+key,str(len(pins))+' bits']))
                    if child.registers:
                        registers=QTreeWidgetItem(['Local registers',str(len(child.registers))]);item.addChild(registers)
                        for rn,rd in child.registers.items():
                            registers.addChild(QTreeWidgetItem([rn,f'{len(rd["next"])} bits, init={rd.get("init",0)}']))
                    populate(item,child,depth+1)
            populate(instances,d)
            instances.setExpanded(True)
        top.setExpanded(True)
        # The functional hierarchy report reflects separately generated DLS
        # modules. Physical RTL is currently flattened, displayed honestly.
        arch_file=self.root/'build'/'latest'/'architecture.json'
        if arch_file.is_file():
            try:
                hierarchy=json.loads(arch_file.read_text(encoding='utf-8'))
                group=QTreeWidgetItem(['Functional modules','Actual hierarchical RTL' if hierarchy.get('semantics')=='HIERARCHICAL_EXECUTABLE_DLS' else 'Functional candidates; no guaranteed instance preservation'])
                self.hierarchy.addTopLevelItem(group)
                for name in hierarchy.get('functions',[]):
                    item=QTreeWidgetItem([name,'reachable' if name in hierarchy.get('reachable',[]) else 'unused'])
                    group.addChild(item)
                    childfile=self.root/'build'/'latest'/'modules'/(name+'.dls')
                    if childfile.is_file():item.setData(0,Qt.ItemDataRole.UserRole,str(childfile))
                group.setExpanded(True)
                for edge in hierarchy.get('edges',[]):
                    self.arch_graph.addTopLevelItem(QTreeWidgetItem(['Call dependency',edge['caller']+' → '+edge['callee']]))
                for req in hierarchy.get('requested',[]):
                    self.arch_graph.addTopLevelItem(QTreeWidgetItem(['MCD '+req['name'],str(req['status'])+' / '+str(req['function'])]))
            except (ValueError, OSError) as exc:
                self.arch_graph.addTopLevelItem(QTreeWidgetItem(['Architecture read error',str(exc)]))
        for group,info in [('Procedural strategies',d.metadata.get('strategies',{})),('Libraries','Boolean primitive gates (local)'),('CO overrides',d.metadata.get('co',{}))]:
            item=QTreeWidgetItem([group,str(info)]);self.arch_graph.addTopLevelItem(item)
        p=IssueCollector();project=open_project(self.root,p)
        if project:
            for mod in project.mcd.get('modules',[]):
                if not isinstance(mod,dict):continue
                self.arch_graph.addTopLevelItem(QTreeWidgetItem(['MCD '+str(mod.get('name','?')),str(mod.get('purpose',''))]))

    def _simulation_page(self):
        w=QWidget();v=QVBoxLayout(w)
        title=QLabel('DLS Gate-Level Execution');title.setObjectName('section');v.addWidget(title)
        v.addWidget(QLabel('Input vector (JSON). State registers advance on each Step Cycle.'))
        row=QHBoxLayout();self.input_json=QLineEdit('{"a": 3, "b": 5, "d": 1}');row.addWidget(self.input_json)
        button=QPushButton('Step Cycle');button.clicked.connect(self.simulate);row.addWidget(button)
        reset=QPushButton('Reset State');reset.clicked.connect(self.reset_sim);row.addWidget(reset)
        export=QPushButton('Export VCD');export.clicked.connect(self.export_waveforms);row.addWidget(export)
        v.addLayout(row)
        self.simstate=None;self.simresults=QTableWidget(0,4);self.simresults.setHorizontalHeaderLabels(['Cycle','Input vector','Output','Register state']);v.addWidget(self.simresults,2)
        v.addWidget(QLabel('Logical signal history (each column is a virtual cycle; not physically timed).'))
        self.simwave=QTableWidget(0,1);self.simwave.setHorizontalHeaderLabels(['Signal / cycle']);v.addWidget(self.simwave,1)
        v.addWidget(QLabel('Timing shown is logical only. Physical delays require RC extraction and timing analysis.'))
        return w
    def _fill_simulation_signals(self):
        if self.dls:
            self.input_json.setText(json.dumps({k:0 for k in self.dls.inputs}))
            self.reset_sim()
    def reset_sim(self):
        self.simstate=self.dls.new_simulator() if self.dls else None;self.simresults.setRowCount(0)
        self.sim_vectors=[];self.sim_outputs=[]
        self.simwave.setRowCount(0);self.simwave.setColumnCount(1)
    def update_signal_history(self):
        if self.dls is None:return
        names=[*self.dls.inputs,*self.dls.outputs]
        displayed=self.sim_vectors[-24:]
        results=self.sim_outputs[-24:]
        self.simwave.setRowCount(len(names));self.simwave.setColumnCount(1+len(displayed))
        self.simwave.setHorizontalHeaderLabels(['Signal']+[str(i+max(0,len(self.sim_vectors)-24)+1) for i in range(len(displayed))])
        for row,name in enumerate(names):
            self.simwave.setItem(row,0,QTableWidgetItem(name))
            for j,(inp,out) in enumerate(zip(displayed,results)):
                value=(inp if name in self.dls.inputs else out).get(name)
                text='X' if value is None else hex(value)
                self.simwave.setItem(row,j+1,QTableWidgetItem(text))
    def export_waveforms(self):
        if not self.dls or not self.sim_vectors:
            QMessageBox.warning(self,'No trace','Simulate at least one cycle before exporting waveforms.');return
        path,_=QFileDialog.getSaveFileName(self,'Save logical VCD trace',str(self.root/'build'/'latest'/'trace.vcd'),'VCD waveform (*.vcd)')
        if not path:return
        try:
            result=export_vcd(self.dls,self.sim_vectors,Path(path))
            self.logview.appendPlainText('[INFO] Logical VCD exported: '+json.dumps(result))
            QMessageBox.information(self,'VCD exported','Logical waveform saved. Virtual cycle timestamps are NOT gate timing.')
        except Exception as exc:QMessageBox.critical(self,'VCD export failed',f'{type(exc).__name__}: {exc}')
    def simulate(self):
        if self.dls is None:
            QMessageBox.warning(self,'No generated circuit','Compile DLS before simulating.');return
        try:
            inp=json.loads(self.input_json.text())
            if not isinstance(inp,dict):raise ValueError('Input must be a JSON object.')
            if self.simstate is None:self.simstate=self.dls.new_simulator()
            result=self.simstate.step(inp)
            self.sim_vectors.append(dict(inp));self.sim_outputs.append(dict(result))
            idx=self.simresults.rowCount();self.simresults.insertRow(idx)
            for col,txt in enumerate([str(self.simstate.cycle),json.dumps(inp),json.dumps(result),json.dumps(self.simstate.register_snapshot(),sort_keys=True)]):
                self.simresults.setItem(idx,col,QTableWidgetItem(txt))
            self.simresults.scrollToBottom();self.update_signal_history();self.tabs.setCurrentIndex(2)
        except Exception as exc:QMessageBox.critical(self,'DLS simulation error',f'{type(exc).__name__}: {exc}')

    def _physical_page(self):
        w=QWidget();v=QVBoxLayout(w)
        title=QLabel('Physical Layout / Mask Data');title.setObjectName('section');v.addWidget(title)
        v.addWidget(QLabel('Real masks are only available after a successful physical EDA run with a valid PDK. No synthetic mask is displayed.'))
        buttons=QHBoxLayout()
        for text,fn in [('Inspect GDS Metadata',self.inspect_mask),('Render GDS Geometry',self.render_mask),('Open GDS/OASIS in KLayout',self.open_mask),('Run Physical Flow',lambda:self.build('physical')),('Refresh Artifacts',self.populate_tree)]:
            b=QPushButton(text);b.clicked.connect(fn);buttons.addWidget(b)
        v.addLayout(buttons)
        self.physical_message=QPlainTextEdit();self.physical_message.setReadOnly(True)
        self.physical_message.setPlainText('Physical design prerequisites:\n1. Compile & verify DLS\n2. Install Yosys + LibreLane (WSL2 or supported Linux)\n3. Configure licensed or open PDK and standard cells\n4. Run synthesis, placement, routing and physical verification\n5. Inspect actual GDSII/OASIS in KLayout, or render a read-only GDS geometry preview\n\nA gate-level DLS file alone is not a manufacturing mask.')
        v.addWidget(self.physical_message)
        self.physical_layout=v
        self.mask_svg_widget=None
        return w
    def render_mask(self):
        file,_=QFileDialog.getOpenFileName(self,'Render actual GDSII geometry',str(self.root/'build'),'GDSII (*.gds *.gdsii)')
        if not file:return
        try:
            dest=self.root/'build'/'mask_previews'/(Path(file).stem+'.svg')
            try:report=render_gds_svg(Path(file),dest)
            except Exception as exc:
                # In particular, do not silently select an ambiguous top cell.
                if getattr(exc,'code',None)!='GDS.AMBIGUOUS_TOP':raise
                name,ok=QInputDialog.getText(self,'Choose GDS top cell',str(exc)+'\nEnter the top cell name:')
                if not ok or not name:return
                report=render_gds_svg(Path(file),dest,top=name.strip())
            self.physical_message.setPlainText(json.dumps(report.as_dict(),indent=2))
            if self.mask_svg_widget is None:
                try:from PySide6.QtSvgWidgets import QSvgWidget
                except ImportError as exc:
                    self.physical_message.appendPlainText('WARNING: QtSvgWidgets unavailable; actual SVG was saved to '+str(dest))
                    self.tabs.setCurrentIndex(3)
                    return
                self.mask_svg_widget=QSvgWidget()
                self.physical_layout.addWidget(self.mask_svg_widget,4)
            self.mask_svg_widget.load(str(dest))
            self.tabs.setCurrentIndex(3)
        except Exception as exc:
            QMessageBox.critical(self,'GDS geometry preview failed',f'{type(exc).__name__}: {exc}')
    def inspect_mask(self):
        path,_=QFileDialog.getOpenFileName(self,'Inspect GDSII file',str(self.root/'build'),'GDSII (*.gds *.gdsii)')
        if not path:return
        try:
            data=inspect_gds(Path(path)).as_dict()
            self.physical_message.setPlainText(json.dumps(data,indent=2))
            self.tabs.setCurrentIndex(3)
        except Exception as exc:
            QMessageBox.critical(self,'GDSII inspection failed',f'{type(exc).__name__}: {exc}')
    def open_mask(self):
        file,_=QFileDialog.getOpenFileName(self,'Open physical layout',str(self.root/'build'), 'Chip layout (*.gds *.gdsii *.oas *.oasis);;All files (*)')
        if not file:return
        path=shutil.which('klayout')
        if not path:
            QMessageBox.warning(self,'Missing KLayout','KLayout is not on PATH. The layout viewer was not launched.\nInstall KLayout or open this file manually.');return
        try:subprocess.Popen([path,file])
        except OSError as exc:QMessageBox.critical(self,'KLayout launch failed',str(exc))

    def _build_page(self):
        w=QWidget();v=QVBoxLayout(w)
        row=QHBoxLayout()
        for name,mode in [('Generate & Verify DLS','compile'),('Synthesize with Yosys','build'),('Physical Flow / LibreLane','physical')]:
            button=QPushButton(name);button.clicked.connect(lambda checked=False,m=mode:self.build(m));row.addWidget(button)
        v.addLayout(row)
        v.addWidget(QLabel('Execution status is evidence-based: PASS / FAIL / BLOCKED / UNAVAILABLE; never simulated signoff.'))
        split=QSplitter(Qt.Orientation.Horizontal)
        self.stage_list=QTreeWidget();self.stage_list.setHeaderLabels(['Stage','Status','Blocked by issue ID']);split.addWidget(self.stage_list)
        self.artifacts=QTreeWidget();self.artifacts.setHeaderLabels(['Artifact','Path']);self.artifacts.itemDoubleClicked.connect(self.open_artifact);split.addWidget(self.artifacts)
        v.addWidget(split)
        return w
    def open_artifact(self,item,col):
        path=Path(item.data(0,Qt.ItemDataRole.UserRole) or '')
        if path.is_file() and path.suffix in ('.v','.dls','.json','.log','.txt'):self.open_editor(path)

    def _settings_page(self):
        w=QWidget();v=QVBoxLayout(w)
        heading=QLabel('Project Settings / Autosave & Backups');heading.setObjectName('section');v.addWidget(heading)
        note=QLabel('Only editor changes are autosaved. Generated build artifacts remain in build/latest and build/history.');v.addWidget(note)
        form=QFormLayout()
        self.autosave_enabled=QCheckBox('Enable automatic saves and recovery snapshots')
        form.addRow('Autosave',self.autosave_enabled)
        self.autosave_interval=QSpinBox();self.autosave_interval.setRange(15,3600);self.autosave_interval.setSuffix(' seconds')
        form.addRow('Interval',self.autosave_interval)
        self.keep_versions=QSpinBox();self.keep_versions.setRange(1,1000)
        form.addRow('Maximum retained source snapshots',self.keep_versions)
        v.addLayout(form)
        self.settings_message=QLabel('Settings are local to this project. A failed save is reported.')
        v.addWidget(self.settings_message)
        v.addStretch(1)
        try:
            path=self.root/'.chipcompiler'/'settings.json'
            values=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            if not isinstance(values,dict):raise ValueError('Settings root must be JSON object')
        except (OSError,ValueError) as exc:
            values={};self.settings_message.setText(f'WARNING: Could not parse settings: {exc}. Safe defaults are active; original file preserved.')
        self.autosave_enabled.setChecked(bool(values.get('autosave_enabled',True)))
        self.autosave_interval.setValue(int(values.get('autosave_interval_s',60)))
        self.keep_versions.setValue(int(values.get('max_source_snapshots',30)))
        self.autosave_enabled.toggled.connect(self.update_autosave_settings)
        self.autosave_interval.valueChanged.connect(self.update_autosave_settings)
        self.keep_versions.valueChanged.connect(self.update_autosave_settings)
        return w
    def apply_autosave_settings(self):
        if self.autosave_enabled.isChecked():
            self.autosave.start(self.autosave_interval.value()*1000)
        else:self.autosave.stop()
    def update_autosave_settings(self,*_):
        data={'autosave_enabled':self.autosave_enabled.isChecked(),
              'autosave_interval_s':self.autosave_interval.value(),
              'max_source_snapshots':self.keep_versions.value()}
        try:
            atomic_write(self.root/'.chipcompiler'/'settings.json',json.dumps(data,indent=2))
            self.apply_autosave_settings()
            self.settings_message.setText('Saved project settings. Backup policy now active.')
        except OSError as exc:
            self.settings_message.setText('ERROR: Settings could not be saved: '+str(exc))
            self.logview.appendPlainText('[ERROR] Settings write failed: '+str(exc))

    def _history_page(self):
        w=QWidget();v=QVBoxLayout(w)
        tools=QHBoxLayout()
        for label,fn in [('Create snapshot',self.make_snapshot),('Restore selected snapshot',self.restore_backup),('Recover unsaved buffers',self.recover_unsaved),('Refresh history',self.refresh_history)]:
            button=QPushButton(label);button.clicked.connect(fn);tools.addWidget(button)
        v.addLayout(tools)
        v.addWidget(QLabel('Autosave snapshots are local and retained for 30 revisions by default. Restores make a pre-restore snapshot.'))
        split=QSplitter(Qt.Orientation.Horizontal)
        self.snapshots=QListWidget();self.snapshots.currentItemChanged.connect(self.show_snapshot)
        split.addWidget(self.snapshots)
        self.snapshot_detail=QPlainTextEdit();self.snapshot_detail.setReadOnly(True);split.addWidget(self.snapshot_detail)
        v.addWidget(split)
        return w
    def refresh_history(self):
        self.snapshots.clear()
        for p in sorted((self.root/'.chipcompiler'/'snapshots').glob('*.zip'),reverse=True):
            item=QListWidgetItem(p.name);item.setData(Qt.ItemDataRole.UserRole,str(p));self.snapshots.addItem(item)
    def show_snapshot(self,item,*_):
        if item is None:return
        path=Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            with zipfile.ZipFile(path) as z:
                names=[n for n in z.namelist() if n!='_snapshot_manifest.json']
                changed=[]
                for name in names:
                    local=self.root/name
                    if local.exists() and local.is_file() and local.stat().st_size<1_000_000:
                        old=z.read(name).decode('utf-8',errors='replace').splitlines()
                        new=local.read_text(encoding='utf-8',errors='replace').splitlines()
                        if old!=new:changed.append(name)
                self.snapshot_detail.setPlainText(f'Snapshot: {path.name}\nFiles: {len(names)}\nDifferences from working files:\n'+ '\n'.join(changed or ['(None found)'])+'\n\nDouble-check restore warning before overwriting working files.')
        except Exception as exc:self.snapshot_detail.setPlainText(str(exc))
    def recover_unsaved(self):
        folder=self.root/'.chipcompiler'/'unsaved'
        candidates=[p for p in folder.rglob('*') if p.is_file()] if folder.is_dir() else []
        if not candidates:
            QMessageBox.information(self,'Recovery','No unsaved buffer recovery files found.');return
        details='\n'.join(str(p.relative_to(folder)) for p in candidates)
        answer=QMessageBox.warning(self,'Recover unsaved buffers',
            f'Restore these editor recovery buffers to working files?\n\n{details}\n\nA pre-recovery backup will be created.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            snapshot(self.root,'pre-buffer-recovery')
            for source in candidates:
                destination=self.root/source.relative_to(folder)
                atomic_write(destination,source.read_bytes())
            self.populate_tree()
            self.statusBar().showMessage(f'Recovered {len(candidates)} editor buffers. Reopen files to reload contents.')
        except Exception as exc:QMessageBox.critical(self,'Recovery failed',str(exc))
    def make_snapshot(self):
        self.save_all()
        try:
            info=snapshot(self.root,'manual',max_versions=self.keep_versions.value());self.refresh_history()
            self.statusBar().showMessage('Snapshot saved: '+info['file'])
        except Exception as exc:QMessageBox.critical(self,'Snapshot failed',str(exc))
    def restore_backup(self):
        item=self.snapshots.currentItem();default=item.data(Qt.ItemDataRole.UserRole) if item else str(self.root/'.chipcompiler'/'snapshots')
        path,_=QFileDialog.getOpenFileName(self,'Restore a snapshot',str(default),'ZIP archives (*.zip)')
        if not path:return
        answer=QMessageBox.warning(self,'Confirm restoration','Restore this archive over working project files? A pre-restore backup is created automatically.',
             QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            self.save_all();restore(self.root,Path(path),confirm=True)
            while self.editors.count():self.editors.removeTab(0)
            self.populate_tree();self.refresh_history()
            self.dls=None;self.graph.show_dls(None)
            self.statusBar().showMessage('Restored archive; DLS must be regenerated before being trusted.')
        except Exception as exc:QMessageBox.critical(self,'Restore failed',str(exc))
    def closeEvent(self,event):
        try:
            if self.worker and self.worker.isRunning():
                QMessageBox.warning(self,'Build in progress','A build is running. Complete it before closing to preserve logs.');event.ignore();return
            self.save_all();snapshot(self.root,'clean-exit',max_versions=self.keep_versions.value())
            (self.root/'.chipcompiler'/'dirty_session.flag').unlink(missing_ok=True)
        except Exception as exc:
            QMessageBox.warning(self,'Could not complete clean shutdown',str(exc))
        super().closeEvent(event)

def launch(root:Path)->int:
    app=QApplication.instance() or QApplication([])
    app.setApplicationName('Chip Compiler')
    win=Window(Path(root));win.show()
    return app.exec()
