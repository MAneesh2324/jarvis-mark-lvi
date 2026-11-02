import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from memory import memory_manager as mm
from memory import conversation_archive as archive
from actions.manage_memory import manage
from core.undo import undo_last


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_memory, self.old_db = mm.MEMORY_PATH, archive.DB_PATH
        mm.MEMORY_PATH = Path(self.tmp.name) / 'facts.json'
        archive.DB_PATH = Path(self.tmp.name) / 'history.db'

    def tearDown(self):
        mm.MEMORY_PATH, archive.DB_PATH = self.old_memory, self.old_db
        self.tmp.cleanup()

    def test_archive_survives_briefing_and_restart(self):
        for n in range(5):
            mm.save_session_summary(f'Project telescope milestone {n}')
        mm.pop_last_session()
        self.assertEqual(len(archive.search('telescope')), 5)
        self.assertEqual(archive.search('telescope')[0]['summary'], 'Project telescope milestone 4')
        self.assertEqual(archive.search("'; DROP TABLE summaries;--"), [])

    def test_migrate_pending_is_idempotent(self):
        old = {'sessions': [{'date': '2026-11-01', 'summary': 'Discussed Hindi voice'}]}
        archive.migrate_pending(old)
        archive.migrate_pending(old)
        self.assertEqual(len(archive.search('Hindi')), 1)

    def test_correct_forget_undo(self):
        mm.remember('drink', 'tea', 'preferences')
        self.assertIn('status=done', manage({'action':'correct', 'category':'preferences', 'key':'drink', 'value':'coffee'}))
        self.assertIn('coffee', mm.search_memory('drink'))
        undo_last()
        self.assertIn('tea', mm.search_memory('drink'))
        manage({'action':'forget', 'category':'preferences', 'key':'drink'})
        self.assertNotIn('drink', mm.load_memory()['preferences'])
        undo_last()
        self.assertIn('drink', mm.load_memory()['preferences'])

    def test_concurrent_memory_updates_survive(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda n: mm.update_memory({'notes': {f'item_{n}': str(n)}}), range(24)))
        self.assertEqual(len(mm.load_memory()['notes']), 24)

    def test_voice_pacing_and_undo(self):
        from unittest.mock import patch
        from memory import config_manager as cfg
        from actions.voice_pacing import configure
        test_config = Path(self.tmp.name) / 'config.json'
        test_config.write_text('{}')
        with patch.object(cfg, 'CONFIG_FILE', test_config), patch.object(cfg, 'CONFIG_DIR', Path(self.tmp.name)):
            original = cfg.get_turn_tuning()
            self.assertIn('status=done', configure({'preset': 'patient'}))
            self.assertEqual(cfg.get_turn_tuning()['silence_ms'], 1200)
            self.assertTrue(cfg.get_turn_tuning()['enabled'])
            undo_last()
            self.assertEqual(cfg.get_turn_tuning(), original)
            self.assertIn('status=failed', configure({'preset': 'bogus'}))

    def test_corrupt_store_recovers_previous_valid_backup(self):
        mm.remember('drink', 'tea')
        mm.remember('drink', 'coffee')
        mm.MEMORY_PATH.write_text('{broken json')
        self.assertEqual(mm.load_memory()['notes']['drink']['value'], 'tea')
        mm.remember('color', 'blue')
        self.assertEqual(mm.load_memory()['notes']['drink']['value'], 'tea')
        self.assertEqual(mm.MEMORY_PATH.stat().st_mode & 0o777, 0o600)

    def test_interrupted_replace_keeps_old_memory_valid(self):
        from unittest.mock import patch
        mm.remember('drink', 'tea')
        with patch.object(mm.os, 'replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                mm.remember('drink', 'coffee')
        self.assertEqual(mm.load_memory()['notes']['drink']['value'], 'tea')
        self.assertEqual(list(mm.MEMORY_PATH.parent.glob('.memory-*')), [])

    def test_undo_does_not_overwrite_newer_value(self):
        mm.remember('drink', 'tea')
        manage({'action':'correct', 'key':'drink', 'value':'coffee'})
        mm.remember('drink', 'water')
        undo_last()
        self.assertEqual(mm.load_memory()['notes']['drink']['value'], 'water')

if __name__ == '__main__':
    unittest.main()
