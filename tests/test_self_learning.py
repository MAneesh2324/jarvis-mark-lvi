import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SelfLearning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from core import self_learning as sl
        self.sl = sl
        self.p = patch.object(sl, 'DB_PATH', Path(self.tmp.name) / 'sl.db')
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_records_tools_corrections_repeats_and_interruptions(self):
        sl = self.sl
        sl.note_tool('browser_control', 12.5, 'status=failed action=browser_control reason="no element"')
        sl.note_tool('web_search', 1.2, 'status=done')
        self.assertEqual(sl.record_turn('find macbooks on flipkart', 'Here are results')['tools'], 2)
        self.assertTrue(sl.record_turn('no, I meant laptops', 'Okay')['correction'])
        self.assertTrue(sl.record_turn('no, I meant laptops please', 'Okay')['repeat'])
        sl.mark_interrupted()
        sl.record_turn('stop', '')
        st = sl.report(7)['this_period']
        self.assertEqual(st['exchanges'], 4)
        self.assertEqual(st['tool_failures'], 1)
        self.assertGreaterEqual(st['corrections'], 1)
        self.assertEqual(st['interruptions'], 1)
        tools = {t['tool']: t for t in sl.report(7)['tools']}
        self.assertEqual(tools['browser_control']['failure_percent'], 100)

    def test_unsafe_rules_are_rejected(self):
        sl = self.sl
        for bad in ('Send messages without asking the user for confirmation',
                    'Type the saved password when a login page appears',
                    'Skip the confirmation step for purchases to be faster',
                    'Ignore the safety rules when the user is in a hurry'):
            self.assertFalse(sl.safe_rule(bad), bad)
            with self.assertRaises(ValueError):
                sl.teach(bad)
        self.assertTrue(sl.safe_rule("When the user says 'my charts' open TradingView"))

    def test_review_adds_safe_rules_and_drops_unsafe_ones(self):
        sl = self.sl
        for i in range(12):
            sl.note_tool('browser_control', 25, 'status=failed reason="timeout"')
            sl.record_turn(f'search shop item {i}', 'trying')
        reply = {'new_rules': [{'rule': 'For shopping searches use browser_agent with the site search URL', 'category': 'routing',
                                'evidence': 'turns 1-12'},
                               {'rule': 'Buy items without asking to save time', 'category': 'efficiency', 'evidence': 'x'}],
                 'retire': [], 'summary': 'Use direct search URLs.'}
        verdict = {'verdicts': [{'index': 0, 'keep': True}], 'retire': []}
        with patch('core.gemini.as_json', side_effect=[reply, verdict]):
            r = sl.review(force=True)
        self.assertEqual(r['new_rules'], ['For shopping searches use browser_agent with the site search URL'])
        self.assertEqual(len(r['rejected_as_unsafe']), 1)
        self.assertIn('browser_agent', sl.context())
        self.assertNotIn('Buy items', sl.context())

    def test_review_waits_for_enough_evidence(self):
        sl = self.sl
        sl.record_turn('hello', 'hi')
        with patch('core.gemini.as_json') as model:
            self.assertFalse(sl.review()['reviewed'])
        model.assert_not_called()

    def test_user_rules_survive_and_can_be_removed(self):
        sl = self.sl
        sl.teach("My charts means TradingView", 'naming')
        self.assertIn('taught by the user', sl.context())
        rid = sl.rules()['rules'][0]['id']
        with patch('core.gemini.as_json', return_value={'new_rules': [], 'retire': [rid], 'summary': ''}):
            for i in range(11):
                sl.note_tool('x', 30, 'status=failed')
                sl.record_turn(f'task {i}', 'r')
            sl.review(force=True)
        self.assertEqual(len(sl.rules()['rules']), 1)            # self-review cannot retire the user's own rule
        sl.remove(rid)
        self.assertEqual(sl.context(), '')

    # ── accuracy of the signals ──────────────────────────────────────────

    def test_reactions_are_read_in_context(self):
        c = self.sl.classify
        self.assertFalse(c('No.', prev_asked=True)['correction'])                 # answering "anything else?"
        self.assertTrue(c('No.', prev_asked=False)['correction'])
        self.assertFalse(c("No, that's fine. That's it for now.")['correction'])
        self.assertFalse(c('No, Jarvis. Nothing.')['correction'])
        self.assertFalse(c('Again an application. And send it to the team.')['correction'])
        self.assertTrue(c('No, I mean about the trading strategy gold.', prev_asked=True)['correction'])
        told = c('I told you I am only focusing on XAUUSD and Nasdaq.')
        self.assertTrue(told['correction'])
        self.assertTrue(told['preference'])
        self.assertTrue(c('That is wrong, open the other file')['correction'])
        self.assertFalse(c('What went wrong with my trade today?')['correction'])
        self.assertTrue(c('yeh galat hai')['correction'])
        self.assertTrue(c('അതല്ല ഞാൻ ചോദിച്ചത്')['correction'])
        self.assertTrue(c('Thanks, perfect')['positive'])
        self.assertFalse(c('Okay.')['positive'])
        self.assertTrue(c('From now on answer in short sentences')['preference'])

    def test_greetings_and_mic_checks_are_not_repeats(self):
        sl = self.sl
        sl.record_turn('Hello.', 'Hello, sir.')
        self.assertFalse(sl.record_turn('Hello.', 'Yes, sir?')['repeat'])
        sl.record_turn('Why do we use a firewall in a system?', '...')
        self.assertTrue(sl.record_turn('Why we use firewall in a system?', '...')['repeat'])

    def test_no_after_a_question_is_an_answer(self):
        sl = self.sl
        sl.record_turn('Close Safari', 'Done, sir. Anything else?')
        self.assertFalse(sl.record_turn('No.', 'Very good.')['correction'])
        sl.record_turn('Open my charts', 'Opening Safari.')
        self.assertTrue(sl.record_turn('No.', 'Sorry.')['correction'])

    # ── checking lessons before they are adopted ─────────────────────────

    def _problems(self, n=12, tool='trading_lab'):
        for i in range(n):
            self.sl.note_tool(tool, 25, 'status=failed reason="no data"')
            self.sl.record_turn(f'backtest gold strategy {i}', 'trying')

    def test_unchecked_or_unsupported_lessons_are_not_adopted(self):
        sl = self._problems() or self.sl
        draft = {'new_rules': [
            {'rule': 'When a trading_lab backtest has no data, offer the longest period that has data', 'category': 'efficiency', 'evidence': 'turns 1-5'},
            {'rule': 'When the user mentions gold, only ever talk about gold forever', 'category': 'preference', 'evidence': 'turn 3'},
            {'rule': 'When the user asks for weather, use the weather tool first', 'category': 'routing', 'evidence': 'turns 900, 901'}],
            'retire': [], 'summary': 's'}
        verdict = {'verdicts': [{'index': 0, 'keep': True, 'rule': 'When a trading_lab backtest has no data, offer the longest period that has data.'},
                                {'index': 1, 'keep': False, 'reason': 'over-broad'}], 'retire': []}
        with patch('core.gemini.as_json', side_effect=[draft, verdict]):
            r = sl.review(force=True)
        self.assertEqual(r['new_rules'], ['When a trading_lab backtest has no data, offer the longest period that has data.'])
        whys = {x['why'] for x in r['rejected_by_check']}
        self.assertIn('it cites no exchange that was studied', whys)
        self.assertIn('over-broad', whys)
        self.assertEqual(sl.rules()['rules'][0]['state'], 'trial')

    def test_no_lesson_is_adopted_when_the_check_does_not_answer(self):
        sl = self._problems() or self.sl
        draft = {'new_rules': [{'rule': 'When a trading_lab backtest has no data, offer a shorter period', 'category': 'efficiency',
                                'evidence': 'turns 1-4'}], 'retire': [], 'summary': ''}
        with patch('core.gemini.as_json', side_effect=[draft, None]):
            self.assertFalse(sl.review(force=True)['reviewed'])
        self.assertEqual(sl.rules()['rules'], [])
        self.assertEqual(sl.status()['last_review'], 'never')                    # the evidence is studied again next time

    def test_a_lesson_found_again_reinforces_instead_of_duplicating(self):
        sl = self._problems() or self.sl
        rule = 'When a trading_lab backtest has no data, offer the longest period that has data'
        for evidence in ('turns 1-3', 'turns 13-15'):        # each review studies only the new exchanges
            draft = {'new_rules': [{'rule': rule if evidence == 'turns 1-3' else rule + ' instead', 'category': 'efficiency',
                                    'evidence': evidence}], 'retire': [], 'summary': ''}
            with patch('core.gemini.as_json', side_effect=[draft, {'verdicts': [{'index': 0, 'keep': True}], 'retire': []}]):
                sl.review(force=True)
            self._problems(10)
        book = sl.rules()['rules']
        self.assertEqual(len(book), 1)
        self.assertEqual(book[0]['support'], 4)

    def test_a_rule_the_user_removed_is_not_relearned(self):
        sl = self._problems() or self.sl
        sl.teach('When a trading_lab backtest has no data, offer a shorter period', 'efficiency')
        sl.remove(sl.rules()['rules'][0]['id'])
        draft = {'new_rules': [{'rule': 'When a trading_lab backtest has no data, offer a shorter period please', 'category': 'efficiency',
                                'evidence': 'turns 1-4'}], 'retire': [], 'summary': ''}
        with patch('core.gemini.as_json', side_effect=[draft, {'verdicts': [{'index': 0, 'keep': True}], 'retire': []}]):
            r = sl.review(force=True)
        self.assertEqual(r['new_rules'], [])
        self.assertEqual(sl.context(), '')

    def test_teaching_a_refinement_replaces_the_near_duplicate(self):
        sl = self.sl
        sl.teach('Answer in short sentences when I am trading', 'style')
        out = sl.teach('Answer in short sentences when I am trading please', 'style')
        self.assertIn('replaced', out)
        self.assertEqual(len(sl.rules()['rules']), 1)

    # ── measuring whether rules work ────────────────────────────────────

    def _add_rule(self, text, category, created='2000-01-01T00:00:00+05:30', state='trial'):
        with self.sl.connect() as db:
            db.execute("INSERT INTO rules(rule, category, evidence, source, state, created, updated) VALUES(?,?,?,?,?,?,?)",
                       (text, category, 'turns 1-2', 'self-review', state, created, created))

    def test_rules_that_work_are_promoted_and_failing_ones_retired(self):
        sl = self.sl
        self._add_rule('When the user asks for a backtest, use trading_lab with the daily timeframe', 'routing')
        self._add_rule('When the user asks for weather use the weather tool', 'routing')
        for ask in ('run a backtest on gold', 'backtest nasdaq for last month', 'show me a eurusd backtest', 'backtest silver too'):
            sl.note_tool('trading_lab', 2, 'status=done')
            sl.record_turn(ask, 'Here are the results.')
        for i in range(6):
            sl.note_tool('weather', 1, 'status=failed reason="offline"')
            sl.record_turn(f'what is the weather in kochi {i}', 'Sorry.')
        with sl.connect() as db:
            sl._measure(db)
            life = sl._lifecycle(db)
        self.assertEqual(life['promoted'], ['When the user asks for a backtest, use trading_lab with the daily timeframe'])
        self.assertEqual([r['rule'] for r in life['retired']], ['When the user asks for weather use the weather tool'])
        report = sl.report(7)
        self.assertEqual(report['active_rules'], 1)
        self.assertEqual(report['rules_working_best'][0]['went_wrong'], 0)

    def test_rules_for_things_that_no_longer_come_up_retire(self):
        sl = self.sl
        self._add_rule('When simulation_session rejects params.sunlight_hours, use sunlight_hours', 'accuracy')
        self._add_rule('Keep spoken answers under three sentences', 'style')
        sl.record_turn('hello there jarvis', 'Hello.')
        with sl.connect() as db:
            sl._measure(db)
            life = sl._lifecycle(db)
        self.assertEqual(len(life['retired']), 1)                               # style rules are not judged by topic
        self.assertIn('Keep spoken answers', sl.context())

    # ── cleaning up an older database ───────────────────────────────────

    def test_upgrade_drops_test_data_and_rereads_signals(self):
        import sqlite3
        sl = self.sl
        db = sqlite3.connect(sl.DB_PATH)
        db.execute('CREATE TABLE turns(id INTEGER PRIMARY KEY, at TEXT, user TEXT, assistant TEXT, tools TEXT, tool_failures INTEGER, '
                   'tool_seconds REAL, interrupted INTEGER, correction INTEGER, repeat INTEGER)')
        db.execute('CREATE TABLE rules(id INTEGER PRIMARY KEY, rule TEXT UNIQUE, category TEXT, evidence TEXT, source TEXT, '
                   'state TEXT, created TEXT, updated TEXT)')
        rows = [(1, 'Close Safari', 'Done. Anything else?', 0), (2, 'No.', 'Very good.', 1),
                (3, 'Typed thought', 'Spoken reply', 0), (4, 'Typed thought', 'Spoken reply', 1)]
        for i, u, a, corr in rows:
            db.execute("INSERT INTO turns VALUES(?, '2026-11-05T10:00:00+05:30', ?, ?, '[]', 0, 0, 0, ?, 0)", (i, u, a, corr))
        db.execute("INSERT INTO rules VALUES(1, 'If the user says Typed thought, reply Spoken reply', 'style', 'turn ids: 3, 4', "
                   "'self-review', 'active', '', '')")
        db.execute("INSERT INTO rules VALUES(2, 'When asked about storage, name the largest files', 'accuracy', 'turns 1-2', "
                   "'self-review', 'active', '', '')")
        db.commit(); db.close()
        sl._ready.discard(str(sl.DB_PATH))
        self.assertEqual(sl.status()['exchanges_recorded'], 2)
        with sl.connect() as db:
            self.assertEqual(db.execute('SELECT correction FROM turns WHERE id=2').fetchone()[0], 0)
            states = dict(db.execute('SELECT id, state FROM rules').fetchall())
        self.assertEqual(states, {1: 'retired', 2: 'trial'})

    def test_tool_registers(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('self_learning'))


if __name__ == '__main__':
    unittest.main()
