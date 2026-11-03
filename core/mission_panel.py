"""Mission Control: plans, checkpoints, evidence, maps and local integrations."""
from pathlib import Path
import json,threading
from PyQt6.QtCore import Qt,QTimer,QUrl,pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QPushButton,QComboBox,QListWidget,QTabWidget,QWidget,QSpinBox,QCheckBox,QFileDialog,QAbstractItemView,QScrollArea,QStackedWidget,QToolButton,QMenu)
from core import mission_store as store
from core.mission_engine import engine

class MissionPanel(QDialog):
    finished=pyqtSignal(object)
    def __init__(self,parent):
        super().__init__(parent);self.host=parent;self.service=engine();self.jobs=0
        self.setWindowTitle('JARVIS Mission Control');self.resize(1040,800)
        self.setStyleSheet('QWidget{background:#06151e;color:#d4eef4;} QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox{background:#102935;color:#e3f7fa;border:1px solid #285061;padding:5px;} QPushButton{background:#16465a;color:#e2f5ff;border:1px solid #3286a3;padding:8px;border-radius:5px;} QPushButton:hover{background:#226079;} QTabBar::tab{padding:10px;}')
        layout=QVBoxLayout(self);title=QLabel('MISSION CONTROL  /  Plan · Act · Verify');title.setStyleSheet('font-size:22px;font-weight:bold;padding:8px;');layout.addWidget(title)
        navigation=QHBoxLayout();layout.addLayout(navigation)
        pages=QStackedWidget();layout.addWidget(pages);self.message=QLabel('Ready. Create a plan, inspect it, then start.');self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.message)
        self._tool_pages={};self._pages=pages
        more=QToolButton();more.setText('More tools');more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(more);more.setMenu(menu)
        for name,build in [('Missions',self._missions),('Sandbox',self._sandbox),('Skills',self._skills),('Earth intelligence',self._earth),('Briefing',self._briefing),('Smart home',self._home),('Voice & screen',self._voice_screen),('Portable memory',self._portable),('Scenario simulator',self._scenarios)]:
            page=QWidget();box=QVBoxLayout(page);build(box);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);index=pages.addWidget(scroll);self._tool_pages[name]=index
            if name in ('Missions','Sandbox','Skills'):
                button=QPushButton(name);button.clicked.connect(lambda checked=False,i=index:pages.setCurrentIndex(i));navigation.addWidget(button)
            else:
                action=menu.addAction(name);action.triggered.connect(lambda checked=False,i=index:pages.setCurrentIndex(i))
        navigation.addStretch();navigation.addWidget(more)
        self.finished.connect(self._finish)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(2000);self.refresh()
    def say(self,text):self.message.setText(str(text))
    def call(self,fn):
        try:return fn()
        except Exception as exc:self.say(exc)
    def button(self,layout,text,fn):
        b=QPushButton(text);b.clicked.connect(lambda:self.call(fn));layout.addWidget(b);return b
    def field(self,form,label,placeholder=''):
        w=QLineEdit();w.setPlaceholderText(placeholder);form.addRow(label,w);return w
    def info(self,layout,text):
        w=QLabel(text);w.setWordWrap(True);w.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(w)
    def background(self,fn,callback):
        if self.jobs>=2:raise ValueError('Two requests are already running. Wait for a result before starting another.')
        self.jobs+=1;self.say('Working in the background…')
        def work():
            try:value=fn();result=(callback,value,None)
            except Exception as exc:result=(callback,None,str(exc))
            self.finished.emit(result)
        threading.Thread(target=work,daemon=True).start()
    def _finish(self,result):
        self.jobs-=1;callback,value,error=result
        if error:self.say(error)
        else:self.call(lambda:callback(value))
    def key(self):
        key=self.mission_list.currentData()
        if not key:raise ValueError('Select a mission first.')
        return key
    def _missions(self,box):
        form=QFormLayout();box.addLayout(form)
        self.kind=QComboBox();self.kind.addItems(['research','restaurants','engineering','routine','briefing']);form.addRow('Mission type',self.kind)
        self.goal=self.field(form,'Goal','What should JARVIS research or review?')
        self.city=self.field(form,'City for this search','Required each restaurant search — include country/state')
        self.radius=QSpinBox();self.radius.setRange(500,10000);self.radius.setValue(5000);form.addRow('Restaurant radius (m)',self.radius)
        self.limit=QSpinBox();self.limit.setRange(1,30);self.limit.setValue(12);form.addRow('Maximum candidates',self.limit)
        self.root=self.field(form,'Project folder','Engineering review only')
        self.routine=self.field(form,'Saved routine name','Create routines in Projects & Workspace first')
        self.selected_files=self.field(form,'Files for AI review','Relative paths separated by |; up to 6')
        self.ai=QCheckBox('Use AI synthesis (research evidence / explicitly selected project files go to your configured AI service)');box.addWidget(self.ai)
        row=QHBoxLayout();box.addLayout(row);self.button(row,'Choose project folder',self.choose_root);self.button(row,'Preview selected files',self.preview_files);self.button(row,'Create plan',self.plan)
        self.mission_list=QComboBox();box.addWidget(self.mission_list);self.mission_list.currentIndexChanged.connect(self.render)
        row=QHBoxLayout();box.addLayout(row)
        for text,fn in [('Start / resume',self.start),('Pause',lambda:self.stop(True)),('Cancel',lambda:self.stop(False)),('Open evidence folder',self.open_folder),('Plot leads',self.plot)]:self.button(row,text,fn)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);box.addWidget(self.details,1)
        row=QHBoxLayout();box.addLayout(row)
        self.lead=QSpinBox();self.lead.setRange(1,30);row.addWidget(QLabel('Candidate number'));row.addWidget(self.lead);self.button(row,'Create private website concept',self.draft)
        self.note=QLineEdit();self.note.setPlaceholderText('Correction / decision to save with this mission');row.addWidget(self.note);self.button(row,'Save note',self.save_note)
        self.kind.currentTextChanged.connect(self._kind_fields);self._kind_fields()
    def _kind_fields(self):
        kind=self.kind.currentText()
        for field,enabled in [(self.goal,kind in ('research','engineering')),(self.city,kind=='restaurants'),(self.radius,kind=='restaurants'),(self.limit,kind=='restaurants'),(self.root,kind=='engineering'),(self.routine,kind=='routine'),(self.selected_files,kind=='engineering'),(self.ai,kind in ('research','engineering'))]:field.setEnabled(enabled)
    def choose_root(self):
        value=QFileDialog.getExistingDirectory(self,'Choose project folder')
        if value:self.root.setText(value)
    def preview_files(self):
        from core.engineering_workspace import read
        root=self.root.text();names=[x.strip() for x in self.selected_files.text().split('|') if x.strip()]
        if not names:raise ValueError('Enter relative file paths, separated by |, first.')
        if len(names)>6:raise ValueError('Select up to six files.')
        self.details.setPlainText('\n\n'.join('FILE: '+n+'\n'+read(root,n) for n in names));self.say('Local preview only. AI receives these excerpts only if you enable AI synthesis and start an engineering mission.')
    def plan(self):
        kind=self.kind.currentText();params={'city':self.city.text(),'radius':self.radius.value(),'limit':self.limit.value(),'root':self.root.text(),'name':self.routine.text(),'files':[x.strip() for x in self.selected_files.text().split('|') if x.strip()],'ai':self.ai.isChecked()}
        item=self.service.plan(kind,self.goal.text(),**params);self.city.clear();self.refresh(item['id']);self.say('Plan saved. Review its steps and start when ready.')
    def start(self):self.service.start(self.key(),getattr(self.host,'_mission_player',None));self.refresh();self.say('Queued. You can continue using JARVIS while this mission runs.')
    def stop(self,pause):self.service.stop(self.key(),pause);self.refresh()
    def refresh(self,select=None):
        current=select or self.mission_list.currentData();rows=store.listing()
        signature=tuple((r['id'],r['state'],r['updated'],r['error']) for r in rows)
        if select is None and getattr(self,'_last_signature',None)==signature:return
        self._last_signature=signature
        self.mission_list.blockSignals(True);self.mission_list.clear()
        for row in rows:self.mission_list.addItem(f'{row["state"].upper()} · {row["goal"][:85]} · {row["id"]}',row['id'])
        index=self.mission_list.findData(current)
        if index>=0:self.mission_list.setCurrentIndex(index)
        self.mission_list.blockSignals(False);self.render()
    def render(self,*args):
        key=self.mission_list.currentData()
        if not key:return
        data=store.get(key);lines=[data['goal'],f'State: {data["state"]} | ID: {key}',json.dumps(data['params'],ensure_ascii=False,indent=2)]
        if data['error']:lines+=['ERROR: '+data['error']]
        for s in data['steps']:lines += [f'\n{s["position"]+1}. [{s["state"]}] {s["title"]}',json.dumps(s['result'],ensure_ascii=False,indent=2) if s['result'] else '']
        lines+=['\nACTIVITY']+[e['created']+' '+e['message'] for e in data['events']]
        scroll=self.details.verticalScrollBar().value();self.details.setPlainText('\n'.join(lines)[:100000]);self.details.verticalScrollBar().setValue(scroll)
    def open_folder(self):QDesktopServices.openUrl(QUrl.fromLocalFile(str(store.folder(self.key()))))
    def plot(self):
        from actions.earth_research import research
        self.say(research({'action':'mission_markers','id':self.key()},player=getattr(self.host,'_mission_player',None)))
    def draft(self):
        from core.mission_workflows import draft_website
        path=draft_website(self.key(),self.lead.value()-1);QDesktopServices.openUrl(QUrl.fromLocalFile(path));self.say('Private website concept saved and opened. It has not been published or sent.')
    def save_note(self):
        note=self.note.text().strip()
        if not note or len(note)>1000:raise ValueError('Enter a correction or decision of up to 1000 characters.')
        store.event(self.key(),'User correction/note: '+note);self.note.clear();self.render();self.say('Note saved for review. Cancel and re-plan if this changes a running mission’s goal.')
    def _earth(self,box):
        self.info(box,'Find public cities, plot mission research and estimate driving routes. City searches go to the configured geocoder; route endpoints go to OSRM. No live traffic. Do not enter private addresses. © OpenStreetMap contributors.')
        form=QFormLayout();box.addLayout(form);self.map_city=self.field(form,'City','City, state, country')
        self.button(box,'Find city on map',self.find_city)
        self.other_city=self.field(form,'Compare with city/area')
        self.button(box,'Compare areas in background',self.compare_areas)
        self.route_fields=[]
        for label in ('Start latitude','Start longitude','End latitude','End longitude'):self.route_fields.append(self.field(form,label))
        self.button(box,'Estimate driving route',self.find_route)
        self.map_output=QPlainTextEdit();self.map_output.setReadOnly(True);box.addWidget(self.map_output)
        self.info(box,'Public Nominatim use: explicit requests only, cached city results, at most one request per second; no autocomplete or bulk geocoding. Policy: operations.osmfoundation.org/policies/nominatim/ . Provider URLs can be changed in config/place-services.json.')
    def find_city(self):
        from core.place_intelligence import city_lookup
        city=self.map_city.text();self.background(lambda:city_lookup(city),self.city_result)
    def city_result(self,data):
        player=getattr(self.host,'_mission_player',None)
        if player:player.show_earth({'view':'street','latitude':data['latitude'],'longitude':data['longitude'],'zoom':12})
        self.map_output.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.say('Map requested. Return to the main JARVIS window to explore.')
    def compare_areas(self):
        a=self.map_city.text().strip();b=self.other_city.text().strip()
        if not a or not b:raise ValueError('Enter both public cities/areas.')
        item=self.service.plan('research',f'Compare {a} and {b}: restaurants, transport, amenities and uncertainties, citing current sources.')
        self.service.start(item['id']);self.refresh(item['id']);self.say('Comparison mission started. Review its evidence in the Missions tab.')
    def find_route(self):
        from core.place_intelligence import route
        values=[float(f.text()) for f in self.route_fields];self.background(lambda:route(values[:2],values[2:]),self.route_result)
    def route_result(self,data):
        player=getattr(self.host,'_mission_player',None)
        if player:player.show_earth({'view':'street','route':data})
        self.map_output.setPlainText(f'Distance: {data["distance_m"]/1000:.1f} km\nEstimated driving time: {data["duration_s"]/60:.0f} min\n{data["note"]}');self.say('Route ready on the Earth panel.')
    def _briefing(self,box):
        from core.personal_briefing import schedule
        self.info(box,'Your local briefing combines active project tasks, mission progress and an imported calendar snapshot. Import an .ics export to include calendar events; this does not connect or synchronize a cloud account.')
        row=QHBoxLayout();box.addLayout(row);self.button(row,'Import calendar .ics',self.import_calendar);self.button(row,'Refresh briefing',self.refresh_briefing)
        self.briefing=QPlainTextEdit();self.briefing.setReadOnly(True);box.addWidget(self.briefing)
        config=schedule();self.daily=QCheckBox('Show a daily briefing while JARVIS is running');self.daily.setChecked(config['enabled']);box.addWidget(self.daily)
        row=QHBoxLayout();box.addLayout(row);self.hour=QSpinBox();self.hour.setRange(0,23);self.hour.setValue(config['hour']);self.minute=QSpinBox();self.minute.setRange(0,59);self.minute.setValue(config['minute']);row.addWidget(QLabel('Local time (24h)'));row.addWidget(self.hour);row.addWidget(self.minute);self.button(row,'Save schedule',self.save_schedule)
    def import_calendar(self):
        from core.personal_briefing import import_calendar
        path,_=QFileDialog.getOpenFileName(self,'Import calendar export','','Calendar (*.ics)')
        if path:self.background(lambda:import_calendar(path),lambda _:self.refresh_briefing())
    def refresh_briefing(self):
        from core.personal_briefing import build
        self.background(build,lambda data:(self.briefing.setPlainText(json.dumps(data,ensure_ascii=False,indent=2)),self.say('Local briefing ready.')))
    def save_schedule(self):
        from core.personal_briefing import save_schedule
        save_schedule(self.daily.isChecked(),self.hour.value(),self.minute.value());self.say('Schedule saved. JARVIS must be running; it cannot wake a sleeping Mac.')
    def _home(self,box):
        from core.home_bridge import status
        self.info(box,'Set up later with your own Home Assistant server. Only explicitly listed light.* and switch.* entities can be controlled. The token stays in a private local configuration file; it is never included in voice tools, mission reports or AI prompts.')
        form=QFormLayout();box.addLayout(form);self.home_url=self.field(form,'Server origin','http://homeassistant.local:8123');self.home_token=self.field(form,'Long-lived access token');self.home_token.setEchoMode(QLineEdit.EchoMode.Password);self.home_entities=self.field(form,'Allowed entities','light.desk, switch.fan')
        configured=status()
        if configured['configured']:self.home_url.setText(configured['url']);self.home_entities.setText(', '.join(configured['entities']))
        row=QHBoxLayout();box.addLayout(row);self.button(row,'Save connection',self.save_home);self.button(row,'Read allowed device states',self.read_home);self.button(row,'Disconnect',self.disconnect_home)
        self.home_output=QPlainTextEdit();self.home_output.setReadOnly(True);self.home_output.setPlainText(json.dumps(configured,indent=2));box.addWidget(self.home_output)
    def save_home(self):
        from core.home_bridge import setup
        data=setup(self.home_url.text(),self.home_token.text(),self.home_entities.text().split(','));self.home_token.clear();self.home_output.setPlainText(json.dumps(data,indent=2));self.say('Connection saved locally. Read device states to test it.')
    def read_home(self):
        from core.home_bridge import states
        self.background(states,lambda data:(self.home_output.setPlainText(json.dumps(data,indent=2)),self.say('Device state result ready.')))
    def disconnect_home(self):
        from core.home_bridge import disconnect
        self.home_output.setPlainText(json.dumps(disconnect(),indent=2));self.home_token.clear()
    def _voice_screen(self,box):
        self.info(box,'Use JARVIS’s existing interruption, speech corrections and Fast response profile for natural conversation. Screen co-pilot follows only the target you select in Projects & Workspace, shares changed screenshots with your configured vision service, and offers suggestions while you are idle. It does not click or execute screenshot instructions.')
        from core.voice_interaction import enabled,set_enabled
        self.voice_interrupt=QCheckBox('Voice interruption (experimental; headphones recommended)');self.voice_interrupt.setChecked(enabled());box.addWidget(self.voice_interrupt)
        self.voice_interrupt.toggled.connect(lambda value:self.call(lambda:set_enabled(value)))
        self.button(box,'Open project memory, screen target and routines',self.host._open_work_panel)
        self.button(box,'Analyze selected screen now',lambda:self.send('/screen analyze'))
        self.button(box,'Start screen co-pilot',lambda:self.send('/screen watch'))
        self.button(box,'Stop screen sharing',lambda:self.send('/screen stop'))
        self.button(box,'Show voice response diagnostics',lambda:self.send('/perf'))
        self.info(box,'Voice examples: “Start a research mission about…” · “Find restaurant website leads in [city]” · “Pause mission…” · “Give me my briefing” · “Show my mission leads on the map” · “Turn on my desk light”. Say “Actually…” to correct a request; durable mission goal changes need cancellation and a new plan.')
        box.addStretch()
    def send(self,text):
        if self.host.on_text_command:threading.Thread(target=self.host.on_text_command,args=(text,),daemon=True).start()
        self.say('Command requested: '+text)
    def closeEvent(self,event):self.timer.stop();super().closeEvent(event)

    def _sandbox(self,box):
        from core.development_panel import sandbox_tab
        sandbox_tab(self,box)
    def _skills(self,box):
        from core.development_panel import skills_tab
        skills_tab(self,box)


    def show_page(self,name):
        self._pages.setCurrentIndex(self._tool_pages[name])
    def _portable(self,box):
        from core.portability_scenario_panel import memory_view
        memory_view(self,box)
    def _scenarios(self,box):
        from core.portability_scenario_panel import scenario_view
        scenario_view(self,box)
