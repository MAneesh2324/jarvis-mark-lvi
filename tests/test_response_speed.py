from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from memory import config_manager as cfg
from core import response_speed as speed


class SpeedProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'settings.json'
        self.path.write_text('{"turn_tuning":{"enabled":true,"silence_ms":1200},"proactive_audio":true}')
        self.patches=[patch.object(cfg,'CONFIG_FILE',self.path),patch.object(cfg,'CONFIG_DIR',Path(self.temp.name))]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def test_fast_profile_effective_pause_and_reversible_preferences(self):
        speed.set_profile('fast')
        self.assertEqual(speed.effective_turn_tuning()['silence_ms'],400)
        self.assertEqual(cfg.get_turn_tuning()['silence_ms'],1200)
        self.assertTrue(cfg.get_proactive_audio_enabled())
        speed.set_profile('standard')
        self.assertEqual(speed.effective_turn_tuning()['silence_ms'],1200)
    def test_fast_turn_configuration_requests_zero_thinking(self):
        from main import JarvisLive
        obj=JarvisLive.__new__(JarvisLive)
        speed.set_profile('fast');config=obj._tuning_config()
        self.assertEqual(config['thinking_config'].thinking_budget,0)
        self.assertEqual(config['realtime_input_config'].automatic_activity_detection.silence_duration_ms,400)
    def test_patient_preference_overrides_fast(self):
        from actions.voice_pacing import configure
        speed.set_profile('fast');configure({'preset':'patient'})
        self.assertEqual(speed.get_profile(),'standard')
        self.assertEqual(speed.effective_turn_tuning()['silence_ms'],1200)
    def test_invalid_profile_rejected(self):
        with self.assertRaises(ValueError):speed.set_profile('invalid')

    def test_fast_profile_keeps_jarvis_out_of_room_conversations(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / 'main.py').read_text()
        block = src[src.index('ProactivityConfig') - 400: src.index('ProactivityConfig')]
        self.assertIn('self._proactive_wanted()', block)                # decided by who is in the room
        prompt = (root / 'core' / 'prompt.txt').read_text()
        self.assertIn('[WHO YOU ANSWER]', prompt)
        self.assertIn('never ignore your name', prompt)

    def test_proactive_audio_only_while_someone_else_is_talking_in_fast_mode(self):
        from main import JarvisLive
        from core.room_sense import RoomSense
        obj = JarvisLive.__new__(JarvisLive)
        obj._room = RoomSense()
        speed.set_profile('fast')
        self.assertFalse(obj._proactive_wanted())                        # just the user: full speed
        obj._room.heard({'result': 'stranger', 'score': 0.1, 'seconds': 3}, now=__import__('time').monotonic())
        self.assertTrue(obj._proactive_wanted())                         # a second voice: weigh each sentence
        asked = []
        obj.request_reconnect = lambda keep_context=True, reason='': asked.append((keep_context, reason))
        obj._room_changed()
        self.assertEqual(asked, [(True, 'someone else is talking')])     # the conversation is kept
        speed.set_profile('standard')
        obj._room = RoomSense()
        self.assertTrue(obj._proactive_wanted())                         # standard profile: always on

    def test_spoken_reply_time_is_measured(self):
        from core import performance
        performance.cancel_response()
        performance.voice_heard()
        performance.first_audio()
        names = [t['name'] for t in performance.snapshot()['timings']]
        self.assertIn('speech_to_first_audio_received', names)

if __name__=='__main__':unittest.main()
