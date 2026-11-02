import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch,Mock
from core import development_sandbox as dev,skill_learning as skills,work_projects,mission_store

class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.project=self.base/'project';self.project.mkdir();(self.project/'sample.py').write_bytes(b'def value():\r\n    return 1\r\n')
        self.patches=[patch.object(dev,'BASE',self.base/'sandboxes'),patch.object(skills,'DB_PATH',self.base/'skills.db'),patch.object(work_projects,'DB_PATH',self.base/'work.db'),patch.object(mission_store,'DB_PATH',self.base/'missions.db')]
        for p in self.patches:p.start()
    def tearDown(self):
        skills._recording=None
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def create(self):return dev.create(str(self.project),'Improve the sample')['id']
    def test_copy_edit_check_apply_and_rollback_preserve_original_bytes(self):
        original=(self.project/'sample.py').read_bytes();key=self.create();dev.edit(key,'sample.py','def value():\n    return 2\n')
        self.assertEqual((self.project/'sample.py').read_bytes(),original);self.assertIn('return 2',dev.review(key)['changes'][0]['diff']);self.assertTrue(dev.check(key)['passed'])
        dev.promote(key);self.assertIn('return 2',(self.project/'sample.py').read_text());dev.rollback(key);self.assertEqual((self.project/'sample.py').read_bytes(),original)
    def test_apply_rejects_changed_original_and_stale_checks(self):
        key=self.create();dev.edit(key,'sample.py','x=2\n');dev.check(key);(self.project/'sample.py').write_text('new_work=3\n')
        with self.assertRaisesRegex(ValueError,'Original project changed'):dev.promote(key)
        self.assertEqual((self.project/'sample.py').read_text(),'new_work=3\n')
    def test_edit_invalidates_checks_and_rollback_protects_new_work(self):
        key=self.create();dev.edit(key,'sample.py','x=2\n');dev.check(key);dev.edit(key,'sample.py','x=3\n')
        with self.assertRaisesRegex(ValueError,'passing checks'):dev.promote(key)
        dev.check(key);dev.promote(key);(self.project/'sample.py').write_text('newer=4\n')
        with self.assertRaisesRegex(ValueError,'newer work'):dev.rollback(key)
    def test_private_files_symlinks_and_traversal_are_excluded(self):
        (self.project/'api_keys.json').write_text('{"secret":"no"}');(self.project/'link.py').symlink_to(self.project/'sample.py');key=self.create()
        self.assertEqual(set(dev.load(key)['files']),{'sample.py'})
        for name in ('../sample.py','/tmp/sample.py','config/api_keys.json'):
            with self.assertRaises(ValueError):dev.target(self.project,name)
        (dev.directory(key)/'work'/'sample.py').unlink();(dev.directory(key)/'work'/'sample.py').symlink_to(self.project/'sample.py')
        with self.assertRaises(ValueError):dev.edit(key,'sample.py','bad=1')
    def test_invalid_python_cannot_be_promoted(self):
        key=self.create();dev.edit(key,'sample.py','def broken(\n');self.assertFalse(dev.check(key)['passed'])
        with self.assertRaises(ValueError):dev.promote(key)
    def test_ai_proposal_does_not_edit_until_staged_and_rejects_stale(self):
        key=self.create();reply=json.dumps({'files':[{'file':'sample.py','content':'x=5\n'}],'explanation':'Example'})
        with patch('core.gemini.text',return_value=reply):dev.propose(key,['sample.py'],'Change it')
        self.assertEqual(dev.review(key)['changes'],[]);dev.edit(key,'sample.py','user=9\n')
        with self.assertRaisesRegex(ValueError,'changed since'):dev.stage_proposal(key)
    def test_ai_response_cannot_write_unselected_file(self):
        key=self.create();reply=json.dumps({'files':[{'file':'../outside.py','content':'x=5\n'}]})
        with patch('core.gemini.text',return_value=reply):
            with self.assertRaises(ValueError):dev.propose(key,['sample.py'],'Change it')
    def test_project_unittests_run_in_copy_and_return_real_result(self):
        (self.project/'tests').mkdir();(self.project/'tests'/'test_value.py').write_text('import unittest\nfrom sample import value\nclass Test(unittest.TestCase):\n def test_value(self):self.assertEqual(value(),1)\n')
        key=self.create();result=dev.run_tests(key);self.assertTrue(result['passed']);self.assertIn('Ran 1 test',result['output'])
        dev.edit(key,'sample.py','def value():\n return 8\n');self.assertFalse(dev.run_tests(key)['passed']);self.assertIn('return 1',(self.project/'sample.py').read_text())
    def test_skill_versions_need_fresh_review(self):
        d={'type':'routine','steps':[{'action':'volume','percent':20}]};first=skills.save('Work',d)
        with self.assertRaisesRegex(ValueError,'approval'):skills.run('Work')
        skills.approve('Work',1,first['fingerprint']);self.assertTrue(skills.get('Work',1)['approved'])
        second=skills.save('Work',d);self.assertEqual(second['version'],2);self.assertFalse(second['approved']);self.assertTrue(skills.get('Work',1)['approved'])
        with self.assertRaises(ValueError):skills.approve('Work',2,'stale-hash')
    def test_restaurant_skill_never_remembers_city_and_requires_new_city(self):
        data=skills.save('Prospects',{'type':'mission','kind':'restaurants','params':{'city':'Old city'}})
        self.assertNotIn('city',data['definition']['params']);skills.approve('Prospects',1,data['fingerprint'])
        with self.assertRaisesRegex(ValueError,'Which city'):skills.run('Prospects')
    def test_teaching_captures_supported_steps_only_when_enabled(self):
        skills.observe({'action':'volume','percent':10},'verified');skills.begin('My workflow');skills.observe({'action':'volume','percent':20},'verified');data=skills.finish()
        self.assertEqual(data['definition']['steps'],[{'action':'volume','percent':20}]);self.assertFalse(data['approved'])
        with self.assertRaises(ValueError):skills.save('Bad',{'type':'routine','steps':[{'action':'shell','command':'anything'}]})
    def test_skill_execution_uses_approved_snapshot_and_cleans_temporary_routine(self):
        d=skills.save('Work',{'type':'routine','steps':[{'action':'volume','percent':20}]});skills.approve('Work',1,d['fingerprint'])
        with patch('core.work_routines.run',return_value={'all_verified':True}) as run:self.assertTrue(skills.run('Work')['all_verified'])
        from core.work_routines import list_routines
        self.assertEqual(list_routines(),[]);run.assert_called_once()

if __name__=='__main__':unittest.main()
