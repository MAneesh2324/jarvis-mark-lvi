import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class Diagnostics(unittest.TestCase):
    def test_quick_run_scores_and_saves(self):
        from core import diagnostics as dg
        with tempfile.TemporaryDirectory() as tmp, patch.object(dg, 'REPORTS', Path(tmp)), \
                patch.object(dg, 'LAST', Path(tmp) / 'last.md'):
            r = dg.run('quick')
            self.assertTrue(0 <= r['score'] <= 100)
            self.assertEqual({s['section'] for s in r['sections']},
                             {'System', 'CPU', 'Memory', 'Storage', 'Battery', 'Network'})
            for s in r['sections']:
                for c in s['checks']:
                    self.assertIn(c['status'], ('ok', 'warn', 'critical'))
            text = Path(r['report_path']).read_text()
            self.assertIn('Health score', text)
            self.assertTrue((Path(tmp) / 'last.md').exists())

    def test_score_reflects_issues(self):
        from core import diagnostics as dg
        fake = lambda *a, **k: {'section': 'X', 'info': {}, 'checks': [dg._check('a', 'critical', 'bad', 'fix it'),
                                                                        dg._check('b', 'warn', 'meh', 'tweak')]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(dg, 'REPORTS', Path(tmp)), \
                patch.object(dg, 'LAST', Path(tmp) / 'l.md'), patch.dict(dg.SECTIONS, {'cpu': fake}):
            r = dg.run('standard', ['cpu'])
        self.assertEqual(r['score'], 74)
        self.assertEqual(r['issues'][0]['status'], 'critical')
        self.assertIn('fix it', r['issues'][0]['fix'])

    def test_a_failing_section_does_not_break_the_run(self):
        from core import diagnostics as dg
        def boom():
            raise RuntimeError('nope')
        with tempfile.TemporaryDirectory() as tmp, patch.object(dg, 'REPORTS', Path(tmp)), \
                patch.object(dg, 'LAST', Path(tmp) / 'l.md'), patch.dict(dg.SECTIONS, {'disk': boom}):
            r = dg.run('standard', ['disk', 'system'])
        self.assertEqual(len(r['sections']), 2)
        self.assertTrue(any('could not run' in c['detail'] for c in r['issues']))

    def test_tool_registers_and_reads_last(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('system_diagnostic'))


if __name__ == '__main__':
    unittest.main()
