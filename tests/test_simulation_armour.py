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


if __name__ == '__main__':
    unittest.main()
