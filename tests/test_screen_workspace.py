import asyncio
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
import numpy as np
from PIL import Image
from core import screen_workspace as screen


class FakeCapture:
    monitors = [{'width': 64, 'height': 48}, {'width': 64, 'height': 48}]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def grab(self, target):
        frame = np.zeros((48, 64, 4), dtype=np.uint8)
        frame[:, :, 1] = 120
        frame[:, :, 3] = 255
        return frame


class ScreenTests(unittest.TestCase):
    def test_recording_finalizes_real_playable_mp4(self):
        import cv2
        recorder=screen.ScreenRecorder()
        with tempfile.TemporaryDirectory() as folder, patch.object(screen, 'RECORDINGS', Path(folder)), patch.object(screen, 'require_screen_permission'), patch('mss.mss', FakeCapture):
            first=recorder.start(fps=5)
            self.assertTrue(first['recording'])
            self.assertGreater(first['frames'], 0)
            with self.assertRaises(RuntimeError): recorder.start()
            final=recorder.stop()
            self.assertTrue(final['saved'])
            self.assertFalse(final['recording'])
            self.assertEqual(Path(final['path']).stat().st_mode & 0o777, 0o600)
            capture=cv2.VideoCapture(final['path'])
            ok, frame=capture.read()
            capture.release()
            self.assertTrue(ok)
            self.assertEqual(frame.shape[:2], (48, 64))

    def test_permission_failure_does_not_start_capture(self):
        recorder=screen.ScreenRecorder()
        with patch.object(screen, 'require_screen_permission', side_effect=PermissionError('permission denied')), patch('mss.mss') as capture:
            with self.assertRaises(PermissionError): recorder.start()
            capture.assert_not_called()
        self.assertFalse(recorder.status()['recording'])

    def test_invalid_monitor_reports_failure_and_releases(self):
        recorder=screen.ScreenRecorder()
        with tempfile.TemporaryDirectory() as folder, patch.object(screen, 'RECORDINGS', Path(folder)), patch.object(screen, 'require_screen_permission'), patch('mss.mss', FakeCapture):
            with self.assertRaisesRegex(RuntimeError, 'display does not exist'): recorder.start(monitor=8)
            self.assertFalse(recorder.stop()['saved'])

    def test_opt_in_and_stop_generation(self):
        workspace=screen.ScreenWorkspace()
        self.assertFalse(workspace.status()['watching'])
        with patch.object(screen, 'require_screen_permission'):
            state=workspace.control('watch', focus='Review my code', interval=2)
            self.assertEqual(state['interval_seconds'], 15)
            self.assertTrue(state['watching'])
            generation=state['generation']
            workspace.control('analyze')
            self.assertTrue(workspace.take_request())
            self.assertFalse(workspace.take_request())
            state=workspace.control('stop')
            self.assertFalse(state['watching'])
            self.assertGreater(state['generation'], generation)

    def test_static_screens_do_not_trigger_repeat_analysis(self):
        buffer=io.BytesIO()
        Image.new('RGB', (64, 48), 'black').save(buffer, format='JPEG')
        first=screen.frame_fingerprint(buffer.getvalue())
        self.assertTrue(screen.screen_changed(None, first))
        self.assertFalse(screen.screen_changed(first, first.copy()))
        self.assertTrue(screen.screen_changed(first, first+30))

    def _controller(self):
        from main import JarvisLive
        obj=JarvisLive.__new__(JarvisLive)
        obj._screen_analysis_pending=0
        obj._engine_caps=None
        obj._is_speaking=False
        obj._vision_busy=False
        obj._awake=True
        obj._last_user_speech=0
        obj.ui=type('UI', (), {'write_log': lambda self, text: None})()
        obj.session=type('Session', (), {'send_client_content': AsyncMock()})()
        return obj

    def test_analysis_uses_actual_image_in_current_session(self):
        workspace=screen.ScreenWorkspace()
        with patch.object(screen, 'require_screen_permission'):
            workspace.control('analyze')
        obj=self._controller()
        buffer=io.BytesIO()
        Image.new('RGB', (64, 48), 'blue').save(buffer, format='JPEG')
        count=0
        async def step(_):
            nonlocal count
            count+=1
            if count>1: raise asyncio.CancelledError()
        async def run():
            with patch.object(screen, 'workspace', workspace), patch('main._capture_screen', return_value=(buffer.getvalue(), 'image/jpeg')), patch('main.asyncio.sleep', side_effect=step):
                with self.assertRaises(asyncio.CancelledError): await obj._run_screen_copilot()
        asyncio.run(run())
        obj.session.send_client_content.assert_awaited_once()
        parts=obj.session.send_client_content.call_args.kwargs['turns']['parts']
        self.assertEqual(parts[0]['inline_data']['data'], buffer.getvalue())
        self.assertIn('untrusted content', parts[1]['text'])
        self.assertEqual(workspace.status()['frames_shared'], 1)

    def test_stop_during_capture_prevents_late_sharing(self):
        workspace=screen.ScreenWorkspace()
        with patch.object(screen, 'require_screen_permission'): workspace.control('analyze')
        obj=self._controller()
        buffer=io.BytesIO()
        Image.new('RGB', (64, 48), 'blue').save(buffer, format='JPEG')
        def capture():
            workspace.control('stop')
            return buffer.getvalue(), 'image/jpeg'
        count=0
        async def step(_):
            nonlocal count
            count+=1
            if count>1: raise asyncio.CancelledError()
        async def run():
            with patch.object(screen, 'workspace', workspace), patch('main._capture_screen', side_effect=capture), patch('main.asyncio.sleep', side_effect=step):
                with self.assertRaises(asyncio.CancelledError): await obj._run_screen_copilot()
        asyncio.run(run())
        obj.session.send_client_content.assert_not_awaited()

if __name__ == '__main__': unittest.main()

class ScreenPermissionTests(unittest.TestCase):
    def test_native_bundle_permission_names_mark_lvi_not_terminal(self):
        from unittest.mock import Mock
        import sys
        bundle=Mock();bundle.infoDictionary.return_value={'CFBundleDisplayName':'Mark LVI'};bundle.bundleIdentifier.return_value='com.maneesh.marklvi'
        quartz=Mock();quartz.CGPreflightScreenCaptureAccess.return_value=False
        foundation=Mock();foundation.NSBundle.mainBundle.return_value=bundle
        with patch.object(screen.platform,'system',return_value='Darwin'),patch.dict(sys.modules,{'Quartz':quartz,'Foundation':foundation}):
            state=screen.screen_permission_status();self.assertFalse(state['granted'])
            with self.assertRaisesRegex(PermissionError,'not granted to Mark LVI'):screen.require_screen_permission()
            text=screen.permission_instructions(state);self.assertIn(str(screen.ROOT.parent/'Mark LVI.app'),text);self.assertNotIn('Enable Screen Recording for Python/Terminal',text);self.assertIn('switch is already on',text);self.assertIn('Audio-only access',text)
            quartz.CGRequestScreenCaptureAccess.assert_not_called()
    def test_request_is_explicit_and_uses_native_api(self):
        from unittest.mock import Mock
        import sys
        quartz=Mock();denied={'required':True,'granted':False};granted={'required':True,'granted':True}
        with patch.object(screen,'screen_permission_status',side_effect=[denied,granted]),patch.dict(sys.modules,{'Quartz':quartz}):self.assertTrue(screen.request_screen_permission()['granted'])
        quartz.CGRequestScreenCaptureAccess.assert_called_once()
    def test_permission_denial_is_visible_in_recorder_status(self):
        recorder=screen.ScreenRecorder()
        with patch.object(screen,'require_screen_permission',side_effect=PermissionError('Access not granted to Mark LVI')):
            with self.assertRaises(PermissionError):recorder.start()
        self.assertTrue(recorder.status()['permission_required']);self.assertIn('Mark LVI',recorder.status()['error']);self.assertFalse(recorder.status()['recording'])
    def test_voice_start_opens_setup_without_claiming_recording_started(self):
        from unittest.mock import Mock
        from actions.screen_recording import recording
        ui=Mock();recorder=screen.ScreenRecorder()
        with patch('actions.screen_recording.workspace',type('State',(),{'recorder':recorder})()),patch.object(screen,'require_screen_permission',side_effect=PermissionError('Enable Mark LVI')):
            result=recording({'action':'start'},player=ui)
        self.assertIn('status=failed',result);self.assertIn('permission_required=true',result);ui.request_screen_permission.assert_called_once();self.assertFalse(recorder.status()['recording'])

class AudioRecordingTests(unittest.TestCase):
    def test_native_audio_dispatch_and_final_status(self):
        import threading
        recorder=screen.ScreenRecorder()
        def native(owner,monitor,fps):
            self.assertEqual((monitor,fps),(1,8))
            owner._path.write_bytes(b'test-only')
            owner._frames=1;owner._ready.set();owner._stop.wait(2)
            owner._audio_recorded=True
        with tempfile.TemporaryDirectory() as folder,patch.object(screen,'RECORDINGS',Path(folder)),patch.object(screen,'require_screen_permission'),patch.object(screen.platform,'system',return_value='Darwin'),patch('core.native_screen_recording.record',side_effect=native):
            self.assertEqual(recorder.start(audio='system')['audio_source'],'system')
            state=recorder.stop();self.assertTrue(state['audio_recorded']);self.assertTrue(state['saved'])
    def test_audio_failure_is_not_reported_as_success(self):
        recorder=screen.ScreenRecorder()
        with tempfile.TemporaryDirectory() as folder,patch.object(screen,'RECORDINGS',Path(folder)),patch.object(screen,'require_screen_permission'),patch.object(screen.platform,'system',return_value='Darwin'),patch('core.native_screen_recording.record',side_effect=RuntimeError('audio initialization failed')):
            with self.assertRaisesRegex(RuntimeError,'audio initialization failed'):recorder.start(audio='system')
            self.assertFalse(recorder.stop()['audio_recorded'])
