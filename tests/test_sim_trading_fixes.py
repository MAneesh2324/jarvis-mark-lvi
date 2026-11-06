"""Fixes for the simulation_session / trading_lab / scenario_simulator failures seen in native-startup.log.

No network: market data loading is mocked everywhere.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURES = Path(__file__).parent / 'fixtures'


def _candles():
    return json.loads((FIXTURES / 'sweep_mss_breaker_short.json').read_text())


class _TempScenarioStore(unittest.TestCase):
    """Keep remember()/save() away from the real memory folder, and start every test with no memory."""

    def setUp(self):
        import actions.trading_lab as act
        import core.scenario_simulator as sim
        import core.sim_session as S
        self.tmp = tempfile.TemporaryDirectory()
        for name in ('LAST', 'REPORTS'):
            p = patch.object(sim, name, Path(self.tmp.name) / ('l.json' if name == 'LAST' else ''))
            p.start()
            self.addCleanup(p.stop)
        act._LAST.clear()
        S.reset()
        self.addCleanup(S.reset)
        self.addCleanup(act._LAST.clear)
        self.addCleanup(self.tmp.cleanup)


# ── 1. formulas the model writes ────────────────────────────────────────────
class ForgivingFormulas(unittest.TestCase):
    LOGGED = [   # every formula the live app refused, as it arrived (after JSON decoding)
        ("0.1 * params['sunlight_hours'] * params['water_litres'] * (1 - variables['size_cm'] / 10)",
         {'sunlight_hours', 'water_litres', 'size_cm'}),
        ('0.1 * params.sunlight_hours * params.water_litres * (1 - variables.size_cm / 10)',
         {'sunlight_hours', 'water_litres', 'size_cm'}),
        ("0.5 * params['sunlight_hours']", {'sunlight_hours'}),
        ('min(params.max_apple_size_cm, params.initial_apple_size_cm + params.growth_rate_factor * t)',
         {'max_apple_size_cm', 'initial_apple_size_cm', 'growth_rate_factor'}),
        ('min(0.2, 0.05 * params["sunlight_hours"] * (variables["glucose_percent"] / 100))',
         {'sunlight_hours', 'glucose_percent'}),
        ('height_cm * 0.01 * (sunlight_hours/8) * (water_litres/0.5) * (nutrient_level/75)',
         {'height_cm', 'sunlight_hours', 'water_litres', 'nutrient_level'}),
        ('floor(height_cm / 50)', {'height_cm'}),
    ]

    def test_every_logged_formula_now_evaluates(self):
        from core.process_sim import Formula
        for text, names in self.LOGGED:
            env = {n: 2.0 for n in names} | {'t': 1.0}
            self.assertIsInstance(Formula(text, names)(env), float, text)

    def test_prefixes_and_library_spellings(self):
        from core.process_sim import Formula
        cases = {
            'np.minimum(x, 3)': 2, 'math.exp(0)': 1, 'numpy.clip(x, 0, 1)': 1, 'p.k + self.k': 2,
            "params.get('k', 5)": 1, 'np.maximum(x, k)': 2, 'math.pow(x, 3)': 8, 'x ** 2': 4, 'abs(-x)': 2,
            'round(x / 3, 2)': 0.67, 'math.floor(2.7)': 2, 'np.ceil(2.1)': 3, 'math.sqrt(x * 8)': 4,
            'np.log(1)': 0, 'math.log10(100)': 2, 'np.sin(0) + np.cos(0)': 1, 'clamp(x, 0, 1)': 1,
            'np.where(x > 1, 10, 20)': 10, 'x // 3': 0, 'math.pi > 3': 1, 'True + x': 3, 'X + K': 3,
        }
        for text, want in cases.items():
            self.assertAlmostEqual(Formula(text, {'x', 'k'})({'x': 2.0, 'k': 1.0, 't': 0}), want, 2, msg=text)

    def test_unsafe_parts_are_named_in_one_line(self):
        from core.process_sim import Formula
        cases = {'x.real': '"x.real"', 'foo.bar(1)': '"foo.bar()"', 'x[0]': '"x[0]"',
                 '[i for i in (1, 2)]': 'comprehension', 'lambda: 1': 'lambda', 'round(x, ndigits=2)': 'keyword',
                 '__import__("os")': 'Unknown function "__import__()"', 'params.__class__': 'Unknown name "__class__"',
                 'x.__class__.__bases__': '"x.__class__.__bases__"', 'sunlight + 1': 'did you mean sunlight_hours',
                 'min(*x)': 'keyword or *'}
        for text, part in cases.items():
            with self.assertRaises(ValueError, msg=text) as cm:
                Formula(text, {'x', 'sunlight_hours'})
            self.assertIn(part, str(cm.exception), text)
            self.assertNotIn('\n', str(cm.exception))

    def test_logged_apple_specs_run_end_to_end(self):
        from core.process_sim import simulate
        spec = {"title": "Apple Growing on Tree", "time_unit": "days", "duration": 180, "steps": 180,
                "params": {"sunlight_hours": 10, "water_litres": 0.5},
                "variables": [{"name": "size_cm", "unit": "cm", "start": 0.5,
                               "rate": "0.1 * params['sunlight_hours'] * params['water_litres'] * (1 - variables['size_cm'] / 10)"},
                              {"name": "ripeness_percent", "unit": "%", "start": 0, "rate": "0.5 * params['sunlight_hours']"}],
                "focus": "size_cm"}
        r = simulate(spec)
        self.assertGreater(r['finals']['size_cm'], 5)
        self.assertLessEqual(r['finals']['ripeness_percent'], 100)


# ── 2. duration as text ─────────────────────────────────────────────────────
class DurationText(unittest.TestCase):
    def test_units_are_converted_to_the_spec_unit(self):
        from core.process_sim import parse_duration
        self.assertEqual(parse_duration('10 years', 'days')[0], 3652.5)
        self.assertAlmostEqual(parse_duration('6 months', 'days')[0], 182.625)
        self.assertEqual(parse_duration('30 days', 'days')[0], 30)
        self.assertEqual(parse_duration('2 hours', 'minutes')[0], 120)
        self.assertEqual(parse_duration('40', 'days')[:2], (40, 'days'))
        self.assertEqual(parse_duration('1.5', 'years')[:2], (1.5, 'years'))
        self.assertEqual(parse_duration('approx. 150 days', 'days')[0], 150)
        self.assertEqual(parse_duration('10 years', None)[:2], (10, 'years'))     # no time_unit: take the duration's
        self.assertEqual(parse_duration('1,000 days', 'days')[0], 1000)
        with self.assertRaisesRegex(ValueError, 'duration must be a number'):
            parse_duration('until ripe', 'days')

    def test_the_logged_apple_spec_runs_and_says_how_it_read_the_duration(self):
        from core.process_sim import simulate
        spec = {"title": "Apple Growing Simulation", "time_unit": "days", "duration": "approx. 150 days",
                "params": {"initial_apple_size_cm": 0.5, "max_apple_size_cm": 7, "growth_rate_factor": 0.05},
                "variables": [{"name": "day_count", "unit": "days", "value": "t"},
                              {"name": "apple_size_cm", "unit": "cm",
                               "value": "min(params.max_apple_size_cm, params.initial_apple_size_cm + params.growth_rate_factor * t)"}],
                "focus": "apple_size_cm"}
        r = simulate(spec)
        self.assertEqual(r['assumptions']['duration'], 150)
        self.assertAlmostEqual(r['finals']['apple_size_cm'], min(7, 0.5 + 0.05 * 140))   # capped at max size
        self.assertTrue(any('150' in n for n in r['notes']))
        years = simulate({**spec, 'duration': '1 year'})
        self.assertEqual(years['assumptions']['duration'], 365.25)


# ── 3. interval switching instead of failing ───────────────────────────────
class IntervalSwitch(_TempScenarioStore):
    def _run(self, params):
        from actions.trading_lab import run_backtest
        fx = _candles()
        data = {'candles': fx, 'symbol': 'GC=F', 'requested': 'XAUUSD', 'interval': params.get('interval', '1h')}
        with patch('core.trading_lab.load', return_value=data) as load, patch('time.time', return_value=fx[-1]['t'] + 60):
            stats = run_backtest(params)
        return stats, load.call_args[0][0]

    def test_logged_1m_requests_switch_to_the_finest_interval_that_covers_the_window(self):
        for days, want in ((7, '5m'), (28, '15m'), (180, '1h')):
            stats, sent = self._run({'symbol': 'XAUUSD', 'interval': '1m', 'past_days': days, 'strategy': 'sweep_mss_breaker'})
            self.assertEqual((stats['interval_requested'], stats['interval_used']), ('1m', want), days)
            self.assertEqual(sent['interval'], want)
            self.assertIn('finest interval', stats['interval_note'])

    def test_short_1m_windows_stay_on_1m_with_a_range_yahoo_accepts(self):
        stats, sent = self._run({'symbol': 'XAUUSD', 'interval': '1m', 'past_days': 3, 'strategy': 'sweep_mss_breaker'})
        self.assertNotIn('interval_used', stats)
        self.assertEqual((sent['interval'], sent['range']), ('1m', '5d'))         # 1mo used to get HTTP 422

    def test_tool_reports_the_switch_as_facts(self):
        import actions.trading_lab as act
        fx = _candles()
        data = {'candles': fx, 'symbol': 'GC=F', 'requested': 'XAUUSD', 'interval': '5m'}
        with patch('core.trading_lab.load', return_value=data), patch('time.time', return_value=fx[-1]['t'] + 60):
            out = act.trading_lab({'action': 'backtest', 'symbol': 'XAUUSD', 'interval': '1m', 'past_days': 7,
                                   'strategy': 'sweep_mss_breaker', 'rr': 2})
        self.assertIn('"interval_requested": "1m"', out)
        self.assertIn('"interval_used": "5m"', out)

    def test_live_session_change_to_1m_runs_and_reports(self):
        import core.sim_session as S
        from actions.simulation_session import session
        fx = _candles()
        data = {'candles': fx, 'symbol': 'GC=F', 'requested': 'XAUUSD', 'interval': '5m'}
        with patch('core.trading_lab.load', return_value=data), patch('time.time', return_value=fx[-1]['t'] + 60):
            S.start('backtest', {'symbol': 'XAUUSD', 'past_days': 7, 'strategy': 'sweep_mss_breaker', 'rr': 2})
            out = session({'action': 'change', 'changes_json': '{"interval": "1m", "past_days": 6}'})
        self.assertTrue(out.startswith('<<<UNTRUSTED'), out)
        self.assertIn('"interval_used": "5m"', out)

    def test_fetch_shortens_ranges_the_source_refuses(self):
        import core.trading_lab as lab
        captured = {}

        def fake_fetch(url, ttl=0, force=False):
            captured['url'] = url
            return {'text': _yahoo_json(_candles()), 'url': url}
        with patch('core.intelligence_cache.fetch', side_effect=fake_fetch):
            data = lab.fetch_candles('XAUUSD', '1m', '1mo')
        self.assertIn('range=5d', captured['url'])
        self.assertIn('shortened', data['range_note'])


def _yahoo_json(candles):
    return json.dumps({'chart': {'result': [{'meta': {'currency': 'USD'}, 'timestamp': [c['t'] for c in candles],
                                             'indicators': {'quote': [{k: [c[k[0]] for c in candles]
                                                                       for k in ('open', 'high', 'low', 'close')}
                                                                      | {'volume': [0] * len(candles)}]}}],
                                 'error': None}})


# ── 4. symbol aliases, fallback and a precise error ─────────────────────────
class SymbolsAndSource(unittest.TestCase):
    def test_futures_aliases(self):
        from core.trading_lab import normalize_symbol as n
        for raw, want in {'XAUUSD': 'GC=F', 'GOLD': 'GC=F', 'MGC': 'GC=F', 'GC': 'GC=F', 'XAUUSD=F': 'GC=F',
                          'gold futures': 'GC=F', 'COMEX:GC1!': 'GC=F', 'NQ': 'NQ=F', 'MNQ': 'NQ=F', 'MNQ1!': 'NQ=F',
                          'Nasdaq futures': 'NQ=F', 'nasdaq 100 futures': 'NQ=F', 'ES': 'ES=F', 'MES': 'ES=F',
                          'S&P 500 futures': 'ES=F', 'NQ=F': 'NQ=F', 'OANDA:XAUUSD': 'GC=F', 'silver futures': 'SI=F',
                          # unchanged meanings
                          'NAS100': '^NDX', 'EURUSD': 'EURUSD=X', 'BTC': 'BTC-USD', 'AAPL': 'AAPL', 'SIL': 'SIL'}.items():
            self.assertEqual(n(raw), want, raw)

    def test_fallback_host_is_tried_when_the_cached_feed_fails(self):
        import core.trading_lab as lab
        ok = MagicMock(status_code=200, text=_yahoo_json(_candles()))
        with patch('core.intelligence_cache.fetch', side_effect=RuntimeError('Public data source is unavailable')), \
                patch('requests.get', return_value=ok) as get:
            data = lab.fetch_candles('MNQ1!', '5m')
        self.assertIn('query2.finance.yahoo.com/v8/finance/chart/NQ=F', get.call_args[0][0])
        self.assertEqual(data['symbol'], 'NQ=F')
        self.assertGreater(len(data['candles']), 60)

    def test_error_names_the_symbol_interval_and_source(self):
        import core.trading_lab as lab
        bad = MagicMock(status_code=429)
        bad.json.return_value = {'chart': {'error': {'description': 'Too Many Requests'}}}
        with patch('core.intelligence_cache.fetch', side_effect=RuntimeError('Public data source is unavailable and no cached copy exists.')), \
                patch('requests.get', return_value=bad):
            with self.assertRaises(ValueError) as cm:
                lab.fetch_candles('XAUUSD', '5m', '1mo')
        msg = str(cm.exception)
        for part in ('XAUUSD', 'GC=F', '5m', 'Yahoo Finance', 'HTTP 429', 'Too Many Requests'):
            self.assertIn(part, msg)


# ── 5. "check it for one week": reuse the last symbol ──────────────────────
class ReuseLastSymbol(_TempScenarioStore):
    def test_backtest_without_symbol_reuses_the_last_one(self):
        import actions.trading_lab as act
        fx = _candles()
        data = {'candles': fx, 'symbol': 'GC=F', 'requested': 'XAUUSD', 'interval': '15m'}
        with patch('core.trading_lab.load', return_value=data) as load, patch('time.time', return_value=fx[-1]['t'] + 60):
            act.trading_lab({'action': 'backtest', 'symbol': 'XAUUSD', 'interval': '15m', 'past_days': 1,
                             'strategy': 'sweep_mss_breaker', 'rr': 3, 'account_balance': 100, 'risk_percent': 1})
            out = act.trading_lab({'action': 'backtest', 'past_hours': 168})
        sent = load.call_args[0][0]
        self.assertEqual((sent['symbol'], sent['strategy'], sent['rr'], sent['interval']),
                         ('XAUUSD', 'sweep_mss_breaker', 3, '15m'))
        self.assertIn('"symbol_reused": "XAUUSD"', out)

    def test_analysis_symbol_is_remembered(self):
        import actions.trading_lab as act
        act.remember({'symbol': 'XAUUSD'})
        p, facts = act.reuse_last({'past_hours': 168, 'strategy': 'breaker_retest'}, backtest=True)
        self.assertEqual((p['symbol'], p['strategy'], facts['symbol_reused']), ('XAUUSD', 'breaker_retest', 'XAUUSD'))

    def test_nothing_to_reuse_asks_for_the_symbol(self):
        import actions.trading_lab as act
        from actions.simulation_session import session
        out = act.trading_lab({'action': 'backtest', 'past_hours': 168})
        self.assertTrue(out.startswith('status=ask'), out)
        self.assertIn('missing=symbol', out)
        out = session({'action': 'start', 'kind': 'backtest', 'parameters_json': '{"strategy": "sweep_mss_breaker"}'})
        self.assertTrue(out.startswith('status=ask'), out)

    def test_live_session_start_reuses_and_stores_the_symbol(self):
        import actions.trading_lab as act
        import core.sim_session as S
        act.remember({'symbol': 'XAUUSD', 'strategy': 'sweep_mss_breaker'}, backtest=True)
        fx = _candles()
        data = {'candles': fx, 'symbol': 'GC=F', 'requested': 'XAUUSD', 'interval': '1h'}
        with patch('core.trading_lab.load', return_value=data), patch('time.time', return_value=fx[-1]['t'] + 60):
            board = S.start('backtest', {'account_balance': 100, 'risk_percent': 1, 'rr': 2, 'past_days': 7},
                            {'metric': 'return_percent', 'op': '>=', 'value': 2})
        self.assertEqual(board['facts']['symbol_reused'], 'XAUUSD')
        self.assertEqual(S.status()['current_settings']['symbol'], 'XAUUSD')


# ── 6. action aliases ───────────────────────────────────────────────────────
class ActionAliases(unittest.TestCase):
    def test_analyze_and_friends(self):
        from actions.trading_lab import resolve_action
        for said, want in {'analyze': 'analyse', 'Analyze': 'analyse', 'analysis': 'analyse', 'backtesting': 'backtest',
                           'test': 'backtest', 'screener': 'scan', 'news': 'calendar', 'stats': 'learning',
                           'pine': 'write_code', 'backtets': 'backtest', 'scan': 'scan'}.items():
            self.assertEqual(resolve_action(said), want, said)
        self.assertIsNone(resolve_action('order'))

    def test_logged_analyze_call_runs(self):
        import actions.trading_lab as act
        fx = _candles()
        data = {'candles': fx, 'symbol': '^NDX', 'requested': 'NAS100', 'interval': '1h'}
        with patch('core.trading_lab.load', return_value=data), patch('core.setup_tracker.watch'), \
                patch('core.setup_tracker.record'):
            out = act.trading_lab({'action': 'analyze', 'interval': '1h', 'symbol': 'NAS100'})
        self.assertTrue(out.startswith('<<<UNTRUSTED'), out)
        self.assertIn('"action_used": "analyse"', out)
        self.assertIn('Use one of', act.trading_lab({'action': 'place_order'}))


# ── 7. scenario_simulator: defaults, other spellings, or a question ─────────
class ScenarioInputs(_TempScenarioStore):
    def _sim(self, params):
        from actions.scenario_simulator import simulate
        return simulate(params, player=None)

    def test_logged_move_percent_is_accepted(self):
        out = self._sim({'kind': 'trade_stress', 'show': True,
                         'parameters_json': '{"equity":1000, "units":1000, "pair_start":28150, "move_percent":1.0, '
                                            '"quote_to_account":1.0, "direction":"short", "notes":"NAS100 Buy Stop"}',
                         'alternative_json': '{"equity":1000, "units":1000, "pair_start":28150, "pair_move_percent":2.0, '
                                             '"quote_to_account":1.0, "direction":"long", "notes":"NAS100 Buy Target"}'})
        self.assertTrue(out.startswith('<<<UNTRUSTED'), out)
        self.assertIn('"move_percent": "pair_move_percent"', out)

    def test_logged_stray_rr_and_default_conversion(self):
        out = self._sim({'kind': 'trade_stress', 'parameters_json':
                         '{"equity": 10000, "pair_start": 1.10, "pair_move_percent": 1, "units": 20000, "rr": 2}'})
        self.assertTrue(out.startswith('<<<UNTRUSTED'), out)
        self.assertIn('"defaults_used"', out)
        self.assertIn('quote_to_account', out)

    def test_missing_numbers_are_asked_for(self):
        out = self._sim({'kind': 'trade_stress', 'parameters_json': '{"equity": 10000, "direction": "buy"}'})
        self.assertTrue(out.startswith('status=ask'), out)
        self.assertIn('missing=units,pair_start,pair_move_percent', out)
        from actions.simulation_session import session
        out = session({'action': 'start', 'kind': 'goal', 'parameters_json': '{"hours_per_day": 2}'})
        self.assertTrue(out.startswith('status=ask'), out)
        self.assertIn('total_hours', out)
        import core.sim_session as S
        self.assertFalse(S.active())                  # a start that never ran leaves no half session


# ── 8. "That changes nothing" and close names ───────────────────────────────
class SessionChanges(_TempScenarioStore):
    def test_close_names_are_matched_and_reported(self):
        import core.sim_session as S
        S.start('process', json.loads((FIXTURES / 'apple_process.json').read_text()))
        board = S.change({'sunlight': 4})
        self.assertEqual(board['facts']['matched_settings'], {'sunlight': 'sunlight_hours'})
        self.assertEqual(S.status()['current_settings']['params']['sunlight_hours'], 4)
        with self.assertRaisesRegex(ValueError, 'not a setting'):
            S.change({'moon_phase': 3})
        S.reset()
        S.start('goal', {'total_hours': 300, 'hours_per_day': 2})
        board = S.change({'hours_a_day': 3})
        self.assertEqual(board['facts']['matched_settings'], {'hours_a_day': 'hours_per_day'})

    def test_repeating_the_same_change_says_what_is_already_set(self):
        import core.sim_session as S
        S.start('goal', {'total_hours': 300, 'hours_per_day': 2})
        S.change({'hours_per_day': 3})
        with self.assertRaisesRegex(ValueError, 'changes nothing: hours_per_day is already 3'):
            S.change({'hours_per_day': 3})


if __name__ == '__main__':
    unittest.main()
