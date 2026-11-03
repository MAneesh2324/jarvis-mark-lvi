import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import json,tempfile,threading,unittest
from unittest.mock import patch,Mock
from core import learning_journal,mission_store as store,mission_engine,mission_workflows as flows,place_intelligence as places,engineering_workspace as engineering,home_bridge,personal_briefing as briefing,work_projects,earth_maps

class MissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(learning_journal,'DB_PATH',self.root/'learning.db'),patch.object(store,'DB_PATH',self.root/'missions.db'),patch.object(store,'ARTIFACTS',self.root/'artifacts'),patch.object(work_projects,'DB_PATH',self.root/'projects.db'),patch.object(home_bridge,'CONFIG',self.root/'home.json'),patch.object(briefing,'CALENDAR',self.root/'calendar.ics'),patch.object(briefing,'SETTINGS',self.root/'briefing.json'),patch.object(places,'SERVICES',self.root/'services.json')]
        for p in self.patches:p.start()
        self.engine=mission_engine.MissionEngine()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def test_restaurant_mission_requires_city_each_time(self):
        with self.assertRaisesRegex(ValueError,'Which city'):self.engine.plan('restaurants')
        item=self.engine.plan('restaurants',city='Kochi, India')
        self.assertEqual(item['state'],'planned');self.assertEqual(len(item['steps']),3)
        self.assertNotIn('location',item['params'])
    def test_engineering_requires_explicit_folder(self):
        with self.assertRaisesRegex(ValueError,'explicit'):self.engine.plan('engineering')
    def test_recovery_preserves_completed_steps(self):
        item=self.engine.plan('research','test source')
        store.transition(item['id'],{'planned'},'running');store.checkpoint(item['id'],0,'done',{'sources':['evidence']});store.checkpoint(item['id'],1,'running')
        store.recover();data=store.get(item['id'])
        self.assertEqual(data['state'],'interrupted');self.assertEqual(data['steps'][0]['state'],'done');self.assertEqual(data['steps'][1]['state'],'pending')
    def test_engine_runs_and_exports_local_engineering_report(self):
        (self.root/'example.py').write_text('def demo():\n    return 1\n')
        item=self.engine.plan('engineering',root=str(self.root));self.engine.start(item['id']);self.engine.jobs.join();data=store.get(item['id'])
        self.assertEqual(data['state'],'completed');self.assertEqual(data['steps'][0]['result']['diagnostics'],[])
        path=store.folder(item['id'])/'report.md';self.assertTrue(path.exists());self.assertEqual(path.stat().st_mode&0o777,0o600)
    def test_cancelled_network_result_cannot_complete_or_overwrite_state(self):
        entered=threading.Event();release=threading.Event()
        def execute(*args):entered.set();release.wait(3);return {'unexpected':'late response'}
        item=self.engine.plan('research','bounded example')
        with patch.object(flows,'execute',side_effect=execute):
            self.engine.start(item['id']);self.assertTrue(entered.wait(2));self.engine.stop(item['id']);release.set();self.engine.jobs.join()
        data=store.get(item['id']);self.assertEqual(data['state'],'cancelled');self.assertIsNone(data['steps'][0]['result'])
    def test_resume_rejects_worker_still_exiting(self):
        entered=threading.Event();release=threading.Event()
        def execute(*a):entered.set();release.wait(3);return {}
        item=self.engine.plan('research','query')
        with patch.object(flows,'execute',side_effect=execute):
            self.engine.start(item['id']);self.assertTrue(entered.wait(2));self.engine.stop(item['id'],True)
            with self.assertRaisesRegex(ValueError,'in-flight'):self.engine.start(item['id'])
            release.set();self.engine.jobs.join()
    def test_failed_routine_does_not_claim_success_or_replay(self):
        with patch('core.work_routines.preview',return_value={'name':'Test','steps':[]}):
            item=self.engine.plan('routine',name='Test')
            with patch('core.work_routines.run',return_value={'all_verified':False,'results':[{'status':'failed'}]}):
                self.engine.start(item['id']);self.engine.jobs.join()
            self.assertEqual(store.get(item['id'])['state'],'failed')
            with self.assertRaisesRegex(ValueError,'cannot safely resume'):self.engine.start(item['id'])
    def test_missing_website_tag_is_never_proof_of_no_website(self):
        response=Mock();response.json.return_value={'elements':[{'type':'node','id':1,'lat':9.9,'lon':76.2,'tags':{'name':'Cafe'}},{'type':'node','id':2,'lat':9.9,'lon':76.2,'tags':{'name':'Has website','contact:website':'https://example.com'}}]}
        with patch.object(places,'city_lookup',return_value={'latitude':9.9,'longitude':76.2}),patch.object(places.requests,'post',return_value=response):data=places.restaurants('Kochi')
        self.assertEqual(len(data['leads']),1);self.assertIn('verification required',data['leads'][0]['website_status']);self.assertIn('do not prove',data['coverage'])
    def test_csv_and_website_drafts_escape_untrusted_business_fields(self):
        lead={'name':'=SUM(A1)','city':'Kochi','address':'<script>alert(1)</script>','cuisine':'','phone':'','source':'https://www.openstreetmap.org/node/1'}
        self.assertIn("'=SUM",places.csv_text([lead]))
        item=self.engine.plan('restaurants',city='Kochi');store.transition(item['id'],{'planned'},'running');store.checkpoint(item['id'],0,'done',{'leads':[lead]})
        path=Path(flows.draft_website(item['id'],0));text=path.read_text();self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>alert',text);self.assertIn('Not an official business website',text)
        with self.assertRaises(ValueError):flows.draft_website(item['id'],-1)
    def test_geocoder_cache_survives_calls_and_provider_is_configurable(self):
        response=Mock();response.json.return_value=[{'display_name':'Kochi, India','lat':'9.93','lon':'76.26','osm_type':'relation','osm_id':1}]
        with patch.object(places.requests,'get',return_value=response) as get:
            places.city_lookup('Kochi');places.city_lookup('kochi');self.assertEqual(get.call_count,1)
        places.SERVICES.write_text(json.dumps({'geocoder':'https://example.test/search'}));self.assertEqual(places.service('geocoder','default'),'https://example.test/search')
    def test_engineering_excludes_credentials_symlinks_and_checks_syntax(self):
        (self.root/'good.py').write_text('def good():\n return 1\n');(self.root/'bad.py').write_text('def invalid(\n');(self.root/'api_keys.json').write_text('{"key":"private"}');(self.root/'link.py').symlink_to(self.root/'good.py')
        data=engineering.inspect(str(self.root));self.assertEqual(len(data['diagnostics']),1);self.assertEqual({r['file'] for r in data['files']},{'good.py','bad.py'})
        with self.assertRaises(ValueError):engineering.read(self.root,'../outside.txt')
        with self.assertRaises(ValueError):engineering.read(self.root,'api_keys.json')
    def test_home_setup_is_private_token_never_returned_and_control_is_scoped(self):
        result=home_bridge.setup('http://homeassistant.local:8123','secret-test-token',['light.desk'])
        self.assertNotIn('secret-test-token',json.dumps(result));self.assertEqual(home_bridge.CONFIG.stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError):home_bridge.control('switch.unknown',True)
        with patch.object(home_bridge,'_request',side_effect=[{}, {'state':'on'}]):self.assertTrue(home_bridge.control('light.desk',True)['verified'])
    def test_home_mismatch_is_unverified_and_redirects_are_disabled(self):
        home_bridge.setup('https://home.example','private-token',['light.desk'])
        with patch.object(home_bridge,'_request',return_value={'state':'off'}),patch.object(home_bridge.time,'sleep'):self.assertFalse(home_bridge.control('light.desk',True)['verified'])
        response=Mock(status_code=302)
        with patch.object(home_bridge.requests,'request',return_value=response) as request:
            with self.assertRaises(RuntimeError):home_bridge._request('GET','states')
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
    def test_calendar_snapshot_expands_recurrence_and_retains_timezone(self):
        from datetime import datetime,timedelta
        today=datetime.now().astimezone().date();yesterday=today-timedelta(days=1)
        text='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:test\r\nDTSTART;VALUE=DATE:'+yesterday.strftime('%Y%m%d')+'\r\nRRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Daily check\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
        path=self.root/'export.ics';path.write_text(text);briefing.import_calendar(path);data=briefing.calendar_events()
        self.assertTrue(data['connected']);self.assertTrue(any(e['title']=='Daily check' and e['start']==today.isoformat() for e in data['events']));self.assertIn('not a live sync',data['note'])
    def test_briefing_missing_calendar_does_not_invent_events(self):
        self.assertFalse(briefing.build()['calendar']['connected'])
    def test_route_validation_and_map_markers(self):
        with self.assertRaises(ValueError):earth_maps.validate_options({'markers':[{'latitude':999,'longitude':0}]})
        route={'geometry':{'type':'LineString','coordinates':[[76,9],[77,10]]},'distance_m':100,'duration_s':50}
        data=earth_maps.validate_options({'view':'street','route':route,'markers':[{'latitude':9,'longitude':76,'label':'Cafe'}]})
        self.assertEqual(data['route']['distance_m'],100);self.assertEqual(data['markers'][0]['label'],'Cafe')
    def test_mission_panel_can_create_plan_without_network(self):
        from PyQt6.QtWidgets import QApplication,QWidget
        from core.mission_panel import MissionPanel
        app=QApplication.instance() or QApplication(['test']);host=QWidget();host._open_work_panel=lambda:None
        with patch('core.mission_panel.engine',return_value=self.engine):panel=MissionPanel(host)
        panel.goal.setText('Research sustainable menus');panel.plan()
        self.assertEqual(store.listing()[0]['state'],'planned');self.assertIn('Gather web sources',panel.details.toPlainText());panel.close();host.close()

if __name__=='__main__':unittest.main()

class InteractionTests(unittest.TestCase):
    def test_voice_interruption_requires_sustained_non_echo_and_respects_off(self):
        import numpy as np
        from core import voice_interaction as voice
        gate=voice.VoiceInterrupt();pcm=np.ones(1024,dtype=np.int16)
        echo=Mock(required_blocks=3);echo.is_user_speech.return_value=True
        with patch.object(voice,'enabled',return_value=True):
            self.assertEqual(gate.feed(pcm,16000,0.2,echo),[]);self.assertEqual(gate.feed(pcm,16000,0.2,echo),[]);self.assertEqual(len(gate.feed(pcm,16000,0.2,echo)),3)
            self.assertEqual(gate.feed(pcm,16000,0.2,echo,allowed=False),[])
            echo.is_user_speech.return_value=False;self.assertEqual(gate.feed(pcm,16000,0.2,echo),[])
        with patch.object(voice,'enabled',return_value=False):self.assertEqual(gate.feed(pcm,16000,0.2,echo),[])
    def test_browser_typing_checks_observed_value_and_never_claims_mismatch_success(self):
        import asyncio
        from unittest.mock import AsyncMock
        from actions.browser_control import _BrowserSession
        obj=_BrowserSession.__new__(_BrowserSession)
        el=Mock();el.input_value=AsyncMock(side_effect=['','different']);el.fill=AsyncMock()
        page=Mock();page.locator.return_value.first=el;obj._get_page=AsyncMock(return_value=page)
        result=asyncio.run(obj.type_text('#name','expected'))
        self.assertIn('status=unverified',result);self.assertNotIn('expected',result)
        el.input_value=AsyncMock(side_effect=['','expected'])
        self.assertIn('status=done',asyncio.run(obj.type_text('#name','expected')))
