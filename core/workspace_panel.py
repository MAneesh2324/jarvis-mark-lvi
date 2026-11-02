"""User-facing controls for project work, routines and scoped screen help."""
from pathlib import Path
import threading
from PyQt6.QtCore import Qt,QTimer,QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QPushButton,QComboBox,QListWidget,QListWidgetItem,QTabWidget,QWidget,QSpinBox)


class WorkspacePanel(QDialog):
    def __init__(self,parent):
        super().__init__(parent)
        self.host=parent;self.steps=[]
        self.setWindowTitle('JARVIS Workspace')
        self.resize(720,660)
        self.setStyleSheet('QDialog,QWidget{background:#001018;color:#b8ebf2;} QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox{background:#001e2a;color:#e2f8fa;border:1px solid #12516a;padding:5px;} QPushButton{background:#00354a;color:#dcfbff;border:1px solid #16748c;border-radius:4px;padding:7px;} QPushButton:hover{background:#07536b;} QTabBar::tab{padding:8px;} QLabel{border:none;}')
        outer=QVBoxLayout(self);tabs=QTabWidget();outer.addWidget(tabs)
        self.status=QLabel('');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.status)
        for name,build in [('Projects',self._projects),('Routines',self._routines),('Screen focus',self._screen),('Local voice',self._voice),('Recording notes',self._notes)]:
            page=QWidget();layout=QVBoxLayout(page);build(layout);layout.addStretch();tabs.addTab(page,name)
        self._timer=QTimer(self);self._timer.timeout.connect(self._refresh_voice);self._timer.start(1000)

    def _message(self,text):self.status.setText(str(text))
    def _call(self,fn):
        try:fn()
        except Exception as exc:self._message(exc)
    def _send(self,text):
        if self.host.on_text_command:threading.Thread(target=self.host.on_text_command,args=(text,),daemon=True).start()
    def _button(self,layout,text,fn):
        button=QPushButton(text);button.clicked.connect(lambda:self._call(fn));layout.addWidget(button);return button
    def _field(self,form,label):
        field=QLineEdit();form.addRow(label,field);return field

    def _projects(self,layout):
        from core import work_projects as store
        self.projects=QComboBox();layout.addWidget(self.projects)
        self._button(layout,'Refresh projects',self._refresh_projects)
        form=QFormLayout();layout.addLayout(form)
        self.project_name=self._field(form,'Project name')
        self.project_goal=self._field(form,'Goal')
        self.project_progress=self._field(form,'Progress so far')
        self.project_next=self._field(form,'Next step')
        self.project_root=self._field(form,'Project folder (optional)')
        self._button(layout,'Save and use this project',self._save_project)
        self.tasks=QListWidget();self.tasks.setMaximumHeight(150);layout.addWidget(self.tasks)
        self.task_text=QLineEdit();self.task_text.setPlaceholderText('New task for this project');layout.addWidget(self.task_text)
        self._button(layout,'Add task',self._add_task)
        self._button(layout,'Toggle selected task complete',self._toggle_task)
        self.projects.currentTextChanged.connect(self._load_project)
        self._refresh_projects()

    def _refresh_projects(self):
        from core import work_projects as store
        self.projects.blockSignals(True);self.projects.clear();self.projects.addItem('New project')
        self.projects.addItems([r['name'] for r in store.list_projects()]);self.projects.blockSignals(False)
        active=store.active_name()
        self.projects.setCurrentText(active or 'New project');self._load_project(self.projects.currentText())

    def _load_project(self,name):
        from core.work_projects import project
        data=project(name) if name!='New project' else None
        for field,key in [(self.project_name,'name'),(self.project_goal,'goal'),(self.project_progress,'progress'),(self.project_next,'next_step'),(self.project_root,'root')]:field.setText(data.get(key,'') if data else '')
        self.tasks.clear()
        for row in (data or {}).get('tasks',[]):
            item=QListWidgetItem(('✓ ' if row['done'] else '○ ')+row['text']);item.setData(Qt.ItemDataRole.UserRole,row);self.tasks.addItem(item)

    def _save_project(self):
        from core import work_projects as store
        name=self.project_name.text().strip()
        store.save_project(name,self.project_goal.text(),self.project_progress.text(),self.project_next.text(),self.project_root.text());store.activate(name)
        self._refresh_projects();self._message('Project saved and active. New screen analysis will use this goal.')
    def _add_task(self):
        from core.work_projects import add_task
        add_task(self.task_text.text(),self.project_name.text());self.task_text.clear();self._load_project(self.project_name.text())
    def _toggle_task(self):
        from core.work_projects import task_done
        item=self.tasks.currentItem()
        if not item:raise ValueError('Select a task first.')
        row=item.data(Qt.ItemDataRole.UserRole);task_done(row['id'],not row['done']);self._load_project(self.project_name.text())

    def _routines(self,layout):
        self.routines=QComboBox();layout.addWidget(self.routines)
        self._button(layout,'Load selected routine',self._load_routine)
        self.routine_name=QLineEdit();self.routine_name.setPlaceholderText('Routine name, such as Start work');layout.addWidget(self.routine_name)
        self.step_kind=QComboBox();self.step_kind.addItems(['Open app','Open folder or document','Arrange app window','Set volume','Activate project']);layout.addWidget(self.step_kind)
        self.step_value=QLineEdit();self.step_value.setPlaceholderText('App name, path, volume 0–100, or project name');layout.addWidget(self.step_value)
        self.step_position=QComboBox();self.step_position.addItems(['left','right','maximize']);layout.addWidget(self.step_position)
        self._button(layout,'Add step',self._add_step)
        self.step_list=QListWidget();layout.addWidget(self.step_list)
        self._button(layout,'Remove selected step',self._remove_step)
        self._button(layout,'Save routine',self._save_routine)
        self._button(layout,'Run saved routine',lambda:self._send('/routine '+self.routine_name.text()))
        self._refresh_routines()
    def _refresh_routines(self):
        from core.work_routines import list_routines
        self.routines.clear();self.routines.addItems([r['name'] for r in list_routines()])
    def _load_routine(self):
        from core.work_routines import preview
        data=preview(self.routines.currentText());self.routine_name.setText(data['name']);self.steps=data['steps'];self._render_steps()
    def _add_step(self):
        kind=self.step_kind.currentIndex();value=self.step_value.text().strip()
        if kind==0:step={'action':'open_app','app':value}
        elif kind==1:step={'action':'open_path','path':value}
        elif kind==2:step={'action':'arrange_app','app':value,'position':self.step_position.currentText()}
        elif kind==3:step={'action':'volume','percent':int(value)}
        else:step={'action':'activate_project','name':value}
        from core.work_routines import validate
        self.steps=validate(self.steps+[step]);self._render_steps()
    def _render_steps(self):
        self.step_list.clear()
        for i,step in enumerate(self.steps,1):self.step_list.addItem(f"{i}. "+step['action'].replace('_',' ')+' — '+', '.join(str(v) for k,v in step.items() if k!='action'))
    def _remove_step(self):
        index=self.step_list.currentRow()
        if index>=0:self.steps.pop(index);self._render_steps()
    def _save_routine(self):
        from core.work_routines import save
        save(self.routine_name.text(),self.steps);self._refresh_routines();self._message('Routine saved. Run executes these listed steps and reports each result.')

    def _screen(self,layout):
        info=QLabel('Choose what AI analysis may see. This does not change the independent whole-display video recording. Region capture includes visible overlapping windows.');info.setWordWrap(True);layout.addWidget(info)
        self.scope_mode=QComboBox();self.scope_mode.addItems(['Display','Window','Region']);layout.addWidget(self.scope_mode)
        form=QFormLayout();layout.addLayout(form)
        self.monitor=QSpinBox();self.monitor.setRange(1,16);form.addRow('Display',self.monitor)
        self.windows=QComboBox();form.addRow('Window',self.windows)
        self._button(layout,'Refresh visible windows',self._refresh_windows)
        self.region={}
        for key in ('left','top','width','height'):
            field=QSpinBox();field.setRange(-20000 if key in ('left','top') else 32,20000 if key in ('left','top') else 8192);field.setValue(640 if key=='width' else 480 if key=='height' else 0);form.addRow(key.title(),field);self.region[key]=field
        self._button(layout,'Use selected screen target',self._save_target)
        self._button(layout,'Analyze now',lambda:self._send('/screen analyze'))
        self._button(layout,'Diagnose visible error',lambda:self._send('/screen diagnose'))
        self._button(layout,'Check my fix against before/after',lambda:self._send('/screen check'))
        self._button(layout,'Open macOS Screen Recording settings',lambda:QDesktopServices.openUrl(QUrl('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture')))
    def _refresh_windows(self):
        from core.screen_focus import windows
        self.windows.clear()
        for row in windows():self.windows.addItem(row['app']+' — '+row['title'],row['window_id'])
    def _save_target(self):
        from core.screen_focus import select
        mode=('display','window','region')[self.scope_mode.currentIndex()]
        data=select(mode,self.monitor.value(),self.windows.currentData(),{k:v.value() for k,v in self.region.items()})
        self._message('Analysis target selected: '+str(data))

    def _voice(self,layout):
        text=QLabel('Local command mode uses a small speech model on this Mac. It understands a limited English command grammar; it does not send command audio to Gemini. Turn it off to return to ordinary conversation. Its spoken replies use the macOS system voice.');text.setWordWrap(True);layout.addWidget(text)
        self.voice_status=QLabel('');layout.addWidget(self.voice_status)
        self._button(layout,'Toggle local voice mode',lambda:self._send('/localvoice toggle'))
        help=QLabel('Try: “open Safari”, “volume 30”, “timer 5 minutes”, “remember coffee is black”, “recall coffee”, “run routine Start work”, “project status”, “what time is it”.\n\nTimers are saved locally. JARVIS must be running to announce them; overdue timers announce once at the next startup.');help.setWordWrap(True);layout.addWidget(help)
        self.local_text=QLineEdit();self.local_text.setPlaceholderText('Or type a local command here');layout.addWidget(self.local_text)
        self._button(layout,'Run local command',lambda:self._send('/local '+self.local_text.text()))
        self._refresh_voice()
    def _refresh_voice(self):
        getter=getattr(self.host,'local_voice_status',None)
        state=getter() if getter else {'enabled':False,'state':'not connected'}
        self.voice_status.setText('Local microphone mode: '+state['state'])

    def _notes(self,layout):
        from core.screen_workspace import RECORDINGS
        info=QLabel('Highlights use sampled recording keyframes and your timestamped markers, not audio transcription or every video frame. Summarize shares those samples with your configured vision model.');info.setWordWrap(True);layout.addWidget(info)
        self.recordings=QComboBox();layout.addWidget(self.recordings)
        self._button(layout,'Refresh recordings',self._refresh_recordings)
        self.marker=QLineEdit();self.marker.setPlaceholderText('Mark a decision, problem or useful moment in the current recording');layout.addWidget(self.marker)
        self._button(layout,'Add timestamped marker',self._mark)
        self._button(layout,'Summarize selected recording',self._summarize)
        self._button(layout,'Open saved highlights',self._open_highlights)
        self._refresh_recordings()
    def _refresh_recordings(self):
        from core.screen_workspace import RECORDINGS
        self.recordings.clear()
        for path in sorted(RECORDINGS.glob('*.mp4'),reverse=True):self.recordings.addItem(path.name,str(path))
    def _mark(self):
        from core.screen_workspace import workspace
        result=workspace.recorder.mark(self.marker.text());self._message(f"Marker saved at {result['seconds']} seconds.");self.marker.clear()
    def _summarize(self):
        from core.recording_notes import load
        from core.screen_workspace import workspace
        video,data=load(self.recordings.currentData() or '')
        workspace.request_job('highlights','Summarize useful moments.',{'video':str(video)});self._message('Summary queued for the connected vision conversation. The report will be saved beside the recording.')
    def _open_highlights(self):
        value=self.recordings.currentData()
        if not value:raise ValueError('Select a recording.')
        path=Path(value).with_suffix('.highlights.md')
        if not path.exists():raise ValueError('No saved highlights yet. Summarize this recording first.')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
