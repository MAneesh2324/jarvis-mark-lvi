import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core import news_engine as ne, setup_tracker as st, auto_learning as al

RSS = '''<?xml version="1.0"?><rss><channel>
<item><title>Leaders agree climate deal at summit</title><link>https://a.example/1</link>
<pubDate>{now}</pubDate><description>&lt;p&gt;Talks ended &lt;b&gt;late&lt;/b&gt;.&lt;/p&gt;</description></item>
<item><title>Storm hits coast</title><link>https://a.example/2</link><pubDate>{now}</pubDate></item>
</channel></rss>'''
ATOM = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Summit leaders agree on climate deal</title><link rel="alternate" href="https://b.example/9"/>
<updated>{iso}</updated><summary>Agreement reached.</summary></entry></feed>'''
GOOGLE = '''<rss><channel><item><title>Gold jumps as dollar slides - Reuters</title><link>https://news.google.com/x</link>
<source url="https://reuters.com">Reuters</source><pubDate>{now}</pubDate></item></channel></rss>'''


def stamp():
    now = datetime.now(timezone.utc)
    return {'now': now.strftime('%a, %d %b %Y %H:%M:%S +0000'), 'iso': now.isoformat()}


class Parsing(unittest.TestCase):
    def test_rss_atom_and_aggregator_source(self):
        rss = ne.parse_feed(RSS.format(**stamp()), 'A')
        self.assertEqual(rss[0]['summary'], 'Talks ended late .')
        self.assertIsNotNone(rss[0]['published'])
        atom = ne.parse_feed(ATOM.format(**stamp()), 'B')
        self.assertEqual(atom[0]['url'], 'https://b.example/9')
        g = ne.parse_feed(GOOGLE.format(**stamp()), 'Google News')
        self.assertEqual((g[0]['source'], g[0]['title']), ('Reuters', 'Gold jumps as dollar slides'))

    def test_rejects_entity_declarations(self):
        with self.assertRaises(ValueError):
            ne.parse_feed('<!DOCTYPE x [<!ENTITY a "b">]><rss/>', 'X')


class Clustering(unittest.TestCase):
    def test_same_story_from_two_outlets_is_corroborated(self):
        arts = ne.parse_feed(RSS.format(**stamp()), 'A') + ne.parse_feed(ATOM.format(**stamp()), 'B')
        stories = ne.cluster(arts)
        top = stories[0]
        self.assertEqual(top['outlet_count'], 2)
        self.assertIn('2 independent outlets', top['corroboration'])
        storm = next(s for s in stories if 'Storm' in s['headline'])
        self.assertIn('unconfirmed', storm['corroboration'])

    def test_headlines_survive_a_failing_outlet(self):
        def fake(source, url, ttl, refresh):
            if source == 'NPR':
                raise RuntimeError('down')
            return ne.parse_feed(RSS.format(**stamp()), source)
        with patch.object(ne, '_fetch', side_effect=fake):
            out = ne.headlines('world', 5)
        self.assertEqual(out['outlets_failed'], ['NPR'])
        self.assertGreaterEqual(out['stories'][0]['outlet_count'], 2)


class Interests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(ne, 'INTERESTS', Path(self.tmp.name) / 'i.json'); self.p.start()

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def test_repeated_searches_and_follows_become_interests(self):
        ne.note_interest('gold price'); self.assertEqual(ne.interests(), [])
        ne.note_interest('Gold price'); self.assertEqual(ne.interests(), ['gold price'])
        ne.follow('RBI policy')
        self.assertEqual(ne.interests()[0], 'RBI policy')
        ne.follow('RBI policy', on=False)
        self.assertNotIn('RBI policy', ne.interests())


def candles(path, start=1_700_000_000, step=3600):
    out, prev = [], path[0]
    for i, (h, l, c) in enumerate(path):
        out.append({'t': start + i * step, 'o': prev, 'h': h, 'l': l, 'c': c, 'v': 0}); prev = c
    return out


class SetupTracking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(st, 'DB_PATH', Path(self.tmp.name) / 't.db'); self.p.start()
        self.setup = {'setup': 'bearish breaker block', 'direction': 'sell', 'zone_low': 100, 'zone_high': 101,
                      'entry': 100, 'stop': 101.1, 'target_idea': 97.8, 'reward_to_risk': 2, 'score': 5,
                      'confluence': ['overlaps key level (3 touches)']}

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def test_win_loss_and_dedupe(self):
        self.assertEqual(st.record('EUR/USD', '1h', [self.setup], 1_700_000_000), 1)
        self.assertEqual(st.record('EURUSD', '1h', [self.setup], 1_700_000_000), 0)  # same zone, same market
        path = [(99.5, 99, 99.2), (100.2, 99.1, 99.8), (99.9, 98.5, 98.6), (98.7, 97.5, 97.7), (98, 97, 97.5)]
        st.evaluate('EURUSD', '1h', candles(path))
        s = st.stats()
        self.assertEqual(s['by_status'], {'won': 1})
        self.assertEqual(s['overall']['total_r'], 2.0)

    def test_stop_on_fill_candle_is_a_loss_and_target_on_fill_candle_is_ignored(self):
        st.record('XAUUSD', '1h', [self.setup], 1_700_000_000)
        path = [(99, 98.9, 99), (101.5, 97, 99), (99, 98.9, 99)]
        st.evaluate('XAUUSD', '1h', candles(path))
        self.assertEqual(st.stats()['by_status'], {'lost': 1})

    def test_unfilled_setup_expires(self):
        st.record('GBPUSD', '1h', [self.setup], 1_700_000_000)
        path = [(99, 98, 98.5)] * (st.EXPIRE_CANDLES + 2)
        st.evaluate('GBPUSD', '1h', candles(path))
        self.assertEqual(st.stats()['by_status'], {'expired': 1})

    def test_ranking_nudge_needs_a_real_sample(self):
        ranked = [dict(self.setup, score=5)]
        with patch.object(st, 'edges', return_value={'bearish breaker block': {'closed': 4, 'wins': 3, 'avg_r': 1.2,
                                                                                 'ranking_nudge': 0}}):
            out = st.annotate(ranked)
        self.assertEqual(out[0]['score'], 5)
        self.assertIn('sample still small', out[0]['learned_track_record'])

    def test_records_real_analyser_output(self):
        from core import trading_lab as lab
        from tests.test_trading_lab import breaker_story
        report = lab.analyse({'symbol': 'T', 'interval': '1h', 'candles': breaker_story()}, learn=False)
        ideas = [{**self.setup, 'zone_low': 200, 'zone_high': 201, 'entry_idea': 200, 'stop_idea': 201.1, 'target_idea': 197.8}]
        for s in ideas:
            for k in ('entry', 'stop'):
                s.pop(k, None)
        self.assertEqual(st.record('T', '1h', ideas + report['setups_ranked'], 1_700_000_000),
                         1 + len(report['setups_ranked']))

    def test_default_watchlist_and_watch(self):
        self.assertTrue(st.watchlist())
        st.watch('btc/usd', '4h')
        self.assertEqual(st.watchlist()[0]['symbol'], 'BTCUSD')


class Background(unittest.TestCase):
    def test_disabled_learner_starts_nothing(self):
        with patch.object(al, 'settings', return_value={**al.DEFAULTS, 'enabled': False}), \
                patch.object(al.threading, 'Thread') as thread:
            al.tick()
        thread.assert_not_called()

    def test_context_is_compact_text(self):
        brief = {'updated': '2026-11-05T03:00:00', 'sources': {
            'news': {'world': [{'headline': 'Big story', 'outlets': 3, 'updated': 'x'}]},
            'trading_learning': 'Trading forward-tracking: 3 setups logged.'}}
        with patch.object(al, 'current', return_value=brief):
            text = al.context()
        self.assertIn('Big story (3 outlets)', text)
        self.assertIn('forward-tracking', text)
        self.assertLess(len(text), 6000)

    def test_configure_clamps_interval_and_categories(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(al, 'CONFIG', Path(tmp) / 'c.json'):
            out = al.configure(True, interval_minutes=1, news_categories=['world', 'nonsense'])
            self.assertEqual((out['interval_minutes'], out['news_categories']), (10, ['world']))
            self.assertTrue(json.loads((Path(tmp) / 'c.json').read_text())['enabled'])


class Tool(unittest.TestCase):
    def test_news_tool_errors_are_reported_not_raised(self):
        from actions.news import news, TOOL
        self.assertEqual(TOOL['name'], 'news')
        self.assertIn('news', news({'action': 'headlines', 'category': 'sports'}))
        self.assertIn('news', news({'action': 'read', 'url': 'http://127.0.0.1/x'}))


if __name__ == '__main__':
    unittest.main()
