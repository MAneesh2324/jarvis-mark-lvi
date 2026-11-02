import asyncio
import io
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,AsyncMock
import numpy as np
from PIL import Image
from core import work_projects as projects,work_routines as routines,local_commands as local,screen_focus,screen_jobs,screen_workspace
from core.recording_notes import RecordingNotes,summary_parts,save_summary


class WorkFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(projects,'DB_PATH',self.root/'work.db'),patch.object(screen_workspace,'RECORDINGS',self.root/'recordings'),patch.object(screen_jobs,'CASES',self.root/'cases')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def project(self):return projects.save_project('Research','Finish the report',next_step='Read the results',root=str(self.root))

    def test_project_tasks_and_context_survive_reopen(self):
        self.project();projects.activate('research');task=projects.add_task('Write conclusions')
        self.assertEqual(projects.project()['name'],'Research')
        self.assertIn('Finish the report',projects.project_context())
        projects.task_done(task);self.assertEqual(projects.project()['tasks'][0]['done'],1)
        projects.save_project('RESEARCH',progress='Results reviewed')
        self.assertEqual(len(projects.list_projects()),1)
        self.assertEqual(projects.project()['progress'],'Results reviewed')
    def test_invalid_project_folder_and_missing_goal_fail(self):
        with self.assertRaises(ValueError):projects.save_project('x')
        with self.assertRaises(ValueError):projects.save_project('x','goal',root=str(self.root/'missing'))
    def test_routines_reject_shell_and_scripts(self):
        with self.assertRaises(ValueError):routines.save('bad',[{'action':'shell','command':'echo test'}])
        script=self.root/'run.command';script.write_text('echo test')
        with self.assertRaises(ValueError):routines.save('bad',[{'action':'open_path','path':str(script)}])
    def test_routine_runs_only_saved_steps_and_reports_unverified_launch(self):
        self.project();routines.save('Start work',[{'action':'activate_project','name':'Research'},{'action':'open_app','app':'Safari'}])
        with patch('actions.open_app.open_app',return_value='status=started action=open_app'):
            result=routines.run('start work')
        self.assertEqual(result['steps_attempted'],2)
        self.assertEqual(result['results'][1]['status'],'requested')
        self.assertFalse(result['all_verified'])
    def test_routine_stops_after_failure(self):
        routines.save('Work',[{'action':'open_app','app':'Missing'},{'action':'volume','percent':80}])
        with patch('actions.open_app.open_app',return_value='status=failed reason=missing'),patch('actions.computer_settings.volume_set') as volume:
            result=routines.run('Work')
        volume.assert_not_called();self.assertEqual(result['steps_attempted'],1)
    def test_local_grammar_understands_spoken_numbers_and_rejects_unrelated_requests(self):
        self.assertEqual(local.parse('Set volume to thirty percent.'),('volume',{'percent':30}))
        self.assertEqual(local.parse('timer for five minutes'),('timer',{'seconds':300}))
        self.assertEqual(local.parse('volume 101'),None)
        self.assertEqual(local.parse('delete all my files'),None)
        self.assertEqual(local.parse('run a shell script'),None)
    def test_local_timer_is_persistent_and_fires_once(self):
        with patch('core.local_commands.time.time',return_value=100):local.execute('timer five seconds')
        self.assertEqual(local.due_timers(104),[])
        self.assertEqual(len(local.due_timers(106)),1)
        self.assertEqual(local.due_timers(110),[])
    def test_typed_local_commands_work_without_conversation(self):
        from main import JarvisLive
        outputs=[];obj=JarvisLive.__new__(JarvisLive)
        obj.ui=type('UI',(),{'write_log':lambda self,t:None,'show_content':lambda self,t,b:outputs.append((t,b))})()
        obj.session=None
        obj._on_text_command('/local time')
        self.assertIn('It is',outputs[0][1])
    def test_disable_during_transcription_discards_stale_command(self):
        entered,release,done=threading.Event(),threading.Event(),threading.Event();texts=[]
        class Model:
            def transcribe(self,*a,**kw):
                entered.set();release.wait(2)
                return [type('Segment',(),{'text':'volume 80'})()],None
        engine=local.LocalVoice(texts.append)
        engine._model=Model();engine.enabled=True;engine.state='ready'
        engine._jobs.put((engine._generation,np.ones(16000,dtype=np.float32)))
        self.assertTrue(entered.wait(1));engine.set_enabled(False);release.set();engine._jobs.join()
        self.assertEqual(texts,[])
    def test_selected_window_close_never_falls_back_to_desktop(self):
        with patch.object(screen_focus,'require_screen_permission',create=True),patch('core.screen_workspace.require_screen_permission'),patch.object(screen_focus,'windows',return_value=[]),patch('mss.mss') as capture:
            with self.assertRaisesRegex(RuntimeError,'selected window closed'):screen_focus.capture({'mode':'window','window_id':12})
        capture.assert_not_called()
    def test_invalid_region_rejected(self):
        with self.assertRaises(ValueError):screen_focus.select('region',region={'left':0,'top':0,'width':0,'height':20})
    def test_recording_keyframes_are_bounded_and_summary_has_timestamps(self):
        video=screen_workspace.RECORDINGS/'session.mp4';video.parent.mkdir();video.write_bytes(b'test')
        notes=RecordingNotes(video)
        for i in range(125):notes.sample(np.full((48,64,3),(i%2)*100,dtype=np.uint8),i*10)
        notes.mark(37,'Decision: use the test environment')
        self.assertLessEqual(len(notes.data['keyframes']),120)
        parts,metadata=summary_parts(str(video))
        self.assertLessEqual(metadata['samples'],8)
        self.assertTrue(any('Frame at' in p.get('text','') for p in parts))
        self.assertIn('37',parts[-1]['text'])
        report=Path(save_summary(metadata,'00:37 — User marked a decision.'))
        self.assertTrue(report.exists());self.assertEqual(report.stat().st_mode&0o777,0o600)
    def test_recording_manifest_rejects_keyframe_outside_recording_folder(self):
        video=screen_workspace.RECORDINGS/'session.mp4';video.parent.mkdir();video.write_bytes(b'test')
        outside=self.root/'outside.jpg';outside.write_bytes(b'test')
        video.with_suffix('.notes.json').write_text(json.dumps({'keyframes':[{'seconds':0,'image':str(outside)}],'markers':[]}))
        with self.assertRaises(ValueError):summary_parts(str(video))
    def image(self,color):
        buffer=io.BytesIO();Image.new('RGB',(64,48),color).save(buffer,format='JPEG');return buffer.getvalue(),'image/jpeg'
    def test_diagnose_then_check_uses_before_and_after_evidence(self):
        scope={'mode':'display','monitor':1}
        with patch.object(screen_focus,'current',return_value=scope):
            parts,meta,_=screen_jobs.prepare('diagnose','Visible error',lambda:self.image('red'))
            screen_jobs.save_result(meta,'Observed: a red error banner.')
            after,check,_=screen_jobs.prepare('check','Error should disappear',lambda:self.image('blue'))
        images=[p['inline_data']['data'] for p in after if 'inline_data' in p]
        self.assertEqual(images,[self.image('red')[0],self.image('blue')[0]])
        self.assertIn('does not prove a backend fix',after[0]['text'])
    def test_check_rejects_changed_target(self):
        with patch.object(screen_focus,'current',return_value={'mode':'display','monitor':1}):screen_jobs.prepare('diagnose','Error',lambda:self.image('red'))
        with patch.object(screen_focus,'current',return_value={'mode':'display','monitor':2}):
            with self.assertRaisesRegex(ValueError,'same screen'):screen_jobs.prepare('check','',lambda:self.image('blue'))
    def test_screenshot_analysis_cannot_execute_a_tool(self):
        from main import JarvisLive
        from types import SimpleNamespace
        obj=JarvisLive.__new__(JarvisLive);obj._screen_readonly=True
        obj._execute_tool_impl=AsyncMock()
        response=asyncio.run(obj._execute_tool(SimpleNamespace(name='open_app',args={'app_name':'Terminal'},id='test')))
        self.assertIn('read-only',response.response['result'])
        obj._execute_tool_impl.assert_not_awaited()
    def test_screenshot_guard_always_allows_stop_sharing(self):
        from main import JarvisLive
        from types import SimpleNamespace
        obj=JarvisLive.__new__(JarvisLive);obj._screen_readonly=True
        obj._execute_tool_impl=AsyncMock(return_value='stopped')
        result=asyncio.run(obj._execute_tool(SimpleNamespace(name='screen_assist',args={'action':'stop'},id='test')))
        self.assertEqual(result,'stopped')
        obj._execute_tool_impl.assert_awaited_once()

    def test_workspace_panel_can_save_a_project_without_capture_or_network(self):
        from PyQt6.QtWidgets import QApplication,QWidget
        from core.workspace_panel import WorkspacePanel
        app=QApplication.instance() or QApplication([]);host=QWidget();host.on_text_command=lambda text:None
        panel=WorkspacePanel(host)
        panel.project_name.setText('Panel project');panel.project_goal.setText('Finish the UI test');panel._save_project()
        self.assertEqual(projects.active_name(),'Panel project')
        panel.resize(720,660);panel.grab().save('/private/tmp/jarvis-workspace-panel.png')
        panel.close();host.close()

if __name__=='__main__':unittest.main()
