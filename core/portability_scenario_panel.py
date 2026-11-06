"""Local-only vault passphrases and scenario controls. No new tab bar."""
import json
from pathlib import Path
from PyQt6.QtCore import Qt,QPointF
from PyQt6.QtGui import QColor,QPainter,QPen,QPolygonF
from PyQt6.QtWidgets import QFormLayout,QHBoxLayout,QLineEdit,QPlainTextEdit,QCheckBox,QFileDialog,QMessageBox,QComboBox,QWidget

class ScenarioChart(QWidget):
 def __init__(self):super().__init__();self.rows=[];self.setMinimumHeight(200);self.setMaximumHeight(260)
 def set_result(self,result):self.rows=result.get('fan_chart',[]);self.unit=result.get('x_unit','trading days');self.update()
 def paintEvent(self,event):
  painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.fillRect(self.rect(),QColor('#081b27'));painter.setPen(QColor('#c9eaf3'))
  if not self.rows:painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Run a forex scenario to show its conditional percentile band.');return
  left,top=70,30;width=max(1,self.width()-100);height=max(1,self.height()-70);values=[r[k] for r in self.rows for k in ('p05','median','p95')];lo,hi=min(values),max(values);span=max(hi-lo,abs(hi)*.01,1e-8);lo-=span*.05;hi+=span*.05
  def point(row,key):return QPointF(left+width*row['day']/max(1,self.rows[-1]['day']),top+height*(hi-row[key])/(hi-lo))
  polygon=QPolygonF([point(r,'p05') for r in self.rows]+[point(r,'p95') for r in reversed(self.rows)]);painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(0,190,220,65));painter.drawPolygon(polygon)
  painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#18d3ed'),2));painter.drawPolyline(QPolygonF([point(r,'median') for r in self.rows]))
  painter.setPen(QColor('#c9eaf3'));painter.drawText(10,25,f'{hi:.5g}');painter.drawText(10,top+height,f'{lo:.5g}');painter.drawText(left,top+height+25,'0');painter.drawText(left+width-100,top+height+25,str(self.rows[-1]['day'])+' '+getattr(self,'unit','trading days'));painter.drawText(left,18,'Conditional 5th–95th percentile band / median. Not a forecast.')

def memory_view(panel,box):
 from core import portable_memory as vault
 panel.info(box,'Create an encrypted local memory vault to move between your devices. Credentials, recordings, app binaries and macOS permissions are excluded. Choose a strong passphrase; it cannot be recovered. Nothing is uploaded automatically.')
 form=QFormLayout();box.addLayout(form);path=panel.field(form,'Vault file (.jarvismem)');password=panel.field(form,'Vault passphrase (12+ characters)');password.setEchoMode(QLineEdit.EchoMode.Password);confirm=panel.field(form,'Repeat passphrase (export only)');confirm.setEchoMode(QLineEdit.EchoMode.Password)
 history=QCheckBox('Include saved conversation text and summaries (personal data)');box.addWidget(history);report=QPlainTextEdit();report.setReadOnly(True);box.addWidget(report);loaded=[None]
 def show(value):report.setPlainText(json.dumps(value,ensure_ascii=False,indent=2))
 def choose_export():
  value,_=QFileDialog.getSaveFileName(panel,'Save encrypted JARVIS memory','JARVIS-memory.jarvismem','JARVIS memory (*.jarvismem)')
  if value:path.setText(value)
 def choose_import():
  value,_=QFileDialog.getOpenFileName(panel,'Choose encrypted memory vault','','JARVIS memory (*.jarvismem)')
  if value:path.setText(value);loaded[0]=None
 def export():
  if password.text()!=confirm.text():raise ValueError('The passphrases do not match.')
  destination=path.text();phrase=password.text();include=history.isChecked();password.clear();confirm.clear()
  panel.background(lambda:vault.export(destination,phrase,include),lambda data:(show(data),panel.say('Encrypted vault saved locally. Keep the passphrase separately; it is not stored by JARVIS.')))
 def preview():
  source=path.text();phrase=password.text();password.clear();confirm.clear();loaded[0]=None
  def ready(payload):loaded[0]=payload;show(vault.summary(payload));panel.say('Vault authenticated and previewed. No current memory has changed.')
  panel.background(lambda:vault.unlock(source,phrase),ready)
 def restore():
  if loaded[0] is None:raise ValueError('Unlock and preview the vault first.')
  payload=loaded[0];show(vault.summary(payload))
  choice=QMessageBox.question(panel,'Queue this memory restore?', 'At the next full startup, stores included in this vault will replace the corresponding local stores. A private local rollback snapshot will be kept. Imported skills require approval; lessons require review; project folders must be selected again. API keys stay on this device. Queue restore?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
  if choice!=QMessageBox.StandardButton.Yes:return
  def ready(value):loaded[0]=None;show(value);panel.say('Restore queued. Fully quit and reopen Mark LVI to apply it before any memory writers start.')
  panel.background(lambda:vault.queue_restore(payload),ready)
 row=QHBoxLayout();box.addLayout(row)
 for label,fn in [('Choose export file',choose_export),('Export encrypted vault',export),('Choose vault to restore',choose_import),('Unlock / preview',preview)]:panel.button(row,label,fn)
 row=QHBoxLayout();box.addLayout(row);panel.button(row,'Queue previewed restore…',restore);panel.button(row,'Cancel queued restore',lambda:show(vault.cancel_restore()))
 panel.info(box,'Restore is replacement, not a merge. Local routines remain on this device; imported workflow approvals are cleared. Vaults protect the exported file; ordinary app memory and the private pending/rollback files remain local application data. Do not speak or paste the passphrase into chat.')

def scenario_view(panel,box):
 from core import scenario_simulator as simulation
 panel.info(box,'Change explicit assumptions, run a local hypothetical scenario, compare results, and optionally save a private report. These calculations never trade, scan systems or alter your services.')
 kind=QComboBox();kind.addItems(['goal','savings','forex','trade_stress','outage']);box.addWidget(kind)
 parameters=QPlainTextEdit();parameters.setMaximumHeight(210);box.addWidget(parameters);chart=ScenarioChart();box.addWidget(chart);output=QPlainTextEdit();output.setReadOnly(True);box.addWidget(output);latest=[None];baseline=[None]
 examples={
 'goal':{'total_hours':300,'hours_per_day':3,'consistency_percent':80,'hours_done':0,'deadline_days':150,'daily_variation_percent':25},
 'savings':{'start_balance':0,'monthly_contribution':10000,'months':36,'annual_return_percent':0,'annual_volatility_percent':0,'target':400000},
 'forex':{'start_rate':1.1,'annual_return_percent':0,'annual_volatility_percent':10,'days':90,'paths':1000,'shock_percent':0,'seed':42},
 'trade_stress':{'equity':10000,'units':10000,'pair_start':1.1,'pair_move_percent':-2,'quote_to_account':1,'spread_cost':2,'slippage_cost':5,'direction':'long'},
 'outage':{'requests_per_minute':100,'outage_minutes':30,'affected_percent':100,'capacity_per_minute':200,'retry_percent':50,'backlog_before':0}}
 def example():parameters.setPlainText(json.dumps(examples[kind.currentText()],indent=2));latest[0]=None;chart.set_result({})
 kind.currentTextChanged.connect(example);example()
 def save():
  if latest[0] is None:raise ValueError('Run a scenario first.')
  panel.say('Private report saved: '+simulation.save(latest[0]))
 def pin():
  if latest[0] is None or latest[0].get('kind')=='comparison':raise ValueError('Run a baseline scenario first.')
  baseline[0]=latest[0];panel.say('Baseline pinned. Edit assumptions, then Compare with baseline.')
 def compare():
  if baseline[0] is None:raise ValueError('Pin a baseline first.')
  if kind.currentText()!=baseline[0]['kind']:raise ValueError('Compare scenarios of the same type.')
  original=baseline[0];values=json.loads(parameters.toPlainText())
  # Reconstruct the actual function parameters from the editable baseline input saved at pin time.
  base_values=original['_input_parameters'];scenario=kind.currentText()
  panel.background(lambda:simulation.compare(scenario,base_values,values),lambda result:(latest.__setitem__(0,result),output.setPlainText(json.dumps(result,indent=2)),chart.set_result(result['alternative'])))
 def run():
  scenario=kind.currentText();values=json.loads(parameters.toPlainText())
  def ready(value):
   value['_input_parameters']=values;latest[0]=value;chart.set_result(value);output.setPlainText(json.dumps(value,indent=2));panel.say('Hypothetical scenario complete. Pin it to compare another set of assumptions.')
  panel.background(lambda:simulation.run(scenario,values),ready)
 row=QHBoxLayout();box.addLayout(row);panel.button(row,'Run scenario',run);panel.button(row,'Pin as baseline',pin);panel.button(row,'Compare with baseline',compare);panel.button(row,'Save this scenario report',save)
 panel.info(box,'Example values are illustrative, not recommended assumptions. Forex uses a simple constant-parameter model; changing volatility, drift or shocks changes its outputs. Outage calculations assume constant traffic and a single recovery queue. Exact parameters remain in each report for reproducibility.')
