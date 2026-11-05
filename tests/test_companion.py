import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def fresh():
    from core.companion import Companion
    return Companion(Path(tempfile.mkdtemp()) / 'companion.json')


class Feelings(unittest.TestCase):
    def test_signals_from_what_the_user_says(self):
        from core.companion import Companion
        cases = {
            "I feel so low today, nothing is going right": 'low',
            "I lost money again, my stop loss hit twice": 'setback',
            "I'm nervous about the interview": 'anxious',
            "I can't focus at all, no motivation": 'unmotivated',
            "I made a profit on gold today": 'win',
            "I don't want to live anymore": 'crisis',
        }
        for text, kind in cases.items():
            self.assertIn(kind, Companion.signals(text), text)
        for calm in ("what's the weather", "the meeting passed quickly", "open the trading dashboard"):
            self.assertEqual(Companion.signals(calm), [], calm)

    def test_jarvis_feels_and_writes_the_right_note(self):
        c = fresh()
        note = c.on_user_turn("I feel really sad and lonely tonight")
        self.assertEqual(c.current()['feeling'], 'concerned')
        self.assertIn('Console first', note)
        c.last_note = 0
        note = c.on_user_turn("I nailed it, I passed my exam")
        self.assertEqual(c.current()['feeling'], 'proud')
        self.assertIn('proud', note)
        c.last_note = 0
        note = c.on_user_turn("I lost money again and my stop loss hit")
        self.assertIn('revenge trading', note)
        self.assertIn('passed my exam', note)                       # a hard moment is met with what they already did

    def test_crisis_is_never_rate_limited_and_gives_helplines(self):
        c = fresh()
        c.on_user_turn("I feel so low")
        note = c.on_user_turn("honestly I want to die")              # straight after another note
        self.assertIn('URGENT', note)
        self.assertIn('14416', note)

    def test_feelings_fade_back_to_warm(self):
        import core.companion as co
        c = fresh()
        c.on_user_turn("I can't focus, I keep procrastinating")
        self.assertEqual(c.current()['feeling'], 'determined')
        c.felt_at -= co.FADE_SECONDS + 1
        self.assertEqual(c.current()['feeling'], 'warm')

    def test_stressed_voice_alone_changes_the_feeling_but_sends_no_second_note(self):
        c = fresh()
        self.assertIsNone(c.on_user_turn("open the chart", mood='stressed'))
        self.assertEqual(c.current()['feeling'], 'calm')


class Memory(unittest.TestCase):
    def test_goals_wins_and_followups_are_remembered(self):
        c = fresh()
        c.on_user_turn("my goal is to become a consistently profitable trader")
        c.on_user_turn("tomorrow I have a job interview at 10")
        c.on_user_turn("I finished the backtest engine")
        self.assertEqual(c.data['goals'][0]['text'], 'become a consistently profitable trader')
        self.assertEqual(c.data['followups'][0]['what'], 'job interview')
        self.assertEqual(len(c.data['wins']), 1)
        block = c.context_block()
        self.assertIn('profitable trader', block)
        self.assertIn('finished the backtest', block)
        again = type(c)(c.path)                                     # it survives a restart
        self.assertEqual(again.data['goals'], c.data['goals'])

    def test_followups_come_due_and_are_asked_once(self):
        from core.companion import Companion
        c = fresh()
        c.data['followups'] = [{'what': 'exam', 'due': '2000-01-01', 'said': 'exam on monday', 'asked': False}]
        self.assertEqual(len(c.due_followups()), 1)
        self.assertIn('Ask how these went', c.context_block())
        c.mark_asked()
        self.assertEqual(c.due_followups(), [])
        thursday = date(2026, 11, 5)
        self.assertEqual(Companion._due('friday', thursday), '2026-11-06')
        self.assertEqual(Companion._due('on thursday', thursday), '2026-11-12')
        self.assertEqual(Companion._due('tomorrow', thursday), '2026-11-06')


class Focus(unittest.TestCase):
    def test_focus_session_counts_down_and_is_tallied(self):
        c = fresh()
        st = c.focus_start('gold backtest', 30)
        self.assertTrue(st['active'])
        self.assertTrue(c.focus_active())
        self.assertEqual(c.current()['feeling'], 'determined')
        self.assertIn('focus session on "gold backtest"', c.context_block())
        c.data['focus']['started'] -= 30 * 60
        c.data['focus']['ends'] -= 30 * 60
        said = c.tick()
        self.assertIn('Focus session complete: 30 minutes on gold backtest', said)
        self.assertFalse(c.focus_active())
        self.assertEqual(c.focus_totals()['today_minutes'], 30)
        self.assertEqual(c.current()['feeling'], 'proud')

    def test_streak_counts_consecutive_days(self):
        from datetime import timedelta
        c = fresh()
        d = date.today()
        c.data['focus_log'] = {(d - timedelta(days=i)).isoformat(): 25 for i in (1, 2, 3)}
        self.assertEqual(c.focus_totals()['streak_days'], 3)          # today not started yet still keeps it
        c.data['focus_log'][d.isoformat()] = 10
        self.assertEqual(c.focus_totals()['streak_days'], 4)


class Face(unittest.TestCase):
    def test_feelings_move_the_face_and_show_on_the_hud(self):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from core.avatar import HoloAvatar
        a = HoloAvatar()
        a.set_feeling('proud', 1.0)
        for _ in range(60):
            a.step(0.05, 0.0)
        self.assertGreater(a._smile, 0.6)
        a.set_feeling('concerned', 1.0)
        for _ in range(60):
            a.step(0.05, 0.0)
        self.assertLess(a._smile, 0.0)
        self.assertGreater(a._brow_shape, 0.5)                       # worried brows: inner ends raised
        import ui
        hud = ui.HudCanvas.__new__(ui.HudCanvas)
        hud._avatar = a
        hud.set_feeling('determined', 0.8, {'active': True, 'task': 'deep work', 'seconds_left': 600, 'minutes': 25})
        self.assertEqual(hud._feel[2], 'DETERMINED')
        self.assertEqual(hud._focus[0], 'deep work')
        from PyQt6.QtGui import QImage, QPainter
        img = QImage(400, 400, QImage.Format.Format_RGB32)
        p = QPainter(img)
        hud._paint_heart(p, 200, 180, 120, 380)                      # draws without error
        p.end()
        app.processEvents()

    def test_tool_registers(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('companion'))
        import core.companion as co
        with patch.object(co, '_instance', fresh()):
            from actions.companion import companion
            r = companion({'action': 'focus_start', 'task': 'reading', 'minutes': 20})
            self.assertIn('reading', str(r))
            self.assertIn('jarvis_feels', str(companion({'action': 'feelings'})))


if __name__ == '__main__':
    unittest.main()
