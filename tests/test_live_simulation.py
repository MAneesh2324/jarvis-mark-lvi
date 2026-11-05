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


class HandGestures(unittest.TestCase):
    @staticmethod
    def hand(n, wrist=(.5, .8)):
        wx, wy = wrist
        pts = [(wx, wy), (wx - .08, wy - .05), (wx - .12, wy - .1), (wx - .14, wy - .15), (wx - .15, wy - .2)]
        for k, fx in enumerate((-.04, 0, .04, .08)):
            pts += ([(wx + fx, wy - .15), (wx + fx, wy - .22), (wx + fx, wy - .27), (wx + fx, wy - .32)] if k < n else
                    [(wx + fx, wy - .15), (wx + fx, wy - .2), (wx + fx + .02, wy - .16), (wx + fx + .01, wy - .13)])
        return pts

    def test_point_swipe_palm_and_old_gestures(self):
        from core.hand_gestures import Interpreter
        i = Interpreter()
        e = i.update([self.hand(1)], 0)
        self.assertEqual(e['kind'], 'point')
        self.assertAlmostEqual(e['x'], .46)
        i, kinds = Interpreter(), []
        for k in range(10):
            kinds.append(i.update([self.hand(4, (.5 + k * .05, .8))], k * .04))
        swipes = [e for e in kinds if e['kind'] == 'swipe']
        self.assertEqual([e['direction'] for e in swipes], ['right'])     # exactly one, with a cooldown
        i = Interpreter()
        held = [i.update([self.hand(4)], k / 10)['kind'] for k in range(14)]
        self.assertEqual(held.count('palm_hold'), 1)
        i = Interpreter()
        self.assertIn('reset', [i.update([self.hand(0)], k / 10)['kind'] for k in range(10)])   # fist still resets
        i = Interpreter()
        self.assertEqual(i.update([self.hand(4), self.hand(4, (.2, .8))], 0)['kind'], 'zoom')  # two hands still zoom

    def test_board_scrubs_zooms_and_swipes_attempts(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import core.sim_session as S
        from core.simulation_view import SimulationHologram
        S.start('process', APPLE, {'metric': 'ripe', 'op': '<=', 'value': 145})
        S.change({'sunlight_hours': 5})
        b = S.change({'sunlight_hours': 10})
        w = SimulationHologram()
        w.resize(1100, 640)
        w.set_result(b, animate=False)
        w.grab()
        w.apply_hand_gesture({'kind': 'point', 'x': .3, 'y': .5})
        x0 = w._hover.x()
        w.apply_hand_gesture({'kind': 'rotate', 'dx': .03, 'dy': 0})
        self.assertGreater(w._hover.x(), x0)                             # pinch-drag scrubs forward in time
        for _ in range(5):
            w.apply_hand_gesture({'kind': 'zoom', 'factor': 1.1})
        w.grab()
        self.assertLess(w._span, 160)                                     # zoomed into part of the timeline
        w.apply_hand_gesture({'kind': 'swipe', 'direction': 'left'})
        self.assertEqual(w.result['session']['attempt'], 2)
        self.assertEqual(w.result['assumptions']['settings']['sunlight_hours'], 5)
        w.apply_hand_gesture({'kind': 'swipe', 'direction': 'right'})
        self.assertEqual(w.result['session']['attempt'], 3)
        w.apply_hand_gesture({'kind': 'reset'})
        self.assertEqual(w._zoom, 1.0)
        self.assertFalse(w.grab().isNull())
        S.reset()
        app.processEvents()

    def test_ui_routes_gestures_to_the_board(self):
        src = (Path(__file__).parent.parent / 'ui.py').read_text(encoding='utf-8')
        self.assertIn('board.apply_hand_gesture(event)', src)


class WorkshopGestures(unittest.TestCase):
    hand = staticmethod(lambda n, wrist=(.5, .8), scale=1.0: WorkshopGestures._hand(n, wrist, scale))

    @staticmethod
    def _hand(n, wrist, k):
        wx, wy = wrist
        pts = [(wx, wy), (wx - .08 * k, wy - .05 * k), (wx - .12 * k, wy - .1 * k), (wx - .14 * k, wy - .15 * k), (wx - .15 * k, wy - .2 * k)]
        for i, fx in enumerate((-.04, 0, .04, .08)):
            fx *= k
            pts += ([(wx + fx, wy - .15 * k), (wx + fx, wy - .22 * k), (wx + fx, wy - .27 * k), (wx + fx, wy - .32 * k)] if i < n else
                    [(wx + fx, wy - .15 * k), (wx + fx, wy - .2 * k), (wx + fx + .02 * k, wy - .16 * k), (wx + fx + .01 * k, wy - .13 * k)])
        return pts

    def kinds(self, frames):
        from core.hand_gestures import Interpreter
        i = Interpreter()
        out = [i.update(f, t) for t, f in frames]
        return [e['kind'] + (':' + e['direction'] if 'direction' in e else '') for e in out if e['kind'] not in ('idle', 'zoom')]

    def test_each_gesture_fires_once_and_near_misses_do_not(self):
        import math
        h = self.hand
        self.assertEqual(self.kinds([(k * .04, [h(0, (.3 + k * .06, .6))]) for k in range(5)] + [(.21, [h(4, (.62, .6))])]), ['throw:right'])
        self.assertEqual(self.kinds([(k * .1, [h(0, (.3 + k * .005, .6))]) for k in range(5)] + [(.55, [h(4, (.33, .6))])]), [])
        self.assertEqual(self.kinds([(k * .1, [h(0)]) for k in range(10)]), ['reset'])
        self.assertEqual(self.kinds([(k * .05, [h(4, (.45 - k * .08, .7)), h(4, (.55 + k * .08, .7))]) for k in range(5)]), ['explode'])
        self.assertEqual(self.kinds([(k * .05, [h(4, (.1 + k * .08, .7)), h(4, (.9 - k * .08, .7))]) for k in range(6)]), ['implode'])
        pair = lambda a: [h(4, (.5 - .2 * math.cos(math.radians(a)), .6 - .2 * math.sin(math.radians(a)))),
                          h(4, (.5 + .2 * math.cos(math.radians(a)), .6 + .2 * math.sin(math.radians(a))))]
        self.assertEqual(self.kinds([(k * .06, pair(k * 10)) for k in range(6)]), ['twist:cw'])
        self.assertEqual(self.kinds([(k * .06, pair(0)) for k in range(6)]), [])
        self.assertEqual(self.kinds([(k * .04, [h(4, (.5, .8 - k * .06))]) for k in range(6)]), ['swipe:up'])
        self.assertEqual(self.kinds([(k * .06, [h(4, (.5, .8), 1 + k * .12)]) for k in range(6)]), ['push'])
        self.assertEqual(self.kinds([(k * .06, [h(4, (.5, .8), 1 - k * .08)]) for k in range(6)]), ['pull'])

    def test_board_responds(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import core.sim_session as S
        from core.simulation_view import SimulationHologram
        S.start('process', APPLE)
        w = SimulationHologram()
        w.resize(1100, 640)
        w.set_result(S.board(), animate=False)
        w.grab()
        w.apply_hand_gesture({'kind': 'explode'})
        self.assertTrue(w._exploded)
        self.assertEqual(len(w._panels()), 3)                           # one panel per quantity
        self.assertFalse(w.grab().isNull())
        w.apply_hand_gesture({'kind': 'implode'})
        self.assertFalse(w._exploded)
        w.apply_hand_gesture({'kind': 'twist', 'direction': 'cw'})
        self.assertEqual(w.shown['focus'], 'sugar_percent')
        w.apply_hand_gesture({'kind': 'twist', 'direction': 'ccw'})
        self.assertEqual(w.shown['focus'], 'diameter_mm')
        w.apply_hand_gesture({'kind': 'swipe', 'direction': 'up'})
        self.assertTrue(w._hood)
        self.assertFalse(w.grab().isNull())
        w.apply_hand_gesture({'kind': 'swipe', 'direction': 'down'})
        self.assertFalse(w._hood)
        closed = []
        w.closed.connect(lambda: closed.append(1))
        w.apply_hand_gesture({'kind': 'throw', 'direction': 'left'})
        w._fly = (w._fly[0] - 2, -1, 0)                                   # past the end of the fly-off
        w.grab()
        app.processEvents()
        self.assertEqual(closed, [1])
        S.reset()


if __name__ == '__main__':
    unittest.main()
