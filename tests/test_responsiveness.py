import threading
import time
import unittest
from unittest.mock import patch
from core.background_writer import BackgroundWriter
from core import performance, quick_commands
from actions import web_search


class ResponsivenessTests(unittest.TestCase):
    def test_ordinary_search_skips_second_model(self):
        rows=[{'title': 'Official docs', 'url': 'https://example.com/docs', 'snippet': 'Current documentation'}]
        with patch.object(web_search, '_ddg_search', return_value=rows), patch.object(web_search, '_gemini_search', side_effect=AssertionError('Extra model call')):
            result=web_search._search('docs')
        self.assertIn('https://example.com/docs', result)

    def test_price_uses_fast_sources(self):
        with patch.object(web_search, '_quick_search', return_value='sources') as fetch:
            self.assertEqual(web_search._price('keyboard'), 'sources')
            fetch.assert_called_once_with('keyboard current price buy')

    def test_search_timeout_does_not_claim_current_facts(self):
        with patch.object(web_search, '_QUICK_SEARCH_SLOTS', threading.BoundedSemaphore(2)), patch.object(web_search, '_run_bounded', return_value=None):
            result=web_search._search('slow request')
        self.assertIn('no current sources were verified', result)

    def test_slow_write_does_not_hold_up_submission(self):
        entered, release, following = threading.Event(), threading.Event(), threading.Event()
        writer=BackgroundWriter()
        def slow():
            entered.set()
            release.wait(2)
        try:
            self.assertTrue(writer.submit(slow))
            self.assertTrue(entered.wait(1))
            self.assertTrue(writer.submit(following.set))
            self.assertFalse(following.is_set())
        finally:
            release.set()
        self.assertTrue(writer.flush())
        self.assertTrue(following.is_set())

    def test_writer_survives_error_and_keeps_order(self):
        errors, values = [], []
        writer=BackgroundWriter(on_error=lambda error: errors.append(str(error)))
        def broken():
            raise OSError('disk unavailable')
        writer.submit(values.append, 1)
        writer.submit(broken)
        writer.submit(values.append, 2)
        self.assertTrue(writer.flush())
        self.assertEqual(values, [1, 2])
        self.assertEqual(errors, ['disk unavailable'])

    def test_local_commands_work_without_provider(self):
        self.assertTrue(quick_commands.recognizes('/time Asia/Kolkata'))
        self.assertFalse(quick_commands.recognizes('What is the time?'))
        title, body=quick_commands.run('/time Asia/Kolkata')
        self.assertEqual(title, 'LOCAL TIME')
        self.assertIn('IST', body)
        self.assertIn('/recall', quick_commands.run('/help')[1])

    def test_performance_measures_next_audio_once(self):
        performance.cancel_response()
        with patch.object(performance, 'monotonic', side_effect=[100.0, 100.25]):
            performance.begin_typed_response()
            performance.first_audio()
            performance.first_audio()
        stats=performance.snapshot()
        rows=[r for r in stats['timings'] if r['name']=='typed_request_to_first_audio_received']
        self.assertEqual(rows[0]['last_ms'], 250)

if __name__ == '__main__':
    unittest.main()
