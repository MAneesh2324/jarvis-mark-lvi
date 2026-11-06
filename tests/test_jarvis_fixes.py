"""Fixes for inabilities seen in the conversation journal and log (2026-11-06).

  * Files: "File not found" for names like solve.py, Desktop/x.py, generate_signature.py.
  * Owner lock-out: a misjudged voice blocked the owner — even from proving who they are by face.
  * Apps: "Ola" (how speech hears the Ulaa browser) could not be closed; a list of actions crashed the tool.
  * Camera: a face check failed while hand gestures held the camera.
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        for d in ('Desktop/JARVIS Code', 'Documents/Projects/bug', 'Downloads'):
            (self.home / d).mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home)})
        self.env.start()
        from core import paths
        self.spot = mock.patch.object(paths, '_spotlight', return_value=[])
        self.spot.start()

    def tearDown(self):
        self.spot.stop()
        self.env.stop()
        self.tmp.cleanup()


class FindFiles(TempHome):
    def test_finds_where_people_keep_things(self):
        from core import paths
        a = self.home / 'Desktop' / 'make_twilio_call.py'
        a.write_text('x')
        b = self.home / 'Desktop' / 'JARVIS Code' / 'solve.py'
        b.write_text('x')
        c = self.home / 'Documents' / 'Projects' / 'bug' / 'Desktop_report_gen.py'
        c.write_text('x')
        self.assertEqual(paths.find('Desktop/make_twilio_call.py'), a)
        self.assertEqual(paths.find('~/Desktop/make_twilio_call.py'), a)
        self.assertEqual(paths.find('make_twilio_call.py'), a)
        self.assertEqual(paths.find('solve.py'), b)
        self.assertEqual(paths.find('~/Desktop/Desktop_report_gen.py'), c)          # wrong folder, right file
        self.assertEqual(paths.find('Desktop report gen.py'), c)                    # spaces for underscores
        self.assertEqual(paths.find('solve'), b)                                    # no extension
        self.assertIsNone(paths.find('nothing_like_this.py'))

    def test_spotlight_is_the_last_resort(self):
        from core import paths
        deep = self.home / 'Work' / 'a' / 'b' / 'c' / 'd' / 'deep_notes.txt'
        deep.parent.mkdir(parents=True)
        deep.write_text('x')
        with mock.patch.object(paths, '_spotlight', return_value=[deep]):
            self.assertEqual(paths.find('deep_notes.txt'), deep)

    def test_file_controller_reads_but_never_deletes_by_guessing(self):
        from actions import file_controller as fc
        target = self.home / 'Documents' / 'Projects' / 'bug' / 'generate_signature.py'
        target.write_text('print("sig")')
        safe = mock.patch.object(fc, '_is_safe_path', return_value=True)   # its allowed roots are fixed at import
        safe.start()
        self.addCleanup(safe.stop)
        out = fc.read_file('desktop', 'generate_signature.py')
        self.assertIn('print("sig")', out)
        info = fc.get_file_info('generate_signature.py')
        self.assertIn('generate_signature.py', info)
        fc.delete_file('desktop', 'generate_signature.py')
        self.assertTrue(target.exists())                                            # not deleted from elsewhere

    def test_code_helper_runs_a_file_by_name(self):
        from actions import code_helper as ch
        (self.home / 'Desktop' / 'JARVIS Code' / 'hello_run.py').write_text('print("ran ok")\n')
        out = ch.code_helper({'action': 'run', 'file_path': 'hello_run.py'})
        self.assertIn('ran ok', out)


class OwnerLockout(unittest.TestCase):
    def live(self, guest=False, face_ok=False):
        import main
        live = main.JarvisLive.__new__(main.JarvisLive)
        live._last_input_voice = True
        live._guest_mode = guest
        live._pending_notes = []
        live.ui = mock.MagicMock()
        live._voice_guard = mock.MagicMock(owner=np.ones(4))
        live._voice_guard.check_now.return_value = {'result': 'stranger', 'score': 0.1}
        live._face_confirms_owner = mock.MagicMock(return_value=face_ok)
        live._face_people = 1
        return live

    def test_proving_identity_is_never_blocked(self):
        live = self.live(guest=True)
        with mock.patch('core.owner_guard.settings', return_value={'voice_guard': True}):
            self.assertFalse(live._guest_blocked('owner_guard', {'action': 'check_face'}))
            self.assertTrue(live._guest_blocked('owner_guard', {'action': 'forget'}))
            self.assertTrue(live._guest_blocked('phone_link', {}))

    def test_owner_seen_by_camera_is_not_blocked(self):
        live = self.live(guest=True, face_ok=True)
        with mock.patch('core.owner_guard.settings', return_value={'voice_guard': True}):
            self.assertFalse(live._guest_blocked('phone_link', {}))
        self.assertFalse(live._guest_mode)
        self.assertTrue(live._pending_notes)                                        # the model is told

    def test_voice_learns_only_when_safe(self):
        from core import owner_guard as og
        g = og.VoiceGuard.__new__(og.VoiceGuard)
        g.owner = og._unit(np.random.RandomState(1).randn(3, 8))
        g.strangers = 3
        sample = og._unit(np.random.RandomState(2).randn(8))
        with mock.patch.object(og, '_save_vec') as save:
            g.last_emb, g.last_score = sample, og.VOICE_ALARM + 0.05
            self.assertFalse(g.owner_confirmed(people=2))                             # someone else in view
            g.last_emb, g.last_score = sample, og.VOICE_ALARM - 0.05
            self.assertFalse(g.owner_confirmed(people=1))                             # clearly another voice
            g.last_emb, g.last_score = sample, og.VOICE_ALARM + 0.05
            self.assertTrue(g.owner_confirmed(people=1))
            save.assert_called_once()
        self.assertEqual(g.strangers, 0)


class Apps(unittest.TestCase):
    def test_misheard_names(self):
        from core import appidentity as ai
        self.assertEqual(ai.heard_as('Ola'), 'Ulaa')
        self.assertEqual(ai.heard_as('the ola browser'), 'Ulaa')
        self.assertEqual(ai.heard_as('Safari'), 'Safari')

    def test_close_suggests_the_closest_running_app(self):
        from actions import computer_control as cc
        from core import appidentity as ai
        with mock.patch.object(ai, 'running', return_value=[]), \
                mock.patch.object(ai, 'running_app_names', return_value=['Ulaa', 'WhatsApp', 'TradingView']):
            out = cc._close_app('Trading Vue')
        self.assertTrue(out.startswith('status=ask'), out)
        self.assertIn('TradingView', out)

    def test_a_list_of_actions_is_explained(self):
        from actions import computer_control as cc
        out = cc.computer_control({'action': 'type, copy, paste, select_all, undo, redo'})
        self.assertIn('one action per call', out)


class CameraSharing(unittest.TestCase):
    def test_gestures_pause_for_a_face_check_and_resume(self):
        from core.hand_gestures import GestureController
        g = GestureController()
        g._callback = object()
        g._thread = mock.MagicMock(is_alive=mock.MagicMock(return_value=True))
        g._stop = threading.Event()
        calls = []
        g.stop = mock.MagicMock(side_effect=lambda: (calls.append('stop'), g._stop.set()))
        g.start = mock.MagicMock(side_effect=lambda cb: calls.append('start'))
        with g.paused(wait=0.1) as was:
            calls.append('face check')
            self.assertTrue(was)
        self.assertEqual(calls, ['stop', 'face check', 'start'])


class WindowList(unittest.TestCase):
    def test_native_dicts_serialise(self):
        from actions import screen_target
        from collections import UserDict
        with mock.patch('core.screen_focus.windows', return_value=[{'bounds': UserDict({'X': 1})}]):
            out = screen_target.select({'action': 'list_windows'})
        self.assertNotIn('failed', out.split('\n')[0])
        self.assertIn('"X": 1', out)


if __name__ == '__main__':
    unittest.main()
