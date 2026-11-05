import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import trading_lab as lab


def path_candles(closes, start=1_700_000_000, step=3600, wick=0.2):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append({'t': start + i * step, 'o': o, 'h': max(o, c) + wick, 'l': min(o, c) - wick, 'c': c, 'v': 0})
        prev = c
    return out


def leg(a, b, n):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def breaker_story():
    """Range, swing high, pullback, bullish break, failure through the order block, retest, drop."""
    closes = [100 + (0.3 if i % 2 else -0.3) for i in range(30)]
    closes += leg(100, 105, 8) + leg(105, 102, 5) + leg(102, 108, 6)
    closes += leg(108, 98, 10) + leg(98, 102.5, 5) + leg(102.5, 94, 10) + [94 + (0.2 if i % 2 else -0.2) for i in range(20)]
    return path_candles(closes)


class Detectors(unittest.TestCase):
    def test_structure_and_breaker_found(self):
        d = lab.detect(breaker_story())
        self.assertTrue(any(e['type'] == 'BOS' and e['direction'] == 'bullish' for e in d['events']))
        bearish = [b for b in d['breakers'] if b['direction'] == 'bearish']
        self.assertTrue(bearish, 'a failed bullish order block should become a bearish breaker')
        self.assertIsNotNone(bearish[-1]['first_retest'])

    def test_fvg_detected_and_fill_tracked(self):
        c = path_candles([100] * 20)
        c += [{'t': c[-1]['t'] + 3600 * k, 'o': o, 'h': h, 'l': l, 'c': cl, 'v': 0}
              for k, (o, h, l, cl) in enumerate([(100, 100.5, 99.8, 100.4), (100.4, 103, 100.3, 102.8),
                                                 (102.8, 103.6, 101.5, 103.4)], 1)]
        gaps = [g for g in lab.fvgs(lab.Series(c)) if g['direction'] == 'bullish']
        self.assertEqual((gaps[-1]['low'], gaps[-1]['high']), (100.5, 101.5))
        self.assertEqual(gaps[-1]['state'], 'unfilled')

    def test_analyse_report_is_compact_and_rounded(self):
        report = lab.analyse({'symbol': 'TEST', 'interval': '1h', 'candles': breaker_story()})
        self.assertIn('setups_ranked', report)
        self.assertLessEqual(len(report['breaker_blocks']), 6)
        pos = (report['summary']['dealing_range'] or {}).get('position_percent', 50)
        self.assertTrue(0 <= pos <= 100)

    def test_key_levels_do_not_chain_into_one_band(self):
        s = lab.Series(path_candles([100 + i * 0.05 for i in range(200)]))
        sw = [{'i': i, 'kind': 'high', 'price': 100 + i * 0.01, 'confirmed': i} for i in range(0, 200, 2)]
        for z in lab.key_levels(s, sw):
            self.assertLessEqual(z['high'] - z['low'], 0.31 * s.a(s.n - 1) + 1e-9)


class Backtests(unittest.TestCase):
    def test_stop_counted_when_stop_and_target_share_a_candle(self):
        c = path_candles([100] * 30, wick=0.1)
        c.append({'t': c[-1]['t'] + 3600, 'o': 100, 'h': 120, 'l': 80, 'c': 100, 'v': 0})
        with patch.object(lab, '_signals', return_value=[{'i': 30, 'direction': 'long', 'entry': 100, 'stop': 99}]):
            r = lab.backtest({'candles': c}, 'ema_cross')
        self.assertEqual(r['total_r'], -1.0)

    def test_limit_fill_candle_cannot_score_its_target(self):
        c = path_candles([100] * 30, wick=0.1)
        c.append({'t': c[-1]['t'] + 3600, 'o': 99, 'h': 100.5, 'l': 90, 'c': 99, 'v': 0})
        sig = [{'i': 30, 'direction': 'short', 'entry': 100, 'stop': 101, 'limit': True}]
        with patch.object(lab, '_signals', return_value=sig):
            r = lab.backtest({'candles': c}, 'breaker_retest')
        self.assertEqual(r['closed_trades'], 0)
        self.assertIsNotNone(r['open_trade'])

    def test_every_strategy_runs(self):
        data = {'candles': breaker_story() * 1}
        for name in lab.STRATEGIES:
            r = lab.backtest(data, name)
            self.assertIn('total_r', r)
        with self.assertRaises(ValueError):
            lab.backtest(data, 'martingale')


class DataLoading(unittest.TestCase):
    def test_symbol_normalisation(self):
        self.assertEqual(lab.normalize_symbol('eur/usd'), 'EURUSD=X')
        self.assertEqual(lab.normalize_symbol('XAUUSD'), 'GC=F')
        self.assertEqual(lab.normalize_symbol('BTCUSDT'), 'BTC-USD')
        self.assertEqual(lab.normalize_symbol('nas100'), '^NDX')
        self.assertEqual(lab.normalize_symbol('AAPL'), 'AAPL')
        with self.assertRaises(ValueError):
            lab.normalize_symbol('bad;symbol')

    def test_tradingview_csv_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'OANDA_EURUSD, 60.csv'
            rows = ['time,open,high,low,close,Volume'] + [f'{1700000000 + i * 3600},{1.1 + i * 1e-4},{1.1005 + i * 1e-4},'
                                                          f'{1.0995 + i * 1e-4},{1.1002 + i * 1e-4},10' for i in range(80)]
            p.write_text('\n'.join(rows))
            data = lab.load({'csv_path': str(p)})
        self.assertEqual(len(data['candles']), 80)
        self.assertEqual(data['interval'], '1h')

    def test_yahoo_parser_skips_empty_rows(self):
        text = ('{"chart":{"result":[{"meta":{"currency":"USD"},"timestamp":[1,2,3],"indicators":{"quote":'
                '[{"open":[1,null,3],"high":[2,2,4],"low":[0.5,1,2],"close":[1.5,1.5,3.5],"volume":[0,0,0]}]}}]}}')
        candles, meta = lab.parse_yahoo(text)
        self.assertEqual([c['t'] for c in candles], [1, 3])
        self.assertEqual(meta['currency'], 'USD')

    def test_resample_to_four_hours(self):
        c = path_candles([1, 2, 3, 4, 5, 6, 7, 8], start=0)
        out = lab.resample(c, 4 * 3600)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['c'], 4)


class PlaybookAndCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user = patch.object(lab, 'USER_PLAYBOOK', Path(self.tmp.name) / 'user.json')
        self.user.start()

    def tearDown(self):
        self.user.stop()
        self.tmp.cleanup()

    def test_playbook_finds_breakers(self):
        hits = lab.playbook('what is a breaker block')['matches']
        self.assertEqual(hits[0]['id'], 'breaker_block')
        self.assertTrue(lab.playbook('')['topics'])

    def test_saved_strategy_is_searchable_and_removable(self):
        lab.save_strategy('London sweep sell', 'Wait for the Asian high sweep\nSell the bearish breaker', ['asian sweep'])
        self.assertEqual(lab.playbook('asian sweep')['matches'][0]['name'], 'London sweep sell')
        self.assertEqual(lab.delete_strategy('London sweep sell')['removed'], 1)

    def test_pine_templates_fill_every_placeholder(self):
        for name in lab.PINE:
            res = lab.write_code('pine', name, output_dir=self.tmp.name)
            code = Path(res['path']).read_text()
            self.assertNotIn('$', code)
            self.assertTrue(res['check']['ok'], res['check'])
            self.assertTrue(code.startswith('//@version=5'))

    def test_code_check_catches_bad_python(self):
        self.assertFalse(lab.check_code('python', 'def x(:\n')['ok'])
        self.assertTrue(lab.check_code('python', 'print(1)\n')['ok'])


class ToolRegistration(unittest.TestCase):
    def test_tool_declares_and_dispatches(self):
        from actions import trading_lab as tool
        self.assertEqual(tool.TOOL['name'], 'trading_lab')
        out = tool.trading_lab({'action': 'playbook', 'query': 'fvg'})
        self.assertIn('fair_value_gap', out)
        self.assertIn('trading_lab', tool.trading_lab({'action': 'nope'}))


if __name__ == '__main__':
    unittest.main()
