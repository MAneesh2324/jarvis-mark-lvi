import json
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np


class Recall(unittest.TestCase):
    def test_date_phrases(self):
        from core.recall import parse_when
        today = date(2026, 11, 5)   # a Thursday
        self.assertEqual(parse_when('yesterday', today), (date(2026, 11, 4), date(2026, 11, 4)))
        self.assertEqual(parse_when('what did I say last week', today), (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(parse_when('on monday', today), (date(2026, 11, 2), date(2026, 11, 2)))
        self.assertEqual(parse_when('in october', today), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(parse_when('on 2026-11-02', today), (date(2026, 11, 2), date(2026, 11, 2)))
        self.assertIsNone(parse_when('what is my risk rule', today))

    def test_keywords_drop_question_words(self):
        from core.recall import keywords
        self.assertEqual(keywords('What did I decide about my risk per trade last week?'), ['risk', 'trade'])

    def test_timeline_search_and_forget(self):
        from core import recall
        with tempfile.TemporaryDirectory() as tmp, patch.object(recall, 'TIMELINE_DB', Path(tmp) / 't.db'), \
                patch('memory.conversation_journal.DB_PATH', Path(tmp) / 'j.db'), \
                patch('memory.conversation_archive.DB_PATH', Path(tmp) / 'a.db', create=True):
            eid = recall.add_entry('2026-11-04', 'decision', 'Decided to risk 1% per trade on forex')
            recall.add_entry('2026-11-04', 'decision', 'Decided to risk 1% per trade on forex')   # duplicate ignored
            found = recall.search('what did I decide about risk', 'any time')
            self.assertEqual(found['matches'][0]['entry_id'], eid)
            self.assertEqual(recall.forget(eid)['deleted'], 1)
            self.assertFalse(recall.search('risk')['matches'])


class Research(unittest.TestCase):
    def test_job_runs_to_a_cited_report(self):
        from core import research_agent as ra, notify
        sent = []
        sink = lambda k, t, s, u: sent.append((k, t))
        notify.register(sink)
        answers = iter(['Writing notes [1]', '# Report\n\n## Key findings\n- A fact [1]', 'Short spoken summary.'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(ra, 'JOBS', Path(tmp) / 'jobs'), \
                patch.object(ra, 'REPORTS', Path(tmp) / 'reports'), \
                patch.object(ra, '_ask', side_effect=lambda prompt, as_json=False, timeout=0:
                             {'title': 'Test', 'questions': ['q one']} if as_json else next(answers)), \
                patch.object(ra, '_web', return_value=[{'title': 'Src', 'url': 'https://example.com/a', 'snippet': 's'}]), \
                patch.object(ra, '_read', return_value='page text'):
            job = ra.start('Research something useful for testing', 'quick')
            for _ in range(100):
                if ra.status(job['id'])['state'] != 'running':
                    break
                time.sleep(0.05)
            st = ra.status(job['id'])
            self.assertEqual(st['state'], 'done', st)
            report = Path(st['report_path']).read_text()
            self.assertIn('## Sources', report)
            self.assertIn('https://example.com/a', report)
        notify.unregister(sink)
        self.assertTrue(any(k == 'research' for k, _ in sent))

    def test_rejects_vague_goal(self):
        from core import research_agent as ra
        with self.assertRaises(ValueError):
            ra.start('x')


class Wellbeing(unittest.TestCase):
    def _speech(self, rng, f0=125, amp=0.12, syl=4.0, var=12, secs=2.0, sr=16000):
        t = np.arange(int(secs * sr)) / sr
        ph = 2 * np.pi * np.cumsum(f0 + var * np.sin(2 * np.pi * 0.7 * t)) / sr
        x = sum(np.sin(k * ph) / k for k in range(1, 8))
        env = np.clip(np.sin(np.pi * syl * t) ** 2, 0, 1) * 0.85 + 0.15
        return (x * env * amp / np.abs(x).max() * 32767).astype(np.int16)

    def _say(self, w, clip):
        for i in range(0, len(clip) - 1024, 1024):
            w.feed(clip[i:i + 1024])
        for _ in range(20):
            w.feed(np.zeros(1024, dtype=np.int16))
        deadline = time.time() + 5
        while (not w.q.empty() or w._busy) and time.time() < deadline:
            time.sleep(0.01)

    def test_learns_baseline_then_spots_a_tired_voice(self):
        from core import wellbeing as wb
        rng = np.random.default_rng(1)
        with tempfile.TemporaryDirectory() as tmp, patch.object(wb, 'BASELINE', Path(tmp) / 'b.json'), \
                patch.object(wb, 'CONFIG', Path(tmp) / 'c.json'):
            w = wb.Wellbeing()
            for _ in range(9):
                self._say(w, self._speech(rng, f0=125 + rng.normal(0, 3)))
                self.assertIsNone(w.end_turn('a normal sentence here'))
            notes = []
            for _ in range(3):
                self._say(w, self._speech(rng, f0=118, amp=0.04, syl=2.4, var=4, secs=3.0))
                notes.append(w.end_turn('a normal sentence here'))   # same words, said more slowly and quietly
            self.assertEqual(w.mood, 'tired')
            self.assertTrue(any(n and 'tired' in n for n in notes))

    def test_words_and_break_reminder(self):
        from core import wellbeing as wb
        self.assertEqual(wb.classify(None, "honestly I'm exhausted")[0], 'tired')
        self.assertEqual(wb.classify(None, 'ugh why is this not working again')[0], 'stressed')
        with tempfile.TemporaryDirectory() as tmp, patch.object(wb, 'BASELINE', Path(tmp) / 'b.json'), \
                patch.object(wb, 'CONFIG', Path(tmp) / 'c.json'):
            w = wb.Wellbeing()
            w.session_start = time.time() - 125 * 60
            self.assertIn('break', w.care_check())
            self.assertIsNone(w.care_check())           # not repeated within the hour
            wb.configure(enabled=False)
            w.last_break = 0
            self.assertIsNone(w.care_check())


class PhoneLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from core import phone_link as pl
        self.pl = pl
        self.p = patch.object(pl, 'CONFIG', Path(self.tmp.name) / 'phone.json')
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_pairing_then_only_paired_chat_is_served(self):
        calls = []

        def fake_call(token, method, timeout=20, timeout_s=None, **params):
            calls.append((method, params))
            return {'username': 'jarvis_test_bot'} if method == 'getMe' else {}

        got = []
        with patch.object(self.pl, '_call', side_effect=fake_call), patch.object(self.pl.PhoneLink, 'start'):
            link = self.pl.PhoneLink(on_text=lambda text, reply: (got.append(text), reply('done')))
            info = link.set_token('123456:' + 'A' * 35)
            code = info['pair_code']
            private = {'id': 42, 'type': 'private'}
            link._handle({'chat': private, 'text': '/pair 000000' if code != '000000' else '/pair 111111'})
            self.assertIsNone(link.cfg['chat_id'])
            link._handle({'chat': private, 'text': f'/pair {code}'})
            self.assertEqual(link.cfg['chat_id'], 42)
            link._handle({'chat': {'id': 99, 'type': 'private'}, 'text': 'delete everything'})
            self.assertEqual(got, [])
            link._handle({'chat': private, 'text': 'what is the news'})
            self.assertEqual(got, ['what is the news'])
        self.assertEqual(oct(Path(self.pl.CONFIG).stat().st_mode & 0o777), '0o600')
        self.assertTrue(any(m == 'sendMessage' and p.get('chat_id') == 99 and 'private' in p['text'] for m, p in calls))

    def test_alerts_respect_quiet_hours_and_kinds(self):
        link = self.pl.PhoneLink()
        link.cfg.update(token='t', chat_id=1, alerts=True, quiet_start=0, quiet_end=0)
        with patch.object(link, 'send', return_value=True) as send:
            self.assertTrue(link.alert('research', 'done'))
            self.assertFalse(link.alert('unknown-kind', 'x'))
            link.cfg.update(quiet_start=0, quiet_end=23)
            with patch.object(link, '_quiet', return_value=True):
                self.assertFalse(link.alert('research', 'quiet please'))
                self.assertTrue(link.alert('security', 'urgent', urgent=True))
        self.assertEqual(send.call_count, 2)

    def test_bad_token_is_refused(self):
        with self.assertRaises(ValueError):
            self.pl.PhoneLink().set_token('not-a-token')


class OwnerGuard(unittest.TestCase):
    def test_fbank_shape_and_normalisation(self):
        from core.owner_guard import fbank
        t = np.arange(32000) / 16000
        f = fbank((np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16))
        self.assertEqual(f.shape[1], 80)
        self.assertEqual(f.shape[0], 198)
        self.assertLess(abs(float(f.mean())), 1e-3)

    def test_voice_enrolment_and_stranger_verdict(self):
        from core import owner_guard as og
        engine = MagicMock()
        owner_vec, other_vec = np.ones(256), np.r_[np.ones(128), -np.ones(128)]
        engine.embed.side_effect = [owner_vec] * 3 + [owner_vec * 1.01, other_vec]
        with tempfile.TemporaryDirectory() as tmp, patch.object(og, 'STORE', Path(tmp)), \
                patch.object(og, '_speaker_engine', return_value=engine), patch.object(og, 'CONFIG', Path(tmp) / 'c.json'):
            g = og.VoiceGuard()
            g.owner = None
            g.start_enrolment(3)
            speech = np.full(16000 * 2, 3000, dtype=np.int16)
            for i in range(3):
                g.buf = [speech]
                r = g.end_turn()
            self.assertTrue(r['enrolled'])
            self.assertTrue((Path(tmp) / 'voice.npy').exists())
            g.buf = [speech]
            self.assertEqual(g.end_turn()['result'], 'owner')
            g.buf = [speech]
            self.assertEqual(g.end_turn()['result'], 'stranger')

    def test_face_check_reports_not_enrolled(self):
        from core import owner_guard as og
        with tempfile.TemporaryDirectory() as tmp, patch.object(og, 'STORE', Path(tmp)):
            self.assertEqual(og.check_face()['result'], 'not_enrolled')


class Tools(unittest.TestCase):
    def test_all_new_tools_register(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        for name in ('memory_recall', 'research_agent', 'wellbeing', 'phone_link', 'owner_guard'):
            self.assertTrue(reg.has(name), name)


if __name__ == '__main__':
    unittest.main()


class TokenHandling(unittest.TestCase):
    TOKEN = '1234567890:AAHCQRmlXvExUF9KR-SzdsKs8rroo9IcvDE'

    def test_redact_hides_bot_tokens(self):
        import main
        out = main._redact(f"{{'text': '{self.TOKEN}', 'action': 'configure'}}")
        self.assertNotIn(self.TOKEN, out)
        self.assertIn('[token-hidden]', out)

    def test_pasted_token_in_any_wording_is_handled_locally(self):
        import main
        obj = main.JarvisLive.__new__(main.JarvisLive)
        seen = []
        obj._phonelink_command = lambda cmd: seen.append(cmd)
        obj._send_typed_command = MagicMock()
        obj._on_text_command(f'here is my telegram bot token {self.TOKEN} thanks')
        self.assertEqual(seen, ['/phonelink token ' + self.TOKEN])
        obj._send_typed_command.assert_not_called()

    def test_tool_rejects_a_misheard_token_helpfully(self):
        from actions import phone_link as tool
        with patch('core.phone_link._call', side_effect=RuntimeError('Unauthorized')):
            out = tool.phone_link({'action': 'set_token', 'token': self.TOKEN})
        self.assertIn('paste', out)
