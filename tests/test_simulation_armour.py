"""Simulation board (#4) and virtual-armour remote commands (#7)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class GoalAndSavings(unittest.TestCase):
    def test_goal_is_reproducible_and_slower_than_the_naive_plan(self):
        from core.scenario_simulator import run
        args = {'total_hours': 300, 'hours_per_day': 3, 'consistency_percent': 75, 'deadline_days': 150}
        a, b = run('goal', args), run('goal', args)
        self.assertEqual(a['finish_day_median'], b['finish_day_median'])
        self.assertEqual(a['naive_finish_day'], 100)
        self.assertGreater(a['finish_day_median'], 100)          # skipped days cost time
        self.assertLessEqual(a['finish_day_p05'], a['finish_day_median'])
        self.assertLessEqual(a['finish_day_median'], a['finish_day_p95'])
        self.assertTrue(0 <= a['simulated_fraction_done_by_deadline_percent'] <= 100)
        self.assertEqual(a['fan_chart'][0]['day'], 0)
        self.assertAlmostEqual(a['fan_chart'][-1]['median'], 300)

    def test_goal_already_done_and_unreachable(self):
        from core.scenario_simulator import run
        self.assertEqual(run('goal', {'total_hours': 10, 'hours_per_day': 1, 'hours_done': 10})['finish_day_median'], 0)
        far = run('goal', {'total_hours': 5000, 'hours_per_day': .5, 'max_days': 30, 'paths': 200})
        self.assertIsNone(far['finish_day_median'])
        self.assertEqual(far['simulated_fraction_unfinished_at_horizon_percent'], 100)

    def test_goal_rejects_bad_input(self):
        from core.scenario_simulator import run
        with self.assertRaises(ValueError):
            run('goal', {'total_hours': 100, 'hours_per_day': 30})
        with self.assertRaises(ValueError):
            run('goal', {'total_hours': 100})

    def test_savings_without_volatility_is_exact(self):
        from core.scenario_simulator import run
        r = run('savings', {'monthly_contribution': 100, 'months': 12, 'start_balance': 50, 'target': 1000})
        self.assertAlmostEqual(r['final_balance_median'], 1250)
        self.assertEqual(r['total_paid_in'], 1250)
        self.assertEqual(r['simulated_fraction_reaching_target_percent'], 100)

    def test_headline_for_every_kind_and_comparison(self):
        from core.scenario_simulator import run, compare, headline
        cases = {'goal': {'total_hours': 50, 'hours_per_day': 2},
                 'savings': {'monthly_contribution': 10, 'months': 6},
                 'forex': {'start_rate': 1.1, 'annual_return_percent': 0, 'annual_volatility_percent': 10, 'days': 20, 'paths': 200},
                 'trade_stress': {'equity': 1000, 'units': 1000, 'pair_start': 1.1, 'pair_move_percent': -1, 'quote_to_account': 1},
                 'outage': {'requests_per_minute': 10, 'outage_minutes': 5, 'affected_percent': 100, 'capacity_per_minute': 20}}
        for kind, args in cases.items():
            h = headline(run(kind, args))
            self.assertTrue(h['title'] and h['verdict'] and h['metrics'], kind)
        c = headline(compare('goal', cases['goal'], {'hours_per_day': 4}))
        self.assertIn('hours_per_day 2→4', c['verdict'])


class SimulatorTool(unittest.TestCase):
    def setUp(self):
        import core.scenario_simulator as sim
        self._tmp = tempfile.TemporaryDirectory()
        self._p = patch.object(sim, 'LAST', Path(self._tmp.name) / 'last.json')
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_tool_shows_the_board_and_returns_the_headline(self):
        from actions.scenario_simulator import simulate
        ui = MagicMock()
        out = simulate({'kind': 'goal', 'parameters_json': json.dumps({'total_hours': 40, 'hours_per_day': 2})}, player=ui)
        ui.show_simulation.assert_called_once()
        self.assertEqual(ui.show_simulation.call_args[0][0]['kind'], 'goal')
        self.assertIn('shown_on_hologram', out)
        self.assertIn('median run reaches', out)

    def test_close_and_errors(self):
        from actions.scenario_simulator import simulate
        ui = MagicMock()
        simulate({'close_display': True}, player=ui)
        ui.show_simulation.assert_called_once_with(None)
        self.assertIn('Choose', simulate({'kind': 'nope', 'parameters_json': '{}'}, player=ui))


class Board(unittest.TestCase):
    def test_board_paints_every_kind_offscreen(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from core.simulation_view import SimulationHologram
        from core.scenario_simulator import run, compare
        w = SimulationHologram()
        for size in ((1000, 600), (420, 640)):
            w.resize(*size)
            for r in (run('goal', {'total_hours': 30, 'hours_per_day': 2, 'deadline_days': 20}),
                      run('trade_stress', {'equity': 1000, 'units': 1000, 'pair_start': 1.1, 'pair_move_percent': 1, 'quote_to_account': 1}),
                      compare('savings', {'monthly_contribution': 10, 'months': 6}, {'monthly_contribution': 20})):
                w.set_result(r)
                for t in (0, 1.5, 20):
                    w.started -= t
                    self.assertFalse(w.grab().isNull())
        self.assertTrue(w.finished())
        app.processEvents()


class ArmourFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        import core.remote_armour as ra
        self.ra = ra
        self.p = [patch.object(ra, 'HOME', self.home), patch.object(ra, 'INBOX', self.home / 'Downloads' / 'From Phone')]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def _file(self, rel, data=b'x'):
        f = self.home / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return f

    def test_never_send_list(self):
        ok = self._file('Documents/resume.pdf')
        self.assertEqual(self.ra.allowed_path(ok), ok)
        for rel in ('.ssh/id_ed25519', 'Library/Cookies/Cookies.binarycookies', 'proj/.env', 'proj/.env.local',
                    'proj/server.pem', 'Mark-LVI/config/api_keys.json', 'Desktop/groq_api_key.txt',
                    'notes/passwords.xlsx', '.aws/credentials'):
            with self.assertRaises(ValueError, msg=rel):
                self.ra.allowed_path(self._file(rel))
        with self.assertRaises(ValueError):
            self.ra.allowed_path('/etc/hosts')                   # outside home
        with self.assertRaises(ValueError):
            self.ra.allowed_path(self.home / 'Documents')        # a folder

    def test_size_limit(self):
        big = self._file('big.bin')
        with patch.object(self.ra, 'MAX_SEND', 0):
            with self.assertRaises(ValueError):
                self.ra.allowed_path(big)

    def test_find_skips_denied_files(self):
        good = self._file('Desktop/oscp-plan.xlsx')
        bad = self._file('Desktop/oscp-token.txt')
        with patch('core.mac_find.find', return_value={'results': [{'path': str(bad)}, {'path': str(good)}]}), \
                patch.object(self.ra.platform, 'system', return_value='Darwin'):
            found = self.ra.find_files('oscp')
        self.assertEqual([f['name'] for f in found], ['oscp-plan.xlsx'])

    def test_incoming_never_overwrites_or_escapes(self):
        a = self.ra.save_incoming('../../evil.sh', b'1')
        b = self.ra.save_incoming('../../evil.sh', b'2')
        self.assertEqual(a.parent, self.ra.INBOX)
        self.assertNotEqual(a, b)
        self.assertEqual(a.read_bytes(), b'1')


class ArmourCommands(unittest.TestCase):
    def _link(self, remote=True):
        from core.phone_link import PhoneLink
        with patch('core.phone_link.load', return_value={'token': '1:x', 'chat_id': 42, 'enabled': True, 'alerts': True,
                                                         'remote': remote, 'quiet_start': 23, 'quiet_end': 7,
                                                         'alert_kinds': []}):
            link = PhoneLink()
        link.replies = []
        link._reply = lambda chat, text: link.replies.append((chat, text))
        return link

    def _msg(self, text, chat=42):
        return {'chat': {'id': chat, 'type': 'private'}, 'text': text}

    def test_screen_command_sends_a_photo(self):
        link = self._link()
        link.send_photo = MagicMock(return_value=True)
        with patch('core.remote_armour.screenshot', return_value=b'jpg'):
            link._handle(self._msg('/screen'))
        link.send_photo.assert_called_once()
        self.assertEqual(link.send_photo.call_args[0][0], b'jpg')

    def test_stranger_cannot_run_commands(self):
        link = self._link()
        link.send_photo = MagicMock()
        with patch('core.remote_armour.screenshot', return_value=b'jpg') as shot:
            link._handle(self._msg('/screen', chat=999))
        shot.assert_not_called()
        self.assertIn('private', link.replies[-1][1])

    def test_kill_switch_is_one_way(self):
        link = self._link()
        with patch('core.phone_link.save'):
            link._handle(self._msg('/remote off'))
            self.assertFalse(link.cfg['remote'])
            link._handle(self._msg('/remote on'))              # the phone cannot turn it back on
        self.assertFalse(link.cfg['remote'])
        with patch('core.remote_armour.screenshot') as shot:
            link._handle(self._msg('/screen'))
        shot.assert_not_called()
        self.assertIn('off', link.replies[-1][1])

    def test_file_lists_then_sends_choice(self):
        link = self._link()
        link.send_document = MagicMock(return_value=True)
        found = [{'path': '/h/a.pdf', 'name': 'a.pdf', 'size_mb': 1, 'modified': 'x'},
                 {'path': '/h/b.pdf', 'name': 'b.pdf', 'size_mb': 1, 'modified': 'y'}]
        with patch('core.remote_armour.find_files', return_value=found):
            link._handle(self._msg('/file report'))
        self.assertIn('2. b.pdf', link.replies[-1][1])
        link._handle(self._msg('/file 2'))
        self.assertEqual(link.send_document.call_args[0][0], '/h/b.pdf')

    def test_plain_text_still_goes_to_jarvis(self):
        link = self._link()
        link.on_text = MagicMock()
        link._handle(self._msg('what is on my calendar'))
        link.on_text.assert_called_once()

    def test_failures_are_reported_not_raised(self):
        link = self._link()
        with patch('core.remote_armour.camera', side_effect=RuntimeError('Camera is busy')):
            link._handle(self._msg('/cam'))
        self.assertIn('Camera is busy', link.replies[-1][1])

    def test_voice_tool_send_file_refuses_secrets(self):
        from actions.phone_link import phone_link
        link = self._link()
        with patch('core.phone_link.instance', return_value=link), patch('core.phone_link._upload') as up:
            out = phone_link({'action': 'send_file', 'path': str(Path.home() / '.ssh' / 'id_rsa')})
        up.assert_not_called()                                    # nothing left the Mac
        self.assertIn('never-send', out)


class ShowAndLab(unittest.TestCase):
    def test_stray_parameter_no_longer_cancels_the_run(self):
        from core.scenario_simulator import run
        r = run('trade_stress', {'equity': 10000, 'pair_start': 1.1, 'pair_move_percent': 1, 'quote_to_account': 1,
                                 'units': 20000, 'rr': 2})              # the exact call that failed in the live app
        self.assertEqual(r['ignored_parameters'], ['rr'])
        with self.assertRaisesRegex(ValueError, 'total_hours'):
            run('goal', {'hours_per_day': 3})

    def test_show_last_replays_or_demos(self):
        import core.scenario_simulator as sim
        from actions.scenario_simulator import simulate
        with tempfile.TemporaryDirectory() as tmp, patch.object(sim, 'LAST', Path(tmp) / 'last.json'), \
                patch.object(sim, 'REPORTS', Path(tmp)):
            ui = MagicMock()
            out = simulate({}, player=ui)                                # nothing run yet → demo
            self.assertIn('demo', out)
            simulate({'kind': 'goal', 'parameters_json': json.dumps({'total_hours': 40, 'hours_per_day': 2})}, player=ui)
            out = simulate({'show_last': True}, player=ui)
            self.assertIn('last simulation', out)
            self.assertEqual(ui.show_simulation.call_args[0][0]['assumptions']['total_hours'], 40)

    def test_open_lab_starts_the_window_process(self):
        import actions.scenario_simulator as act
        proc = MagicMock()
        proc.poll.return_value = None
        with patch('subprocess.Popen', return_value=proc) as popen, patch('time.sleep'):
            act._lab = None
            out = act.simulate({'open_lab': True})
        self.assertIn('simulation_live.py', popen.call_args[0][0][1])
        self.assertIn('opened', out)
        act._lab = None


class BacktestBoard(unittest.TestCase):
    def test_equity_curve_and_board(self):
        from core.trading_lab import _curve
        from core.scenario_simulator import from_backtest, headline
        curve = _curve([2, -1, -1, 2])
        self.assertEqual(curve, [[0, 0.0], [1, 2.0], [2, 1.0], [3, 0.0], [4, 2.0]])
        self.assertEqual(len(_curve([1] * 1000)), 300)
        board = from_backtest({'strategy': 'breaker_retest', 'instrument': 'XAUUSD', 'interval': '15m',
                               'settings': {'reward_to_risk': 2}, 'closed_trades': 4, 'wins': 2, 'losses': 2,
                               'win_rate_percent': 50, 'total_r': 2, 'max_drawdown_r': 2, 'equity_curve_r': curve})
        self.assertEqual(board['y_unit'], 'R')
        self.assertEqual(board['fan_chart'][3]['p95'], 2.0)          # running peak shades the drawdown
        h = headline(board)
        self.assertIn('XAUUSD', h['title'])
        self.assertEqual(dict((k, v) for k, v, _ in h['metrics'])['TOTAL R'], '+2.00R')

    def test_trading_tool_shows_backtest_on_board(self):
        import actions.trading_lab as act
        import core.scenario_simulator as sim
        stats = {'strategy': 'breaker_retest', 'closed_trades': 1, 'total_r': 2, 'equity_curve_r': [[0, 0], [1, 2]]}
        ui = MagicMock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(sim, 'LAST', Path(tmp) / 'l.json'), \
                patch.object(sim, 'REPORTS', Path(tmp)), patch('core.trading_lab.load', return_value={}), \
                patch('core.trading_lab.backtest', return_value=dict(stats)):
            out = act.trading_lab({'action': 'backtest', 'symbol': 'XAUUSD'}, player=ui)
            self.assertEqual(sim.last()['kind'], 'backtest')          # "show me the simulation" replays it
        self.assertEqual(ui.show_simulation.call_args[0][0]['kind'], 'backtest')
        self.assertIn('"shown_on_hologram": true', out)
        self.assertNotIn('equity_curve_r', out)

    def test_numbers_are_formatted_for_the_board(self):
        from core.simulation_view import _num, _at
        self.assertEqual(_num(389444), '389.4k')
        self.assertEqual(_num(2.5e6), '2.50M')
        self.assertEqual(_num(300, 'hours'), '300 h')
        self.assertEqual(_num(-3.4, 'R'), '-3.4R')
        self.assertEqual(_num(1.10234), '1.1023')
        row = _at([{'day': 0, 'p05': 0, 'median': 0, 'p95': 0}, {'day': 10, 'p05': 10, 'median': 20, 'p95': 30}], 5)
        self.assertEqual(row['median'], 10)


class SweepMssBreaker(unittest.TestCase):
    """The user's setup on a hand-built chart: sweep at candle 32, MSS close at 35, breaker retest at 47."""

    def setUp(self):
        self.candles = json.loads((Path(__file__).parent / 'fixtures' / 'sweep_mss_breaker_short.json').read_text())

    def test_detects_sweep_shift_and_retest(self):
        import core.trading_lab as t
        s = t.Series(self.candles, 3)
        sig = t._sweep_mss_breaker(s, t.swings(s), {})
        self.assertEqual(len(sig), 1)
        e = sig[0]
        self.assertEqual((e['direction'], e['i'], e['setup']['sweep_i'], e['setup']['mss_i']), ('short', 47, 32, 35))
        self.assertAlmostEqual(e['entry'], 99.4)
        self.assertGreater(e['stop'], 106.5)                        # stop above the sweep high
        self.assertLess(t._sweep_mss_breaker(s, t.swings(s), {'stop_at': 'breaker'})[0]['stop'], 101)

    def test_money_costs_and_trade_list(self):
        import core.trading_lab as t
        r = t.backtest({'candles': self.candles, 'symbol': 'T'}, 'sweep_mss_breaker', rr=2,
                       account_balance=10000, risk_percent=1, spread=.3, commission=2)
        tr = r['trades'][0]
        risk = tr['stop'] - tr['entry']
        self.assertAlmostEqual(tr['target'], tr['entry'] - 2 * risk, places=3)
        self.assertAlmostEqual(tr['r'], 2 - .3 / risk, places=2)     # the spread costs R
        self.assertAlmostEqual(tr['pnl'], tr['r'] * 100 - 2, places=1)
        self.assertEqual(tr['result'], 'win')
        self.assertEqual(r['money']['end_balance'], tr['balance'])
        self.assertEqual(r['money']['largest_loss'], 0)
        none = t.backtest({'candles': self.candles, 'symbol': 'T'}, 'sweep_mss_breaker', rr=2,
                          from_time=self.candles[48]['t'])          # window starts after the entry
        self.assertEqual(none['closed_trades'], 0)

    def test_invalidated_when_sweep_high_is_taken_first(self):
        import core.trading_lab as t
        c = [dict(x) for x in self.candles]
        c[40]['h'] = 107.0                                          # price runs above the sweep high before the retest
        s = t.Series(c, 3)
        self.assertEqual(t._sweep_mss_breaker(s, t.swings(s), {}), [])

    def test_tool_lists_every_trade_and_uses_the_window(self):
        import actions.trading_lab as act
        import core.scenario_simulator as sim
        ui = MagicMock()
        data = {'candles': self.candles, 'symbol': 'GC=F', 'requested': 'XAUUSD', 'interval': '15m'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(sim, 'LAST', Path(tmp) / 'l.json'), \
                patch.object(sim, 'REPORTS', Path(tmp)), patch('core.trading_lab.load', return_value=data) as load, \
                patch('time.time', return_value=self.candles[-1]['t'] + 60):
            out = act.trading_lab({'action': 'backtest', 'symbol': 'XAUUSD', 'interval': '15m', 'past_days': 7,
                                   'strategy': 'sweep_mss_breaker', 'account_balance': 10000, 'risk_percent': 1}, player=ui)
        self.assertEqual(load.call_args[0][0]['range'], '1mo')       # enough history for a 7-day window
        title, table = ui.show_content.call_args[0]
        self.assertIn('XAUUSD', title)
        self.assertIn('WIN', table)
        self.assertIn('+200.00   10,200.00', table)          # no spread passed: exactly 2R of 100
        board = ui.show_simulation.call_args[0][0]
        self.assertEqual(board['trades'][0]['result'], 'win')
        self.assertEqual(board['y_unit'], 'money')
        self.assertIn('"wins": 1', out)


if __name__ == '__main__':
    unittest.main()
