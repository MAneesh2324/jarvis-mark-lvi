import tempfile,unittest,json
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch,Mock
from core import learning_journal as learn,forex_workspace as forex,cyber_workspace as cyber,intelligence_cache as cache,auto_learning

class KnowledgeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.patches=[patch.object(learn,'DB_PATH',self.root/'learning.db'),patch.object(cache,'ROOT',self.root/'cache')]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in self.patches:p.stop()
  self.temp.cleanup()
 def test_user_lesson_requires_evidence_and_review(self):
  with self.assertRaises(ValueError):learn.draft('forex','Rule','Test','')
  row=learn.draft('forex','Daily rates','These are reference observations','ECB source')
  self.assertEqual(learn.recall(),[]);learn.review(row['id'],True);self.assertEqual(len(learn.recall()),1);learn.review(row['id'],False);self.assertEqual(learn.recall(),[])
 def test_expired_lessons_never_enter_context(self):
  row=learn.draft('general','Test','Check evidence','Unit test',days=1);learn.review(row['id'],True)
  with patch.object(learn,'now',return_value=learn.now()+timedelta(days=2)):self.assertEqual(learn.recall(),[])
 def test_outcome_learning_is_automatic_deduplicated_and_revocable(self):
  mission={'id':'test','kind':'research','state':'failed','error':'Timed out','steps':[{'title':'Fetch','state':'running'}]}
  row=learn.reflect(mission);self.assertEqual(row['state'],'observed');learn.reflect(mission);self.assertEqual(len(learn.listing()),1);self.assertIn('failed',learn.context().lower())
  learn.review(row['id'],False);learn.reflect(mission);self.assertEqual(learn.recall(),[])
 def test_cross_currency_reference_conversion(self):
  text='<root><Cube time="2026-01-02"><Cube currency="USD" rate="1.2"/><Cube currency="JPY" rate="180"/></Cube><Cube time="2026-01-01"><Cube currency="USD" rate="1.1"/><Cube currency="JPY" rate="165"/></Cube></root>'
  rows=forex.parse_rates(text,'USD','JPY');self.assertEqual(rows[-1]['rate'],150);self.assertEqual(rows[0]['date'],'2026-01-01')
  with self.assertRaises(ValueError):forex.parse_rates('<!DOCTYPE x><root/>','EUR','USD')
 def test_indicators_use_simple_observation_math(self):
  rows=[{'rate':float(x),'date':str(x)} for x in range(1,61)];data=forex.indicators(rows)
  self.assertEqual(data['sma20'],50.5);self.assertEqual(data['rsi14_simple'],100)
  self.assertEqual(forex.indicators([{'rate':1}]*20)['rsi14_simple'],50)
 def test_position_sizing_and_conversion_guards(self):
  row=forex.position_size('EUR/USD',10000,1,20,'USD');self.assertEqual(row['base_currency_units'],50000)
  with self.assertRaises(ValueError):forex.position_size('USD/JPY',10000,1,20,'USD')
  with self.assertRaises(ValueError):forex.position_size('EUR/USD',float('nan'),1,20,'USD')
 def test_journal_does_not_mix_currencies(self):
  learn.trade('EUR/USD',100,'USD');learn.trade('EUR/USD',-50,'USD');learn.trade('EUR/GBP',900,'GBP')
  row=learn.trade_summary('USD');self.assertEqual(row['trades'],2);self.assertEqual(row['net_realized'],50);self.assertEqual(row['profit_factor'],2);self.assertEqual(row['max_drawdown_in_entered_results'],50)
 def test_cisa_filter_preserves_source_and_observation_date(self):
  payload={'catalogVersion':'test','dateReleased':'2026-01-02','vulnerabilities':[{'cveID':'CVE-2021-44228','vendorProject':'Apache','product':'Log4j','dateAdded':'2021-12-10'}]}
  with patch.object(cache,'fetch',return_value={'text':json.dumps(payload),'url':cyber.CISA,'fetched_at':'test','offline_fallback':False,'cache_hit':False}):row=cyber.kev('log4j')
  self.assertEqual(row['matching'],1);self.assertEqual(row['items'][0]['cveID'],'CVE-2021-44228');self.assertIn('not a scan',row['note'])
 def test_primary_source_filter_rejects_lookalike_hosts(self):
  with patch('core.place_intelligence.search_sources',return_value=[{'url':'https://owasp.org.evil.test/','title':'Fake'},{'url':'https://owasp.org/Top10/','title':'Official'}]):row=cyber.research('Web security')
  self.assertEqual(len(row['sources']),1);self.assertEqual(row['sources'][0]['title'],'Official')
 def test_failed_refresh_labels_cached_data_offline_and_retains_timestamp(self):
  import requests,hashlib
  url='https://example.test/feed';cache.ROOT.mkdir();key=hashlib.sha256(url.encode()).hexdigest();(cache.ROOT/(key+'.json')).write_text(json.dumps({'text':'old','timestamp':0,'fetched_at':'original-date','url':url}))
  with patch.object(cache.requests,'get',side_effect=requests.ConnectionError):result=cache.fetch(url,force=True)
  self.assertTrue(result['offline_fallback']);self.assertEqual(result['fetched_at'],'original-date')
 def test_cve_id_validation_prevents_arbitrary_endpoint_queries(self):
  with self.assertRaises(ValueError):cyber.cve('../anything')
 def test_auto_learning_off_does_not_start_requests(self):
  with patch.object(auto_learning,'settings',return_value={'enabled':False}),patch.object(auto_learning.threading,'Thread') as thread:auto_learning.tick();thread.assert_not_called()

if __name__=='__main__':unittest.main()

class ToolLearningTests(unittest.TestCase):
 def test_permission_failures_become_local_observed_lessons_without_raw_error_in_context(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(learn,'DB_PATH',Path(folder)/'learning.db'):
   learn.reflect_tool('screen_recording','Permission denied: private-detail-example')
   learn.reflect_tool('screen_recording','Permission denied: private-detail-example')
   self.assertEqual(len(learn.listing()),1);text=learn.context();self.assertIn('actual app permission',text);self.assertNotIn('private-detail-example',text)
