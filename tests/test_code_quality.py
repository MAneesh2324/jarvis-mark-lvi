import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import code_quality as cq


class StaticChecks(unittest.TestCase):
    def test_python_syntax_undefined_names_and_imports(self):
        self.assertTrue(cq.static_check('python', 'import json\nprint(json.dumps({}))\n')['ok'])
        r = cq.static_check('python', 'def f(:\n  pass\n')
        self.assertIn('SyntaxError', r['errors'][0])
        r = cq.static_check('python', 'def f():\n    return totl\n')
        self.assertTrue(any('totl' in e for e in r['errors']))
        r = cq.static_check('python', 'import surely_not_a_real_module_xyz\n')
        self.assertEqual(r['missing_modules'], ['surely_not_a_real_module_xyz'])
        r = cq.static_check('python', 'import utils.helpers\n', known_modules={'utils.helpers'})
        self.assertEqual(r['missing_modules'], [])

    def test_truncated_file_is_named(self):
        r = cq.static_check('python', 'def main():\n    data = [1, 2,\n')
        self.assertIn('cut off', r['errors'][0])

    def test_placeholders_are_errors(self):
        r = cq.static_check('python', 'def f():\n    # TODO: implement\n    return 1\n')
        self.assertTrue(any('placeholder' in e for e in r['errors']))

    def test_unused_import_is_only_a_warning(self):
        r = cq.static_check('python', 'import os\nprint(1)\n')
        self.assertTrue(r['ok'])
        self.assertTrue(r['warnings'])

    def test_javascript_json_bash_html(self):
        self.assertTrue(cq.static_check('javascript', 'const a = 1;\nconsole.log(a);\n')['ok'])
        self.assertFalse(cq.static_check('javascript', 'const a = ;\n')['ok'])
        self.assertFalse(cq.static_check('json', '{"a": 1,}')['ok'])
        self.assertFalse(cq.static_check('bash', 'if true; then echo hi\n')['ok'])
        self.assertFalse(cq.static_check('html', '<div><span>x</div>')['ok'])

    def test_cpp_through_clang(self):
        good = '#include <cstdio>\nint main(){ std::printf("hi"); return 0; }\n'
        self.assertTrue(cq.static_check('cpp', good)['ok'])
        self.assertFalse(cq.static_check('cpp', 'int main(){ undefined_call(); }\n')['ok'])


class PineLinter(unittest.TestCase):
    GOOD = '//@version=5\nindicator("x", overlay=true)\nlen = input.int(14)\nplot(ta.sma(close, len))\n'

    def test_valid_script_passes(self):
        self.assertTrue(cq.static_check('pine', self.GOOD)['ok'])

    def test_common_mistakes_are_caught(self):
        cases = {
            'v4 function': self.GOOD.replace('ta.sma', 'sma'),
            'missing version': self.GOOD.replace('//@version=5\n', ''),
            'plot in local scope': self.GOOD + 'if close > open\n    plot(close)\n',
            'na comparison': self.GOOD + 'x = close == na ? 1 : 0\n',
            'transp': self.GOOD + 'bgcolor(color.red, transp=80)\n',
            'strategy call in indicator': self.GOOD + 'if close > open\n    strategy.entry("L", strategy.long)\n',
            'two declarations': self.GOOD + 'strategy("y")\n',
            'unbalanced': self.GOOD + 'plot(ta.ema(close, 9)\n',
        }
        for name, code in cases.items():
            with self.subTest(name):
                self.assertFalse(cq.static_check('pine', code)['ok'], name)

    def test_comments_and_strings_do_not_trigger(self):
        code = self.GOOD + '// sma(close, 9) is v4 style\nlabel.new(bar_index, high, "rsi(14) high")\n'
        self.assertTrue(cq.static_check('pine', code)['ok'])

    def test_wrong_argument_names_and_objects_as_bools(self):
        bad = self.GOOD + 'plotshape(close > open, look=shape.triangleup)\nvar line l1 = na\nif barstate.islast and l1\n    l1 := na\n'
        errors = cq.static_check('pine', bad)['errors']
        self.assertTrue(any('no parameter named look' in e for e in errors))
        self.assertTrue(any('not a bool' in e for e in errors))
        ok = self.GOOD + 'plotshape(close > open, style=shape.triangleup, location=location.belowbar)\nvar line l1 = na\n' \
                         'if not na(l1)\n    line.set_x2(l1, bar_index)\n'
        self.assertTrue(cq.static_check('pine', ok)['ok'], cq.static_check('pine', ok)['errors'])

    def test_reviewer_runs_for_uncompilable_languages_and_is_capped(self):
        good = '//@version=5\nindicator("x")\nplot(close)\n'
        with patch.object(cq, 'ask_model', return_value='```\n' + good + '```'), \
                patch.object(cq, 'review', side_effect=[['line 3: invented problem'], ['still'], ['again']]) as rv:
            code, report = cq.generate('plot close', 'pine', max_rounds=5, log=lambda m: None)
        self.assertEqual(rv.call_count, 2)
        self.assertTrue(report['ok'])

    def test_mql_needs_an_entry_point(self):
        self.assertFalse(cq.static_check('mql5', 'int OnInit(){ return 0; }')['ok'])
        self.assertTrue(cq.static_check('mql5', 'int OnInit(){ return 0; }\nvoid OnTick(){ }')['ok'])


class Running(unittest.TestCase):
    def test_exit_code_decides_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / 'ok.py'; ok.write_text('print("0 errors found")\n')
            bad = Path(tmp) / 'bad.py'; bad.write_text('raise SystemExit(3)\n')
            slow = Path(tmp) / 'slow.py'; slow.write_text('import time\nprint("up")\ntime.sleep(5)\n')
            self.assertTrue(cq.run_file(ok)['ok'])          # the word "errors" in output is not a failure
            self.assertFalse(cq.run_file(bad)['ok'])
            r = cq.run_file(slow, timeout=1)
            self.assertTrue(r['ok']); self.assertTrue(r['timed_out'])


class RepairLoop(unittest.TestCase):
    def test_generate_repairs_until_checks_and_run_pass(self):
        replies = iter(['```python\nprint(undefined_name)\n```',
                        '```python\nimport sys\nsys.exit(1)\n```',
                        '```python\nprint("works")\n```'])
        runs = []

        def runner(code):
            runs.append(code)
            return {'ok': 'exit(1)' not in code, 'output': 'exit 1'}

        with patch.object(cq, 'ask_model', side_effect=lambda prompt, **k: next(replies)):
            code, report = cq.generate('print works', 'python', runner=runner, log=lambda m: None)
        self.assertEqual(code, 'print("works")\n')
        self.assertTrue(report['ok'])
        self.assertEqual(report['rounds'], 3)
        self.assertEqual(len(runs), 2)  # the static failure never reached the runner

    def test_gives_up_honestly(self):
        with patch.object(cq, 'ask_model', return_value='```python\nprint(nope)\n```'):
            code, report = cq.generate('x', 'python', max_rounds=2, log=lambda m: None)
        self.assertFalse(report['ok'])
        self.assertTrue(report['remaining_errors'])

    def test_long_output_is_continued(self):
        class Resp:
            def __init__(self, text, reason):
                self.text = text
                self.candidates = [type('C', (), {'finish_reason': reason})()]
        answers = iter([Resp('```python\nprint(1)\n', 'FinishReason.MAX_TOKENS'), Resp('print(2)\n```', 'FinishReason.STOP')])
        with patch('core.gemini.call', side_effect=lambda *a, **k: next(answers)):
            text = cq.ask_model('write it')
        self.assertEqual(cq.extract_code(text), 'print(1)\nprint(2)\n')

    def test_extract_picks_the_code_block(self):
        self.assertEqual(cq.extract_code('Here you go:\n```python\nx = 1\n```\nEnjoy!'), 'x = 1\n')


class ForexAdditions(unittest.TestCase):
    def test_session_and_asian_range(self):
        from core import trading_lab as lab
        day = 1_700_006_400 - 1_700_006_400 % 86400
        candles = [{'t': day + h * 3600, 'o': 1.1, 'h': 1.101 + (0.002 if h == 9 else 0), 'l': 1.099, 'c': 1.1, 'v': 0}
                   for h in range(14)]
        s = lab.forex_session(candles)
        self.assertIn('London', s['open_sessions'])
        self.assertIn('New York', s['open_sessions'])
        self.assertTrue(s['asian_range']['high_swept'])
        self.assertFalse(s['asian_range']['low_swept'])

    def test_calendar_filters_and_news_risk(self):
        from datetime import datetime, timedelta, timezone
        from core import news_engine as ne
        now = datetime.now(timezone.utc)
        rows = [{'time_utc': now + timedelta(hours=5), 'currency': 'USD', 'event': 'Non-Farm Employment Change',
                 'impact': 'High', 'forecast': '150K', 'previous': '120K'},
                {'time_utc': now + timedelta(hours=6), 'currency': 'JPY', 'event': 'Tankan', 'impact': 'Medium',
                 'forecast': None, 'previous': None}]
        with patch.object(ne, '_calendar_rows', return_value=(rows, {'fetched_at': 'x'})):
            cal = ne.calendar(['USD'], 'High', 24)
            self.assertEqual([e['event'] for e in cal['events']], ['Non-Farm Employment Change'])
            self.assertEqual(len(ne.calendar(None, 'Medium', 24)['events']), 2)
            risk = ne.news_risk('EURUSD=X', 24)
        self.assertEqual(risk['events'][0]['currency'], 'USD')
        self.assertIn('high-impact', risk['warning'])

    def test_default_watchlist_is_forex(self):
        from core import setup_tracker as st, trading_lab as lab
        self.assertTrue(all(len(s) == 6 and s in lab.FX_PAIRS for s, _ in st.DEFAULT_WATCH))


if __name__ == '__main__':
    unittest.main()
