"""Local review UI for source copies and learned workflow versions."""
from pathlib import Path
import json
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFormLayout,QHBoxLayout,QLineEdit,QPlainTextEdit,QComboBox,QCheckBox,QFileDialog,QMessageBox

def sandbox_tab(panel,box):
    from core import development_sandbox as dev
    panel.info(box,'Work on a private source copy. Originals change only through Apply reviewed changes. This is file isolation, not a VM. Dependencies and private configuration are excluded.')
    form=QFormLayout();box.addLayout(form)
    root=panel.field(form,'Source project folder');goal=panel.field(form,'Change goal')
    copies=QComboBox();box.addWidget(copies);files=QComboBox();box.addWidget(files)
    editor=QPlainTextEdit();editor.setMaximumHeight(150);editor.setPlaceholderText('Select a copied file to inspect or edit. Save edits before checking.');box.addWidget(editor)
    output=QPlainTextEdit();output.setMaximumHeight(120);output.setReadOnly(True);box.addWidget(output)
    def key():
        value=copies.currentData()
        if not value:raise ValueError('Create or select a source copy.')
        return value
    def render(value):output.setPlainText(json.dumps(value,ensure_ascii=False,indent=2)[:150000]);panel.say('Result ready. Review the diff and check type before applying.')
    def load_files(*args):
        files.clear()
        if copies.currentData():files.addItems(sorted(dev.load(key())['files']))
    def load_file(*args):
        if files.currentText() and copies.currentData():editor.setPlainText(dev.read(key(),files.currentText()))
    copies.currentIndexChanged.connect(lambda:panel.call(load_files));files.currentTextChanged.connect(lambda:panel.call(load_file))
    def refresh(selected=None):
        current=selected or copies.currentData();copies.blockSignals(True);copies.clear()
        for row in dev.listing():copies.addItem(row['id']+' · '+row['goal'][:55]+' · '+row['root'],row['id'])
        i=copies.findData(current)
        if i>=0:copies.setCurrentIndex(i)
        copies.blockSignals(False);load_files()
    def choose():
        path=QFileDialog.getExistingDirectory(panel,'Select source project')
        if path:root.setText(path)
    def create():
        path=root.text();instruction=goal.text()
        panel.background(lambda:dev.create(path,instruction),lambda data:(refresh(data['id']),render(data)))
    row=QHBoxLayout();box.insertLayout(2,row)
    panel.button(row,'Choose folder',choose);panel.button(row,'Create source copy',create);panel.button(row,'Refresh copies',refresh)
    def save_edit():render(dev.edit(key(),files.currentText(),editor.toPlainText()))
    def ensure_saved():
        if files.currentText() and editor.toPlainText()!=dev.read(key(),files.currentText()).replace('\r\n','\n'):raise ValueError('Save the current copy edit before checking, testing, proposing or applying.')
    def checks():
        ensure_saved();selected=key();panel.background(lambda:dev.check(selected),render)
    def tests():
        ensure_saved();selected=key()
        if QMessageBox.question(panel,'Run project test code?', 'This runs Python unittest discovery from tests/ in the source copy for up to 45 seconds. Test code has your Mac user permissions and can access files/network outside this copy. Run only project code you trust. Continue?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        panel.background(lambda:dev.run_tests(selected),render)
    row=QHBoxLayout();box.addLayout(row)
    panel.button(row,'Save copy edit',save_edit);panel.button(row,'Review diff',lambda:render(dev.review(key())));panel.button(row,'Check Python / JSON / HTML',checks);panel.button(row,'Run Python unittest tests…',tests)
    selected=panel.field(form,'AI files (relative paths, separated by |)')
    def propose():
        ensure_saved();names=[x.strip() for x in selected.text().split('|') if x.strip()];identifier=key();instruction=goal.text()
        if not sharing.isChecked():raise ValueError('Enable sharing after reviewing the selected source files.')
        panel.background(lambda:dev.propose(identifier,names,instruction),render)
    sharing=QCheckBox('Share the explicitly selected copied files with my configured AI service for an edit proposal');box.addWidget(sharing)
    row=QHBoxLayout();box.addLayout(row);panel.button(row,'Generate AI proposal',propose);panel.button(row,'Stage proposal in copy',lambda:(render(dev.stage_proposal(key())),load_file()))
    def apply():
        ensure_saved();report=dev.review(key());render(report)
        if not report['changes']:raise ValueError('No changes to apply.')
        if QMessageBox.question(panel,'Apply this reviewed revision?', 'Apply the displayed copied-file changes to '+report['root']+'? Original hashes will be checked and the baseline kept for rollback.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:render(dev.promote(key()))
    def rollback():
        report=dev.review(key());render(report)
        if QMessageBox.question(panel,'Restore the saved originals?', 'Restore files previously applied from this sandbox? Rollback stops if those files have newer changes.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:render(dev.rollback(key()))
    def preview():
        name=files.currentText()
        if Path(name).suffix.lower()!='.html':raise ValueError('Select a copied HTML file. Other formats can be inspected in the editor.')
        path=dev.target(dev.directory(key())/'work',name);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)));panel.say('Opened the saved HTML copy in your browser; its scripts run as local webpage code.')
    row=QHBoxLayout();box.addLayout(row);panel.button(row,'Preview copied HTML',preview);panel.button(row,'Apply reviewed changes…',apply);panel.button(row,'Rollback applied changes…',rollback)
    refresh()

def skills_tab(panel,box):
    from core import skill_learning as learn
    panel.info(box,'Learn reusable mission recipes or supported Mac routines. Each edit creates an unapproved version. Teaching captures supported steps from routines you explicitly run; it does not record other activity.')
    form=QFormLayout();box.addLayout(form);name=panel.field(form,'Skill name');source=panel.field(form,'Routine name or completed mission ID');city=panel.field(form,'City for this restaurant run')
    versions=QComboBox();box.addWidget(versions);definition=QPlainTextEdit();definition.setMaximumHeight(160);box.addWidget(definition);report=QPlainTextEdit();report.setMaximumHeight(140);report.setReadOnly(True);box.addWidget(report)
    reviewed=[None]
    def show(data):
        reviewed[0]=data;name.setText(data['name']);definition.setPlainText(json.dumps(data['definition'],ensure_ascii=False,indent=2));report.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
    def load(*args):
        value=versions.currentData()
        if value:show(learn.get(*value))
    def refresh(selected=None):
        versions.blockSignals(True);versions.clear()
        for row in learn.listing():versions.addItem(f'{row["name"]} · v{row["version"]} · '+('APPROVED' if row['approved'] else 'DRAFT'),(row['name'],row['version']))
        if selected:
            index=versions.findData((selected['name'],selected['version']))
            if index>=0:versions.setCurrentIndex(index)
        versions.blockSignals(False);load()
    versions.currentIndexChanged.connect(lambda:panel.call(load))
    def saved(data):refresh(data);show(data);panel.say('Draft saved. Review this exact version before approval or execution.')
    def approve():
        data=reviewed[0]
        if not data:raise ValueError('Select a version first.')
        if json.loads(definition.toPlainText())!=data['definition']:raise ValueError('Save your edits as a new version before approving.')
        saved(learn.approve(data['name'],data['version'],data['fingerprint']));panel.say('This exact version is approved. Run is still an explicit action.')
    def run():
        data=reviewed[0]
        if not data:raise ValueError('Select a version first.')
        if json.loads(definition.toPlainText())!=data['definition']:raise ValueError('Unsaved edits: save and approve a new version before running.')
        location=city.text();city.clear();player=getattr(panel.host,'_mission_player',None)
        panel.background(lambda:learn.run(data['name'],data['version'],location,player),lambda value:report.setPlainText(json.dumps(value,ensure_ascii=False,indent=2)))
    row=QHBoxLayout();box.addLayout(row);panel.button(row,'Learn from saved routine',lambda:saved(learn.from_routine(name.text(),source.text())));panel.button(row,'Learn from completed mission',lambda:saved(learn.from_mission(name.text(),source.text())));panel.button(row,'Save new version',lambda:saved(learn.save(name.text(),json.loads(definition.toPlainText()))))
    row=QHBoxLayout();box.addLayout(row);panel.button(row,'Begin teaching',lambda:report.setPlainText(json.dumps(learn.begin(name.text()),indent=2)));panel.button(row,'Stop teaching / save draft',lambda:saved(learn.finish()));panel.button(row,'Refresh versions',refresh)
    row=QHBoxLayout();box.addLayout(row);panel.button(row,'Approve reviewed version',approve);panel.button(row,'Revoke approval',lambda:saved(learn.revoke(reviewed[0]['name'],reviewed[0]['version'])));panel.button(row,'Run selected version',run)
    definition.setPlaceholderText('{"type":"routine","steps":[{"action":"open_app","app":"Safari"}]}');refresh()
