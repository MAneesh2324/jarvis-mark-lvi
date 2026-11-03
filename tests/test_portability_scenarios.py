import json,math,os,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from core import portable_memory as vault,scenario_simulator as sim

class PortableTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'memory').mkdir();(self.root/'config').mkdir();self.patch=patch.object(vault,'ROOT',self.root);self.patch.start();self.password='unit-test-passphrase-only'
  (self.root/'memory'/'long_term.json').write_text(json.dumps({'identity':{'name':'Example'},'notes':{'test':'Original note'}}))
  (self.root/'config'/'api_keys.json').write_text(json.dumps({'gemini_api_key':'LOCAL-SECRET-NOT-PORTABLE','assistant_name':'Example JARVIS','response_speed':'fast'}))
 def tearDown(self):self.patch.stop();self.temp.cleanup()
 def destination(self):return self.root/'memory.jarvismem'
 def database(self,name,table,rows):
  path=self.root/'memory'/name
  with closing(sqlite3.connect(path)) as db,db:
   for t,columns,sql in vault.SCHEMAS[name]:db.execute(sql)
   columns=next(c for t,c,s in vault.SCHEMAS[name] if t==table);db.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in columns.split(','))+')',rows)
 def test_encrypted_round_trip_omits_credentials_and_history_by_default(self):
  self.database('conversations.db','summaries',[(1,'2026-01-01','Private chat','en')]);result=vault.export(self.destination(),self.password)
  raw=self.destination().read_bytes();self.assertNotIn(b'Original note',raw);self.assertNotIn(b'LOCAL-SECRET',raw)
  data=vault.unlock(self.destination(),self.password);self.assertNotIn('conversations.db',data['components']);self.assertNotIn('gemini_api_key',data['components']['preferences']);self.assertTrue(result['encrypted']);self.assertEqual(self.destination().stat().st_mode&0o777,0o600)
 def test_wrong_password_tampering_and_overwrite_do_not_restore(self):
  vault.export(self.destination(),self.password)
  with self.assertRaisesRegex(ValueError,'Wrong passphrase'):vault.unlock(self.destination(),'another-long-passphrase')
  raw=bytearray(self.destination().read_bytes());raw[-1]^=1;self.destination().write_bytes(raw)
  with self.assertRaisesRegex(ValueError,'damaged'):vault.unlock(self.destination(),self.password)
  with self.assertRaises(FileExistsError):vault.export(self.destination(),self.password)
  self.assertFalse((self.root/'memory'/'restore-pending.json').exists())
 def test_short_password_invalid_components_and_arbitrary_sql_are_rejected(self):
  with self.assertRaises(ValueError):vault.export(self.destination(),'short')
  with self.assertRaises(ValueError):vault.validate({'version':1,'components':{'../../outside':{}}})
  with self.assertRaises(ValueError):vault.validate({'version':1,'components':{'preferences':{'api_key':'bad'}}})
 def test_restore_only_applies_at_startup_preserves_local_api_key_and_snapshots_previous_memory(self):
  vault.export(self.destination(),self.password);payload=vault.unlock(self.destination(),self.password)
  (self.root/'memory'/'long_term.json').write_text('{"notes":{"test":"New local work"}}');(self.root/'config'/'api_keys.json').write_text('{"gemini_api_key":"CURRENT-LOCAL-KEY","assistant_name":"Local"}')
  vault.queue_restore(payload);self.assertIn('New local work',(self.root/'memory'/'long_term.json').read_text())
  result=vault.apply_pending();self.assertTrue(result['restored']);self.assertIn('Original note',(self.root/'memory'/'long_term.json').read_text());config=json.loads((self.root/'config'/'api_keys.json').read_text());self.assertEqual(config['gemini_api_key'],'CURRENT-LOCAL-KEY');self.assertEqual(config['assistant_name'],'Example JARVIS')
  backup=Path(result['rollback_snapshot']);self.assertIn('New local work',(backup/'memory'/'long_term.json').read_text());self.assertFalse((self.root/'memory'/'restore-pending.json').exists())
 def test_imported_skills_lose_approval_lessons_return_to_draft_roots_clear(self):
  self.database('skills.db','skills',[('Test',1,'{"type":"routine","steps":[{"action":"volume","percent":10}]}',1,'today')]);self.database('learning.db','lessons',[(1,'general','Test','Lesson','Evidence',None,'observed','2026-01-01','2030-01-01')]);self.database('workspaces.db','projects',[('P','Goal','Done','Next','/old/device/path','today')])
  payload=vault.collect();vault.queue_restore(payload);vault.apply_pending()
  for name,query,expected in [('skills.db','SELECT approved FROM skills',0),('learning.db','SELECT state FROM lessons','draft'),('workspaces.db','SELECT root FROM projects','')]:
   with closing(sqlite3.connect(self.root/'memory'/name)) as db,db:self.assertEqual(db.execute(query).fetchone()[0],expected)
 def test_saved_routines_are_portable_draft_skills_and_local_routines_survive(self):
  self.database('workspaces.db','projects',[])
  with closing(sqlite3.connect(self.root/'memory'/'workspaces.db')) as db,db:db.execute('CREATE TABLE routines(name TEXT PRIMARY KEY,steps TEXT,updated TEXT)');db.execute('INSERT INTO routines VALUES(?,?,?)',('Desk','[{"action":"volume","percent":20}]','today'))
  payload=vault.collect();self.assertEqual(payload['components']['skills.db']['skills'][0][0],'Desk');vault.queue_restore(payload);vault.apply_pending()
  with closing(sqlite3.connect(self.root/'memory'/'workspaces.db')) as db,db:self.assertEqual(db.execute('SELECT name FROM routines').fetchone()[0],'Desk')
  with closing(sqlite3.connect(self.root/'memory'/'skills.db')) as db,db:self.assertEqual(db.execute('SELECT approved FROM skills').fetchone()[0],0)
 def test_history_opt_in_restores_text_but_capture_stays_off(self):
  self.database('conversation_journal.db','sessions',[('s','today',0)])
  with closing(sqlite3.connect(self.root/'memory'/'conversation_journal.db')) as db,db:db.execute('INSERT INTO turns VALUES(1,"s","user","Private example","today")');db.execute('INSERT INTO settings VALUES("capture","on")')
  payload=vault.collect(True);vault.queue_restore(payload);vault.apply_pending()
  with closing(sqlite3.connect(self.root/'memory'/'conversation_journal.db')) as db,db:self.assertEqual(db.execute('SELECT value FROM settings WHERE key="capture"').fetchone()[0],'off');self.assertEqual(db.execute('SELECT text FROM turns').fetchone()[0],'Private example')
 def test_failed_restore_rolls_back_all_changed_stores(self):
  payload=vault.collect();payload['components']['facts']={'notes':{'replacement':'Test'}};vault.queue_restore(payload)
  original=vault._write
  def write(path,data):
   if Path(path)==self.root/'config'/'api_keys.json' and b'Example JARVIS' in data and b'CURRENT' not in data and not getattr(write,'raised',False):write.raised=True;raise OSError('Simulated write failure')
   return original(path,data)
  with patch.object(vault,'_write',side_effect=write):
   with self.assertRaises(OSError):vault.apply_pending()
  self.assertIn('Original note',(self.root/'memory'/'long_term.json').read_text());self.assertFalse((self.root/'memory'/'restore-pending.json').exists())
 def test_cancel_restore_and_empty_restore(self):
  vault.queue_restore(vault.collect());vault.cancel_restore();self.assertFalse(vault.apply_pending()['restored'])
  with self.assertRaises(ValueError):vault.queue_restore({'version':1,'components':{}})

class ScenarioTests(unittest.TestCase):
 def test_zero_volatility_forex_has_exact_conditional_result(self):
  result=sim.forex(1.2,0,0,days=20,paths=100,shock_percent=-10);self.assertAlmostEqual(result['terminal_rate_median'],1.08);self.assertEqual(result['terminal_rate_p05'],result['terminal_rate_p95']);self.assertAlmostEqual(result['median_path_max_drawdown_percent'],10)
 def test_reproducible_seed_and_volatility_comparison(self):
  params={'start_rate':1.1,'annual_return_percent':0,'annual_volatility_percent':10,'days':90,'paths':1000,'seed':5}
  a=sim.forex(**params);b=sim.forex(**params);self.assertEqual(a['fan_chart'],b['fan_chart']);result=sim.compare('forex',params,{'annual_volatility_percent':20});self.assertGreater(result['alternative']['terminal_rate_p95']-result['alternative']['terminal_rate_p05'],a['terminal_rate_p95']-a['terminal_rate_p05'])
 def test_compute_limits_nan_and_invalid_direction_rejected(self):
  with self.assertRaises(ValueError):sim.forex(1,0,10,days=2520,paths=10000)
  with self.assertRaises(ValueError):sim.forex(float('nan'),0,10)
  with self.assertRaises(ValueError):sim.trade_stress(1000,100,1,1,1,direction='bad')
 def test_trade_stress_accounts_for_direction_and_costs(self):
  a=sim.trade_stress(10000,10000,1.1,-2,1,2,5);self.assertAlmostEqual(a['net_pnl_account_currency'],-227)
  b=sim.trade_stress(10000,10000,1.1,-2,1,2,5,'short');self.assertAlmostEqual(b['net_pnl_account_currency'],213)
 def test_outage_recovery_and_insufficient_capacity(self):
  a=sim.outage(100,30,100,200,50);self.assertEqual(a['failed_or_interrupted_requests'],3000);self.assertEqual(a['estimated_backlog_clearance_minutes'],15)
  b=sim.outage(100,30,100,100,50);self.assertFalse(b['stable_recovery']);self.assertIsNone(b['estimated_backlog_clearance_minutes'])
  c=sim.outage(100,0,0,50);self.assertFalse(c['stable_recovery'])
 def test_report_saved_privately(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(sim,'REPORTS',Path(folder)):
   result=sim.run('outage',{'requests_per_minute':10,'outage_minutes':1,'affected_percent':100,'capacity_per_minute':20});path=Path(sim.save(result));self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertEqual(json.loads(path.read_text())['kind'],'outage')

if __name__=='__main__':unittest.main()
