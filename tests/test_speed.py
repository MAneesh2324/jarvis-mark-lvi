"""Speed fixes (2026-11-06): less to read before every reply, quicker location, look-ups side by side."""
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock


class Instructions(unittest.TestCase):
    def test_capability_list_uses_the_short_brief(self):
        import main
        long = 'Does many things. ' + 'Detail ' * 60
        text = main._describe_tools([{'name': 'a', 'description': long, 'brief': 'Short summary.'},
                                     {'name': 'b', 'description': long}])
        self.assertIn('- a: Short summary.', text)
        self.assertIn('- b: Does many things.', text)
        self.assertNotIn('Detail', text)

    def test_finished_missions_are_not_read_into_every_session(self):
        from core import mission_store as ms
        from datetime import datetime, timezone, timedelta
        fresh = datetime.now(timezone.utc).isoformat(timespec='seconds')
        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec='seconds')
        items = [{'id': 1, 'state': 'completed', 'updated': fresh}, {'id': 2, 'state': 'failed', 'updated': old},
                 {'id': 3, 'state': 'interrupted', 'updated': fresh}]
        full = {3: {'id': 3, 'goal': 'Research telescopes', 'state': 'interrupted', 'steps': [], 'events': []}}
        with mock.patch.object(ms, 'listing', return_value=items), mock.patch.object(ms, 'get', side_effect=lambda k: full[k]):
            text = ms.resume_context()
        self.assertIn('Research telescopes', text)
        with mock.patch.object(ms, 'listing', return_value=items[:2]):
            self.assertEqual(ms.resume_context(), '')

    def test_session_context_is_trimmed_before_it_gets_slow(self):
        import main
        self.assertLess(main.LIVE_CONTEXT_TARGET_TOKENS, main.LIVE_CONTEXT_TRIGGER_TOKENS)
        self.assertLessEqual(main.LIVE_CONTEXT_TRIGGER_TOKENS, 80_000)

    def test_only_look_ups_run_side_by_side(self):
        import main
        self.assertIn('my_location', main._READ_ONLY_TOOLS)
        for acting in ('computer_control', 'send_message', 'email', 'browser_control', 'open_app', 'file_controller'):
            self.assertNotIn(acting, main._READ_ONLY_TOOLS)


class ReplySpeedLog(unittest.TestCase):
    def test_each_reply_logs_its_delay(self):
        from core import performance
        performance.voice_heard()
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(performance, 'monotonic', return_value=performance.monotonic() + 4):
            performance.first_audio()
        self.assertIn('[Speed] voice reply began', out.getvalue())
        self.assertIn('slow', out.getvalue())


class Location(unittest.TestCase):
    def test_a_recent_fix_is_reused(self):
        from core import location as L
        self.assertGreaterEqual(L.CACHE_SECONDS, 600)
        fix = {'latitude': 9.93, 'longitude': 76.26, 'accuracy_m': 80, 'source': 'Mac location services (Wi-Fi)',
               'at': __import__('time').time(), 'address': 'Kochi'}
        with mock.patch.object(L, '_cache', fix), mock.patch.object(L, '_phone_fix', None), \
                mock.patch.object(L, '_corelocation') as corel, mock.patch.object(L, '_ip_fix') as ip:
            out = L.current()
        corel.assert_not_called()
        ip.assert_not_called()
        self.assertEqual(out['address'], 'Kochi')


if __name__ == '__main__':
    unittest.main()
