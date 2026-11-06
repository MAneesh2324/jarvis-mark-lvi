"""Fixes for errors seen in the live log on 2026-11-06.

  * file_processor: "File not found: ~/Desktop/…" — '~' was never expanded.
  * file_processor: convert to PDF did nothing for HTML, text, code or Word files.
  * code_helper: output_path '~/x.py' created a folder literally named '~'.
  * code_helper: write with ready-made code answered "Please describe what you want me to write".
  * browser_control: after the user closed the browser, every call failed with
    "Target page, context or browser has been closed".
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class HomeDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / 'Desktop').mkdir()
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class FileProcessor(HomeDir):
    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from actions.file_processor import file_processor
        self.fp = file_processor

    def test_tilde_path_is_found(self):
        (self.home / 'Desktop' / 'notes.py').write_text('print(1)\n')
        out = self.fp({'file_path': '~/Desktop/notes.py', 'action': 'info'})
        self.assertNotIn('File not found', out)
        self.assertIn('Code file', out)

    def test_missing_file_names_the_real_path(self):
        out = self.fp({'file_path': '~/Desktop/nope.html', 'action': 'convert', 'format': 'pdf'})
        self.assertIn(str(self.home / 'Desktop' / 'nope.html'), out)

    def test_html_and_code_to_pdf(self):
        html = self.home / 'Desktop' / 'Report.html'
        html.write_text('<h1>Bug report</h1><p>Steps to reproduce</p>')
        out = self.fp({'file_path': '~/Desktop/Report.html', 'action': 'convert', 'format': 'pdf'})
        self.assertIn('status=done', out)
        pdf = self.home / 'Desktop' / 'Report.pdf'
        self.assertTrue(pdf.exists())
        self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
        (self.home / 'Desktop' / 'gen.py').write_text('x = 1\n')
        out = self.fp({'file_path': '~/Desktop/gen.py', 'action': 'convert', 'format': 'pdf'})
        self.assertTrue((self.home / 'Desktop' / 'gen.pdf').exists(), out)


class CodeHelper(HomeDir):
    def setUp(self):
        super().setUp()
        from actions import code_helper as ch
        self.ch = ch

    def test_saves_given_code_at_home_path(self):
        cwd = Path.cwd()
        out = self.ch.code_helper({'action': 'write', 'language': 'python', 'output_path': '~/report_gen.py',
                                   'code': '```python\nprint("hello")\n```'})
        saved = self.home / 'report_gen.py'
        self.assertIn(str(saved), out)
        self.assertEqual(saved.read_text(), 'print("hello")\n')
        self.assertFalse((cwd / '~').exists())
        self.assertFalse((self.home / 'Desktop' / '~').exists())
        self.assertNotIn('describe', out)

    def test_relative_name_goes_to_desktop(self):
        with mock.patch.object(self.ch, 'DESKTOP', self.home / 'Desktop'):
            out = self.ch.code_helper({'action': 'write', 'language': 'html', 'output_path': 'page.html',
                                       'code': '<p>hi</p>'})
        self.assertTrue((self.home / 'Desktop' / 'page.html').exists(), out)


class BrowserRecovery(unittest.TestCase):
    def test_relaunches_after_the_browser_was_closed(self):
        from actions import browser_control as bc
        s = bc._BrowserSession.__new__(bc._BrowserSession)
        s.browser_name = 'test'
        dead = mock.MagicMock()
        dead.new_page = mock.AsyncMock(side_effect=Exception(
            'BrowserContext.new_page: Target page, context or browser has been closed'))
        dead.close = mock.AsyncMock()
        fresh_page = mock.MagicMock()
        fresh_page.is_closed.return_value = False
        closed_page = mock.MagicMock()
        closed_page.is_closed.return_value = True
        s._context, s._page = dead, closed_page
        launches = []

        async def launch():
            if s._context is None:
                s._context = mock.MagicMock()
                launches.append(1)

        s._launch = launch
        s._adopt_page = mock.AsyncMock(return_value=fresh_page)
        page = asyncio.run(s._get_page())
        self.assertIs(page, fresh_page)
        self.assertEqual(launches, [1])
        dead.close.assert_awaited()

    def test_other_errors_still_raise(self):
        from actions import browser_control as bc
        s = bc._BrowserSession.__new__(bc._BrowserSession)
        s.browser_name = 'test'
        ctx = mock.MagicMock()
        ctx.new_page = mock.AsyncMock(side_effect=RuntimeError('disk full'))
        s._context, s._page = ctx, None

        async def launch():
            pass

        s._launch = launch
        with self.assertRaises(RuntimeError):
            asyncio.run(s._get_page())


class ShutdownOnlyWhenAsked(unittest.TestCase):
    """JARVIS closed itself mid-conversation: shutdown_jarvis fired on goodbyes and stray words."""

    def test_plain_requests(self):
        import main
        for said in ('Jarvis, shut down', 'shutdown please', 'quit', 'close yourself', 'turn yourself off',
                     'switch off jarvis', 'power down', 'jarvis band karo'):
            self.assertTrue(main._says_shutdown(said), said)

    def test_not_a_shutdown(self):
        import main
        for said in ('okay bye', 'Jarvis mute okay, I have to do', 'stop', 'good night', 'wait a second',
                     'see you later', 'Can we continue on the bug bounty report?', 'Ya ves.', ''):
            self.assertFalse(main._says_shutdown(said), said)

    def test_who_and_where(self):
        import main
        from core.room_sense import RoomSense
        live = main.JarvisLive.__new__(main.JarvisLive)
        live._room = RoomSense()
        live._last_input_voice = False
        self.assertTrue(live._shutdown_is_clear(''))                 # typed in the window
        live._last_input_voice = True
        self.assertFalse(live._shutdown_is_clear('okay bye'))        # needs the on-screen button
        self.assertTrue(live._shutdown_is_clear('Jarvis, shut down'))
        live._room.active = True                                     # someone else is talking
        self.assertFalse(live._shutdown_is_clear('Jarvis, shut down'))

    def test_guests_cannot_close_it(self):
        import main
        self.assertIn('shutdown_jarvis', main.JarvisLive._SENSITIVE_TOOLS)


if __name__ == '__main__':
    unittest.main()
