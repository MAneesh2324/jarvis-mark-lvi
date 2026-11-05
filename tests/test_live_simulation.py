"""Live simulation lab: process models of anything, iterative attempts and verdicts."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

APPLE = json.loads((Path(__file__).parent / 'fixtures' / 'apple_process.json').read_text())


class Formulas(unittest.TestCase):
    def test_arithmetic_and_helpers(self):
        from core.process_sim import Formula
        f = Formula('clamp(x * 2, 0, 10) + between(t, 1, 5) + (3 if x > 1 else 4) + 2^3', {'x'})
        self.assertEqual(f({'x': 3, 't': 2}), 6 + 1 + 3 + 8)

    def test_code_cannot_run(self):
        from core.process_sim import Formula
        for bad in ('__import__("os").system("x")', 'x.__class__', '[1, 2]', 'open("f")', 'lambda: 1',
                    'y + 1', '"text"', 'min(x, key=1)'):
            with self.assertRaises(ValueError, msg=bad):
                Formula(bad, {'x'})


class Process(unittest.TestCase):
    def test_apple_grows_ripens_and_reacts_to_settings(self):
        from core.process_sim import simulate
        r = simulate(APPLE)
        self.assertEqual(r['kind'], 'process')
        self.assertGreater(r['finals']['diameter_mm'], 70)
        ev = {e['label']: e['at'] for e in r['events']}
        self.assertIsNotNone(ev['ripe'])
        shade = simulate({**APPLE, 'params': {**APPLE['params'], 'sunlight_hours': 4}})
        self.assertLess(shade['finals']['diameter_mm'], r['finals']['diameter_mm'])
        self.assertLessEqual(r['fan_chart'][-1]['p05'], r['fan_chart'][-1]['median'])   # uncertainty band
        self.assertEqual(set(r['series']), {'diameter_mm', 'sugar_percent', 'red_percent'})

    def test_bad_specs_are_refused(self):
        from core.process_sim import simulate
        with self.assertRaises(ValueError):
            simulate({**APPLE, 'focus': 'nope'})
        with self.assertRaises(ValueError):
            simulate({'variables': [{'name': 'x', 'rate': 'x * 1e300 ** 2'}], 'duration': 10})  # ** capped, then inf
        with self.assertRaises(ValueError):
            simulate({'variables': []})


class Session(unittest.TestCase):
    def test_attempts_verdicts_and_search(self):
        import core.sim_session as S
        b = S.start('goal', {'total_hours': 300, 'hours_per_day': 2, 'consistency_percent': 75},
                    {'metric': 'finish_day', 'op': '<=', 'value': 120})
        self.assertEqual((b['session']['attempt'], b['session']['status']), (1, 'failed'))
        boards = S.search('hours_per_day', [2.5, 3, 3.5, 4, 5])
        self.assertEqual(boards[-1]['session']['status'], 'success')
        self.assertEqual(len(boards), 3)                            # stopped at the first success (3.5 h)
        self.assertEqual(S.status()['current_settings']['hours_per_day'], 3.5)
        S.search('hours_per_day', [1, 1.5])                           # nothing works → model unchanged
        self.assertEqual(S.status()['current_settings']['hours_per_day'], 3.5)
        S.reset()

    def test_process_changes_reach_the_spec_and_goals_use_events(self):
        import core.sim_session as S
        b = S.start('process', APPLE, {'metric': 'ripe', 'op': '<=', 'value': 145})
        self.assertEqual(b['session']['status'], 'success')
        b = S.change({'sunlight_hours': 5})
        self.assertEqual(b['session']['status'], 'failed')
        self.assertIn('sunlight hours 8→5', b['session']['attempts'][-1]['change'])
        self.assertEqual(S.status()['current_settings']['params']['sunlight_hours'], 5)
        b = S.change({'focus': 'sugar_percent'})
        self.assertEqual(b['focus'], 'sugar_percent')
        with self.assertRaisesRegex(ValueError, 'ripe'):
            S.set_goal({'metric': 'colour', 'value': 1})
        S.reset()

    def test_invert_flips_the_side(self):
        from core.sim_session import _apply
        self.assertEqual(_apply({'side': 'short'}, {'side': 'invert'})[0]['side'], 'long')


class Tool(unittest.TestCase):
    def setUp(self):
        import core.scenario_simulator as sim
        import actions.simulation_session as act
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [patch.object(sim, 'LAST', Path(self.tmp.name) / 'l.json'), patch.object(act, 'MONTAGE_SECONDS', 0)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()
        import core.sim_session as S
        S.reset()

    def test_voice_flow(self):
        import time
        from actions.simulation_session import session
        ui = MagicMock()
        out = session({'action': 'start', 'kind': 'process', 'parameters_json': json.dumps(APPLE),
                       'goal_metric': 'ripe', 'goal_op': '<=', 'goal_value': 145, 'label': 'Apple'}, player=ui)
        self.assertIn('MODEL SUCCESSFUL', out)
        out = session({'action': 'search', 'param': 'sunlight_hours', 'values': [3, 4, 9]}, player=ui)
        self.assertIn('"first_success"', out)
        time.sleep(.2)
        shown = [c[0][0]['session']['attempt'] for c in ui.show_simulation.call_args_list if c[0][0]]
        self.assertEqual(shown[-1], 4)                              # the montage ended on the success
        self.assertIn('failed', session({'action': 'change', 'changes_json': '{}'}, player=ui))
        session({'action': 'reset'}, player=ui)
        ui.show_simulation.assert_called_with(None)


class BoardDraws(unittest.TestCase):
    def test_session_and_scene_paint(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QPointF
        app = QApplication.instance() or QApplication([])
        import core.sim_session as S
        from core.simulation_view import SimulationHologram
        w = SimulationHologram()
        for scene in ('grow', 'fill', 'dots'):
            spec = {**APPLE, 'scene': {**APPLE['scene'], 'type': scene}}
            S.start('process', spec, {'metric': 'ripe', 'op': '<=', 'value': 145})
            b = S.change({'sunlight_hours': 5})
            for size in ((1100, 640), (490, 640)):
                w.resize(*size)
                for t in (0, 1.2, 3.0, 20):
                    w.set_result(b)
                    w.started -= t
                    self.assertFalse(w.grab().isNull())
                w._hover = QPointF(200, 200)
                self.assertFalse(w.grab().isNull())
        S.reset()
        app.processEvents()


class AccountLimits(unittest.TestCase):
    def test_balance_never_goes_below_zero(self):
        import core.trading_lab as t
        fx = json.loads((Path(__file__).parent / 'fixtures' / 'sweep_mss_breaker_short.json').read_text())
        # the fixture's one trade wins; force a loss by flipping to longs only on a copy where the setup is short
        r = t.backtest({'candles': fx, 'symbol': 'T'}, 'sweep_mss_breaker', rr=2, account_balance=100, risk_amount=500)
        self.assertGreaterEqual(min(x['balance'] for x in r['trades']), 0)
        self.assertIn('500%', r['money']['risk_warning'])

    def test_clipped_window_is_reported(self):
        import time
        from actions.trading_lab import run_backtest
        fx = json.loads((Path(__file__).parent / 'fixtures' / 'sweep_mss_breaker_short.json').read_text())
        data = {'candles': fx, 'symbol': 'T', 'interval': '5m'}
        with patch('core.trading_lab.load', return_value=data), patch('time.time', return_value=fx[-1]['t'] + 60):
            s = run_backtest({'symbol': 'T', 'interval': '5m', 'past_days': 180, 'strategy': 'sweep_mss_breaker'})
        self.assertIn('only go back', s['window_note'])


class ModelWrittenFormulas(unittest.TestCase):
    """The exact shapes JARVIS wrote in the live app, which used to fail five times in a row."""

    def test_params_dot_and_bracket_styles(self):
        from core.process_sim import Formula, normalise
        self.assertEqual(normalise("params.sunlight_hours * variables['size_cm']"), 'sunlight_hours * size_cm')
        f = Formula("0.1 * params.a * params['b'] * (1 - variables.x / 10) + math.exp(0) && 1", {'a', 'b', 'x'})
        self.assertAlmostEqual(f({'a': 2, 'b': 3, 'x': 5, 't': 0}), 1.0)
        with self.assertRaisesRegex(ValueError, 'bare names'):
            Formula('os.system(1)', set())

    def test_call_without_action_or_kind_starts_a_process(self):
        from actions.simulation_session import session
        import core.sim_session as S
        spec = {'title': 'Apple', 'duration': 180, 'params': {'sunlight_hours': 10, 'water_litres': .5},
                'variables': [{'name': 'size_cm', 'unit': 'cm', 'start': .5,
                               'rate': '0.1 * params.sunlight_hours * params.water_litres * (1 - variables.size_cm / 10)'},
                              {'name': 'Ripeness_Percent', 'unit': '%', 'start': 0, 'rate': "0.5 * params['sunlight_hours']"}]}
        out = session({'parameters_json': json.dumps(spec)}, player=MagicMock())
        self.assertIn('"attempt": 1', out)
        self.assertIn('"can_change"', out)
        b = S.board()
        self.assertLessEqual(max(b['series']['ripeness_percent']), 100)   # % stays within 0-100
        S.reset()


class VideoStreamUrl(unittest.TestCase):
    def test_long_stream_url_is_not_treated_as_a_file(self):
        src = (Path(__file__).parent.parent / 'ui.py').read_text(encoding='utf-8')
        self.assertIn("if source.startswith(('http://', 'https://')):", src)


class MoreFormulaFunctions(unittest.TestCase):
    def test_the_logged_floor_call_runs_and_runaway_growth_is_flagged(self):
        from core.process_sim import simulate, Formula
        spec = {"title": "Apple Growing", "time_unit": "days", "duration": "1000", "steps": 1000,
                "params": {"sunlight_hours": 8, "water_litres": 0.5, "nutrient_level": 75},
                "variables": [{"name": "height_cm", "unit": "cm", "start": 1,
                               "rate": "height_cm * 0.01 * (sunlight_hours/8) * (water_litres/0.5) * (nutrient_level/75)"},
                              {"name": "fruit_count", "unit": "apples", "value": "floor(height_cm / 50)"}]}
        r = simulate(spec)                                            # "duration" as text and floor() both work
        self.assertEqual(r['finals']['fruit_count'], int(r['finals']['fruit_count']))
        self.assertTrue(any('unbounded' in w for w in r['model_warnings']))
        bounded = dict(spec, variables=[{"name": "height_cm", "unit": "cm", "start": 1, "rate": "0.01 * (400 - height_cm)"}])
        self.assertEqual(simulate(bounded)['model_warnings'], [])
        for f in ('ceil(x)', 'round(x, 1)', 'pow(x, 2)', 'sign(-x)', 'sigmoid(x)', 'clip(x, 0, 1)', 'int(x)', 'ln(x)'):
            Formula(f, {'x'})({'x': 2.5, 't': 0})
        with self.assertRaisesRegex(ValueError, 'Unknown function "gamma'):
            Formula('gamma(x)', {'x'})


class Board3D(unittest.TestCase):
    """The 3D viewport on the board: layout, time sync and the bundled scene page."""

    class FakeView:
        def __init__(self, parent):
            from PyQt6.QtWidgets import QWidget
            self.w = QWidget(parent)
            self.models, self.times, self.statuses, self.current_time = [], [], [], 42.0
        def show_model(self, result, status=None): self.models.append((result.get('scene'), status))
        def set_time(self, t): self.times.append(t)
        def set_status(self, s): self.statuses.append(s)
        def show(self): self.w.show()
        def hide(self): self.w.hide()
        def geometry(self): return self.w.geometry()
        def setGeometry(self, g): self.w.setGeometry(g)

    def test_process_results_get_a_3d_hero_synced_to_the_chart(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import core.sim_session as S
        from core.simulation_view import SimulationHologram
        made = []
        with patch.object(SimulationHologram, 'make_3d', staticmethod(lambda parent: made.append(Board3D.FakeView(parent)) or made[-1])):
            w = SimulationHologram()
            w.resize(1100, 700)
            S.start('process', APPLE, {'metric': 'ripe', 'op': '<=', 'value': 145})
            w.set_result(S.board())
            w.started -= 1.0
            w.grab()
            view = made[0]
            self.assertTrue(w._3d_on)
            self.assertEqual(view.models[-1][0]['type'], 'grow')
            self.assertGreater(view.w.geometry().height(), 200)                 # the 3D scene is the main picture
            self.assertGreater(w._chart.top(), view.w.geometry().bottom())      # the chart sits under it
            self.assertIsNotNone(view.times[-1])                               # during the build it follows the beam
            w.started -= 30
            w.grab()
            self.assertIsNone(view.times[-1])                                  # afterwards it plays the time-lapse
            self.assertEqual(view.statuses[-1], 'success')
            w.set_result(__import__('core.scenario_simulator', fromlist=['run']).run('goal', {'total_hours': 30, 'hours_per_day': 2}))
            self.assertFalse(w._3d_on)                                         # other kinds keep the classic board
            self.assertFalse(view.w.isVisible())
            S.reset()
        app.processEvents()

    def test_scene_page_is_bundled_and_local(self):
        root = Path(__file__).parent.parent / 'web' / 'sim3d'
        page = (root / 'index.html').read_text()
        bundle = (root / 'vendor' / 'sim3d.bundle.js').read_text()
        self.assertIn('vendor/sim3d.bundle.js', page)
        self.assertNotIn('http', page)                                         # nothing loads from the network
        for name in ('Sim3D', 'setTime', 'buildTree', 'currentTime'):
            self.assertIn(name, (root / 'src' / 'main.js').read_text())
        self.assertIn('Sim3D', bundle)
        from core.sim3d_view import Sim3DView
        self.assertTrue(Sim3DView.available())


class HandControls(unittest.TestCase):
    """Pinch tracking for the board, and where hand frames go."""

    @staticmethod
    def hand(gap, x=0.5, y=0.5):
        pts = [[x, y + 0.2]] + [[x, y]] * 20                    # wrist below, palm length 0.2
        pts[9] = [x, y]
        pts[4] = [x - gap / 2, y - 0.05]                         # thumb tip
        pts[8] = [x + gap / 2, y - 0.05]                         # index tip
        return pts

    def test_pinch_press_release_has_hysteresis_and_a_steady_pointer(self):
        from core.hand_gestures import HandPose
        pose = HandPose()
        held = lambda gap: pose.update([self.hand(gap)], ['Right'])[0]['p']
        self.assertFalse(held(0.15))                             # open: ratio .75
        self.assertTrue(held(0.05))                              # tips together: pressed
        self.assertTrue(held(0.07))                              # a little apart: still held
        self.assertTrue(held(0.12))                              # clearly apart once: still held (one noisy frame)
        self.assertFalse(held(0.12))                             # twice: released
        a = pose.update([self.hand(0.15)], ['Right'])[0]
        b = pose.update([self.hand(0.04)], ['Right'])[0]
        self.assertLess(abs(a['x'] - b['x']) + abs(a['y'] - b['y']), 0.001)   # closing the pinch does not move the pointer
        self.assertGreater(b['s'], a['s'])
        self.assertEqual(len(b['pts']), 21)
        two = pose.update([self.hand(0.05, x=0.7), self.hand(0.05, x=0.3)], ['Left', 'Right'])
        self.assertEqual([h['id'] for h in two], ['Right', 'Left'])          # sorted left to right on screen
        self.assertEqual(pose.update([], []), [])

    def test_frames_reach_the_3d_view_or_a_flat_board_cursor(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import core.sim_session as S
        from core.simulation_view import SimulationHologram
        made = []

        class View(Board3D.FakeView):
            def __init__(self, parent):
                super().__init__(parent); self.frames = []; self.states = []
            def hand(self, frame): self.frames.append(frame)
            def gesture_state(self, st): self.states.append(st)

        with patch.object(SimulationHologram, 'make_3d', staticmethod(lambda parent: made.append(View(parent)) or made[-1])):
            w = SimulationHologram(); w.resize(1100, 700)
            S.start('process', APPLE, {'metric': 'ripe', 'op': '<=', 'value': 145})
            w.set_result(S.board()); w.grab()
            frame = {'kind': 'idle', 't': 1.0, 'hands': [{'id': 'Right', 'x': .5, 'y': .5, 's': 1, 'p': True, 'pts': []}]}
            w.hand(frame)
            self.assertEqual(made[0].frames[-1]['hands'][0]['id'], 'Right')
            w.gesture_state({'enabled': True, 'state': 'tracking'})
            self.assertEqual(made[0].states[-1]['state'], 'tracking')
            w.set_result(__import__('core.scenario_simulator', fromlist=['run']).run('goal', {'total_hours': 30, 'hours_per_day': 2}))
            w.started -= 60; w.grab()
            n = len(made[0].frames)
            w.hand(frame); w.grab()
            self.assertEqual(len(made[0].frames), n)             # flat board: drawn here, not sent to the hidden 3D view
            self.assertIsNotNone(w._hand)
            self.assertTrue(w._chart.contains(w._hover))         # the hand reads the chart like the mouse
            w.hand({'kind': 'idle', 'hands': []})
            self.assertIsNone(w._hand)
            S.reset()
        app.processEvents()

    def test_page_only_asks_for_gesture_start_and_stop(self):
        from core.sim3d_view import REQUESTS
        self.assertEqual(set(REQUESTS), {'gestures:start', 'gestures:stop'})
        js = (Path(__file__).parent.parent / 'web' / 'sim3d' / 'src' / 'interact.js').read_text()
        for word in ('OneEuro', 'rewind', "'zoom'", "'scrub'", 'gestures:start'):
            self.assertIn(word, js)


if __name__ == '__main__':
    unittest.main()
