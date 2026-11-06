"""Fixes for browser and WhatsApp failures seen in native-startup.log on 2026-11-06.

  1. browser_control: every open/search came back "unverified" - the page was
     never read back from the user's browser.
  2. browser_control: "Unknown browser action: 'open'".
  3. browser_control: "Could not launch chrome: BrowserType.launch_persistent_
     context: Chromium distribution 'chrome' is not found" on a Mac without
     Chrome (only Ulaa), plus the profile-in-use fallback.
  4. browser_control: "Click error: Locator.click: Target page, context or
     browser has been closed" - page actions now recover and retry once.
  5. browser_agent: "A browser task is already running" / "No browser task is
     waiting for you" - the newest request wins.
  6. send_message: "WhatsApp driver unavailable (cannot import name
     '_whatsapp_core' ...)" - WhatsApp now works without that module.

Nothing here opens a real website, drives a real browser or sends a message:
subprocess, osascript, playwright and pyautogui are all mocked.
"""
import asyncio
import io
import os
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


def _cp(args, rc=0, out='', err=''):
    return subprocess.CompletedProcess(args, rc, stdout=out, stderr=err)


ULAA_PS = ('/Applications/Ulaa.app/Contents/MacOS/Ulaa\n'
           '/Applications/Ulaa.app/Contents/Frameworks/Ulaa Framework.framework/Helpers/chrome_crashpad_handler\n'
           '/Applications/Claude.app/Contents/Frameworks/Electron Framework.framework/Helpers/chrome_crashpad_handler\n')


# ─────────────────────────────────────────────────────────────────────────────
# 1. Reading the page back from the user's own browser
# ─────────────────────────────────────────────────────────────────────────────
class OpenIsReadBack(unittest.TestCase):
    def setUp(self):
        from actions import browser_control as bc
        self.bc = bc
        self.patches = [mock.patch.object(bc, '_default_browser_cached', return_value='ulaa'),
                        mock.patch.object(bc, '_VERIFY_STEP', 0.01)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def fake_run(self, tab_urls, opened=None, ps=ULAA_PS, osa_err=''):
        """subprocess.run stand-in: `ps`, `osascript` (front-tab reads in order) and `open`."""
        urls = list(tab_urls)

        def run(args, **kw):
            if args[0] == 'ps':
                return _cp(args, out=ps)
            if args[0] == 'osascript':
                if osa_err:
                    return _cp(args, rc=1, err=osa_err)
                return _cp(args, out=(urls.pop(0) if len(urls) > 1 else urls[0]) + '\n')
            if args[0] == 'open':
                if opened is not None:
                    opened.append(args)
                return _cp(args)
            raise AssertionError(f'unexpected command {args}')
        return run

    def test_default_browser_path_is_confirmed_when_the_tab_shows_the_site(self):
        bc = self.bc
        opened = []
        target = 'https://www.google.com/search?q=MacBook'
        run = self.fake_run(['https://www.flipkart.com/', 'https://www.google.com/search?q=MacBook'], opened)
        with mock.patch.object(bc, '_OS', 'Darwin'), mock.patch.object(bc.subprocess, 'run', side_effect=run):
            out = bc._open_native(target, None)
        self.assertTrue(out.startswith('status=done '), out)
        self.assertIn('opened=https://www.google.com/search?q=MacBook', out)
        self.assertIn('browser=Ulaa', out)
        self.assertEqual(opened, [['open', target]])            # handed over exactly once

    def test_permission_refused_stays_unverified_and_says_why_fast(self):
        bc = self.bc
        run = self.fake_run([''], osa_err='execution error: Not authorized to send Apple events to Ulaa. (-1743)')
        t0 = time.monotonic()
        with mock.patch.object(bc, '_OS', 'Darwin'), mock.patch.object(bc.subprocess, 'run', side_effect=run):
            out = bc._open_native('https://www.flipkart.com', None)
        self.assertTrue(out.startswith('status=unverified '), out)
        self.assertIn('permission', out)
        self.assertIn('Automation', out)
        self.assertLess(time.monotonic() - t0, 1.0)             # gives up at once, no 3 s wait

    def test_an_old_tab_on_the_same_site_is_not_proof(self):
        bc = self.bc
        stale = 'https://www.flipkart.com/cart'
        run = self.fake_run([stale])                            # never changes
        with mock.patch.object(bc, '_VERIFY_SECONDS', 0.2), mock.patch.object(bc.subprocess, 'run', side_effect=run):
            out = bc._confirm_mac_open('https://www.flipkart.com/search?q=macbook', None, {'Ulaa': stale})
        self.assertTrue(out.startswith('status=unverified '), out)
        self.assertIn('showing_host=flipkart.com', out)
        self.assertNotIn('/cart', out)                          # the user's other page is not repeated

    def test_reopening_the_same_address_counts(self):
        bc = self.bc
        url = 'https://www.flipkart.com/'
        with mock.patch.object(bc.subprocess, 'run', side_effect=self.fake_run([url])):
            out = bc._confirm_mac_open('https://www.flipkart.com', None, {'Ulaa': url})
        self.assertTrue(out.startswith('status=done '), out)

    def test_nothing_readable_is_unverified(self):
        bc = self.bc
        with mock.patch.object(bc, '_VERIFY_SECONDS', 0.1), \
                mock.patch.object(bc.subprocess, 'run', side_effect=self.fake_run([''], ps='/usr/bin/zsh\n')):
            out = bc._confirm_mac_open('https://www.flipkart.com', None, {})
        self.assertTrue(out.startswith('status=unverified '), out)
        self.assertIn('no browser that can report its address was running', out)

    def test_named_browser_is_read_back_too(self):
        bc = self.bc
        opened = []
        run = self.fake_run(['', 'https://www.youtube.com/'], opened)
        with mock.patch.object(bc, '_OS', 'Darwin'), mock.patch.object(bc.subprocess, 'run', side_effect=run):
            out = bc._open_native('youtube.com', 'Ola')                 # what speech hears for Ulaa
        self.assertEqual(opened, [['open', '-a', 'Ulaa', 'https://youtube.com']])
        self.assertTrue(out.startswith('status=done '), out)

    def test_scripts_only_talk_to_running_browsers(self):
        bc = self.bc
        self.assertIn('URL of current tab of front window', bc._tab_url_script('Safari'))
        for app in ('Google Chrome', 'Ulaa', 'Brave Browser', 'Microsoft Edge', 'Arc', 'Vivaldi', 'Opera'):
            s = bc._tab_url_script(app)
            self.assertIn('URL of active tab of front window', s)
            self.assertIn(f'if application "{app}" is running', s)

    def test_site_matching(self):
        bc = self.bc
        self.assertTrue(bc._same_site('https://flipkart.com', 'https://www.flipkart.com/'))
        self.assertTrue(bc._same_site('https://www.google.com/search?q=x', 'https://google.com/search?q=x'))
        self.assertFalse(bc._same_site('https://www.flipkart.com', 'https://www.amazon.in/'))
        self.assertTrue(bc._same_site('file:///Users/me/Desktop/a%20b.html', 'file:///Users/me/Desktop/a b.html'))
        self.assertFalse(bc._same_site('https://x.com', ''))

    def test_crashpad_helpers_are_not_chrome(self):
        bc = self.bc
        with mock.patch.object(bc.subprocess, 'run', side_effect=self.fake_run([''])):
            self.assertEqual(bc._running_mac_browsers(), ['Ulaa'])
            with mock.patch.object(bc, '_OS', 'Darwin'):
                self.assertFalse(bc._browser_running('chrome'))
                self.assertTrue(bc._browser_running('ulaa'))

    def test_follow_up_click_resumes_on_the_opened_page(self):
        bc = self.bc
        with mock.patch.object(bc, '_open_native', return_value='status=unverified action=browser_control url=x'), \
                mock.patch.object(bc, '_peek_page', return_value=None), \
                mock.patch.object(bc._registry, 'has', return_value=False), \
                mock.patch.object(bc._registry, 'note_native_url') as note:
            bc.browser_control({'action': 'go_to', 'url': 'flipkart.com'})
        note.assert_called_once_with('https://flipkart.com')


# ─────────────────────────────────────────────────────────────────────────────
# 2. Action aliases
# ─────────────────────────────────────────────────────────────────────────────
class ActionAliases(unittest.TestCase):
    def run_nav(self, params):
        from actions import browser_control as bc
        with mock.patch.object(bc, '_open_native', return_value='status=done action=browser_control') as nat, \
                mock.patch.object(bc, '_peek_page', return_value=None), \
                mock.patch.object(bc, '_peek_search', return_value=None), \
                mock.patch.object(bc._registry, 'has', return_value=False), \
                mock.patch.object(bc._registry, 'note_native_url'):
            out = bc.browser_control(params)
        return out, nat

    def test_open_and_friends_mean_go_to(self):
        for word in ('open', 'Open', 'navigate', 'visit', 'goto', 'go', 'load', 'Go To', 'open-url', 'browse'):
            out, nat = self.run_nav({'action': word, 'url': 'https://www.flipkart.com'})
            self.assertTrue(out.startswith('status=done'), (word, out))
            nat.assert_called_once_with('https://www.flipkart.com', None)

    def test_open_with_words_becomes_a_search(self):
        out, nat = self.run_nav({'action': 'open', 'query': 'MacBook on Flipkart'})
        nat.assert_called_once_with('https://www.flipkart.com/search?q=macbook', None)
        out, nat = self.run_nav({'action': 'open', 'url': 'macbooks near me'})
        self.assertIn('google.com/search?q=macbooks+near+me', nat.call_args[0][0])

    def test_open_with_nothing_opens_the_browser(self):
        out, nat = self.run_nav({'action': 'open'})
        nat.assert_called_once_with('', None)

    def test_other_synonyms(self):
        from actions.browser_control import _normalize_action as n
        self.assertEqual(n({'action': 'scroll_up'}), {'action': 'scroll', 'direction': 'up'})
        self.assertEqual(n({'action': 'refresh'})['action'], 'reload')
        self.assertEqual(n({'action': 'read page'})['action'], 'get_text')
        self.assertEqual(n({'action': 'go back'})['action'], 'back')
        self.assertEqual(n({'action': 'web_search', 'query': 'x'})['action'], 'search')
        self.assertEqual(n({'action': 'search', 'url': 'flipkart.com'})['action'], 'go_to')
        self.assertEqual(n({'action': 'enter'}), {'action': 'press', 'key': 'Enter'})

    def test_unknown_action_fails_without_starting_a_browser(self):
        from actions import browser_control as bc
        with mock.patch.object(bc._registry, 'get') as get:
            out = bc.browser_control({'action': 'dance'})
        get.assert_not_called()
        self.assertTrue(out.startswith('status=failed'), out)
        self.assertIn('go_to', out)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Chrome not installed / profile in use
# ─────────────────────────────────────────────────────────────────────────────
class LaunchFallbacks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'HOME': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_missing_chrome_is_replaced_by_an_installed_chromium(self):
        from actions import browser_control as bc
        reg = bc._SessionRegistry()
        with mock.patch.object(bc, '_OS', 'Darwin'), \
                mock.patch.object(bc, '_mac_app_installed', side_effect=lambda n: n != 'chrome'), \
                mock.patch.object(bc, '_default_browser_cached', return_value='ulaa'), \
                mock.patch.object(reg, '_get_or_create', side_effect=lambda name: name):
            self.assertEqual(reg.get('chrome'), 'ulaa')
            self.assertEqual(reg.get('ulaa'), 'ulaa')

    def session(self, launches):
        from actions import browser_control as bc
        s = bc._BrowserSession.__new__(bc._BrowserSession)
        s.browser_name = 'ulaa'
        s._spec = {'engine': 'chromium', 'exe': '/Applications/Ulaa.app/Contents/MacOS/Ulaa', 'channel': None}
        s._context = s._page = None
        s.profile_kind = ''
        engine = mock.MagicMock()
        engine.launch_persistent_context = mock.AsyncMock(side_effect=launches)
        s._pw = mock.MagicMock(chromium=engine)
        s._adopt_page = mock.AsyncMock(return_value=mock.MagicMock())
        return s, engine

    def test_running_browser_uses_the_jarvis_profile(self):
        from actions import browser_control as bc
        ctx = mock.MagicMock()
        s, engine = self.session([ctx])
        with mock.patch.object(bc, '_browser_running', return_value=True):
            asyncio.run(s._launch())
        self.assertIs(s._context, ctx)
        self.assertEqual(s.profile_kind, 'separate')
        self.assertTrue(engine.launch_persistent_context.call_args[0][0].endswith('.jarvis_profiles/ulaa'))

    def test_real_profile_in_use_falls_back_to_jarvis_profile(self):
        from actions import browser_control as bc
        ctx = mock.MagicMock()
        s, engine = self.session([Exception('ProcessSingleton: profile in use'), ctx])
        with mock.patch.object(bc, '_browser_running', return_value=False):
            asyncio.run(s._launch())
        self.assertIs(s._context, ctx)
        self.assertEqual(s.profile_kind, 'separate')

    def test_jarvis_profile_in_use_gets_a_spare(self):
        from actions import browser_control as bc
        ctx = mock.MagicMock()
        s, engine = self.session([Exception('Failed to create a ProcessSingleton for your profile directory'), ctx])
        with mock.patch.object(bc, '_browser_running', return_value=True):
            asyncio.run(s._launch())
        self.assertIs(s._context, ctx)
        self.assertTrue(engine.launch_persistent_context.call_args[0][0].endswith('.jarvis_profiles/ulaa-2'))

    def test_other_launch_errors_still_raise(self):
        from actions import browser_control as bc
        s, _ = self.session([Exception("Chromium distribution 'chrome' is not found")])
        with mock.patch.object(bc, '_browser_running', return_value=True):
            with self.assertRaises(RuntimeError):
                asyncio.run(s._launch())


# ─────────────────────────────────────────────────────────────────────────────
# 4. Page actions recover from a closed page/browser
# ─────────────────────────────────────────────────────────────────────────────
CLOSED = 'Locator.click: Target page, context or browser has been closed'


class ClosedPageRetry(unittest.TestCase):
    def session(self):
        from actions import browser_control as bc
        s = bc._BrowserSession.__new__(bc._BrowserSession)
        s.browser_name = 'ulaa'
        s.profile_kind = 'separate'

        async def launch():
            if s._context is None:
                s._context = self.fresh_ctx
        s._launch = launch
        return s

    def page(self, closed_error=False):
        p = mock.MagicMock()
        p.is_closed.return_value = False
        click = mock.AsyncMock(side_effect=Exception(CLOSED)) if closed_error else mock.AsyncMock()
        p.get_by_text.return_value.first.click = click
        p.mouse.wheel = mock.AsyncMock(side_effect=Exception(CLOSED)) if closed_error else mock.AsyncMock()
        return p

    def test_click_on_a_closed_tab_opens_a_new_one_and_retries(self):
        dead, good = self.page(True), self.page()
        self.fresh_ctx = None
        s = self.session()
        s._context = mock.MagicMock()
        s._context.new_page = mock.AsyncMock(return_value=good)
        s._page = dead
        out = asyncio.run(s.click(text='close buy limit order'))
        good.get_by_text.return_value.first.click.assert_awaited()
        self.assertIn('clicked=true', out)
        self.assertNotIn('Click error', out)

    def test_scroll_after_the_browser_was_closed_relaunches(self):
        dead, good = self.page(True), self.page()
        dead_ctx = mock.MagicMock()
        dead_ctx.new_page = mock.AsyncMock(side_effect=Exception(
            'BrowserContext.new_page: Target page, context or browser has been closed'))
        dead_ctx.close = mock.AsyncMock()
        self.fresh_ctx = mock.MagicMock()
        s = self.session()
        s._context, s._page = dead_ctx, dead
        s._adopt_page = mock.AsyncMock(return_value=good)
        out = asyncio.run(s.scroll('down', 500))
        self.assertEqual(out, 'Scrolled down.')
        good.mouse.wheel.assert_awaited_with(0, 500)
        self.assertIs(s._context, self.fresh_ctx)

    def test_retries_only_once(self):
        self.fresh_ctx = None
        s = self.session()
        s._context = mock.MagicMock()
        s._context.new_page = mock.AsyncMock(side_effect=lambda: self.page(True))
        s._page = self.page(True)
        with self.assertRaises(Exception):
            asyncio.run(s.click(text='x'))
        self.assertEqual(s._context.new_page.await_count, 1)

    def test_other_click_errors_are_a_plain_failure(self):
        self.fresh_ctx = None
        s = self.session()
        s._context = mock.MagicMock()
        p = self.page()
        p.get_by_text.return_value.first.click = mock.AsyncMock(side_effect=Exception('element is not visible'))
        s._page = p
        out = asyncio.run(s.click(text='x'))
        self.assertTrue(out.startswith('status=failed'), out)

    def test_every_page_action_goes_through_recovery(self):
        from actions.browser_control import _BrowserSession
        for name in ('go_to', 'click', 'type_text', 'scroll', 'press', 'get_text', 'get_url', 'fill_form',
                     'smart_click', 'smart_type', 'new_tab', 'screenshot', 'back', 'forward', 'reload'):
            self.assertTrue(hasattr(getattr(_BrowserSession, name), '__wrapped__'), name)

    def test_dispatcher_errors_are_status_lines(self):
        from actions import browser_control as bc
        sess = mock.MagicMock()
        sess.run.side_effect = RuntimeError("Could not launch chrome: Chromium distribution 'chrome' is not found")
        with mock.patch.object(bc._registry, 'get', return_value=sess), \
                mock.patch.object(bc._registry, 'pop_native_url', return_value=''):
            out = bc.browser_control({'action': 'scroll'})
        self.assertTrue(out.startswith('status=failed'), out)
        self.assertIn('is not found', out)


# ─────────────────────────────────────────────────────────────────────────────
# 5. browser_agent: the newest request wins
# ─────────────────────────────────────────────────────────────────────────────
SNAP = {'title': 'Flipkart', 'url': 'https://www.flipkart.com', 'elements': [
    {'id': 1, 'tag': 'a', 'type': '', 'label': 'MacBook Air', 'href': '/p/1', 'visible': True, 'meta': ''}]}


class BrowserAgentNewestWins(unittest.TestCase):
    def setUp(self):
        from core import browser_agent as ba
        self.ba = ba
        self.release = threading.Event()
        self.executed = []
        self.notes = []

        def model(prompt):
            if 'PCs' in prompt:                       # the old task: thinks for a long time
                self.release.wait(5)
                return {'action': 'click', 'id': 1}
            return {'action': 'done', 'answer': 'Found MacBooks.'}

        self.patches = [
            mock.patch.dict(ba._jobs, {}, clear=True),
            mock.patch.object(ba, '_session', return_value=mock.MagicMock()),
            mock.patch.object(ba, '_snapshot', return_value=SNAP),
            mock.patch.object(ba, '_ask_model', side_effect=model),
            mock.patch.object(ba, '_execute', side_effect=lambda s, step, snap, job: self.executed.append(
                (job['id'], step)) or 'ok'),
            mock.patch('core.notify.send', side_effect=lambda *a, **k: self.notes.append(a)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        self.ba.stop()                                # no worker may outlive the mocks
        self.release.set()
        for t in list(self.ba._threads.values()):
            t.join(timeout=2)
        for p in reversed(self.patches):
            p.stop()

    def wait_state(self, job_id, state):
        for _ in range(200):
            if self.ba.status(job_id)['state'] == state:
                return True
            time.sleep(0.01)
        return False

    def test_start_while_running_replaces_the_old_task(self):
        from actions.browser_agent import browser_agent
        old = self.ba.start('check for available PCs on Flipkart')
        out = browser_agent({'action': 'start', 'goal': 'search for available MacBooks on Flipkart'})
        self.assertTrue(out.startswith('status=started'), out)
        self.assertIn(f'replaced_task={old["id"]}', out)
        self.assertEqual(self.ba.status(old['id'])['state'], 'stopped')
        new_id = out.split(' id=')[1].split()[0]
        self.assertTrue(self.wait_state(new_id, 'done'))
        self.release.set()                            # the old model call returns late…
        time.sleep(0.1)
        self.assertEqual([e for e in self.executed if e[0] == old['id']], [])   # …and does nothing
        self.assertEqual(self.ba.status(old['id'])['state'], 'stopped')
        self.assertFalse(any('PCs' in str(n) for n in self.notes))

    def test_reply_with_nothing_waiting_starts_the_text_as_a_task(self):
        from actions.browser_agent import browser_agent
        for word in ('reply', 'update', 'answer', 'continue'):
            out = browser_agent({'action': word, 'id': 'gone1234', 'text': 'search for available laptops instead'})
            self.assertTrue(out.startswith('status=started'), (word, out))
            self.assertIn('started_new_task=true', out)
            self.assertNotIn('No browser task', out)
            new_id = out.split(' id=')[1].split()[0]
            self.assertIn('laptops', self.ba._jobs[new_id]['goal'])
            self.assertTrue(self.wait_state(new_id, 'done'))

    def test_follow_up_keeps_the_earlier_goal_as_context(self):
        first = self.ba.start('find MacBooks on Flipkart')
        self.assertTrue(self.wait_state(first['id'], 'done'))
        res = self.ba.reply(first['id'], text='sort them by highest price first')
        self.assertTrue(res['started_new_task'])
        self.assertIn('find MacBooks on Flipkart', self.ba._jobs[res['id']]['goal'])

    def test_a_bare_yes_with_nothing_waiting_is_not_a_task(self):
        from actions.browser_agent import browser_agent
        out = browser_agent({'action': 'reply', 'approve': True, 'text': 'yes'})
        self.assertTrue(out.startswith('status=failed'), out)
        self.assertEqual(self.ba._jobs, {})

    def test_update_to_a_running_task_still_goes_to_it(self):
        old = self.ba.start('check for available PCs on Flipkart')
        res = self.ba.reply(old['id'], text='laptops instead of PCs')
        self.assertEqual(res['id'], old['id'])
        self.assertEqual(self.ba._jobs[old['id']]['updates'], ['laptops instead of PCs'])

    def test_tool_is_registered_with_the_new_handler(self):
        from actions import browser_agent as mod
        self.assertIs(mod.TOOL['handler'], mod.browser_agent)
        self.assertEqual(mod.TOOL['name'], 'browser_agent')
        self.assertIn('newest request always wins', mod.TOOL['description'])


# ─────────────────────────────────────────────────────────────────────────────
# 6. WhatsApp without plugins/_whatsapp_core.py
# ─────────────────────────────────────────────────────────────────────────────
class WhatsAppSending(unittest.TestCase):
    def setUp(self):
        from actions import send_message as sm
        self.sm = sm
        self.gui = mock.MagicMock()
        self.calls = []

        def run(args, **kw):
            self.calls.append(list(args))
            return _cp(args)

        self.patches = [
            mock.patch.object(sm, '_get_os', return_value='mac'),
            mock.patch.object(sm, 'pyautogui', self.gui),
            mock.patch.object(sm, '_paste_text', side_effect=lambda t: self.gui.paste(t)),
            mock.patch.object(sm, '_search_in_app', side_effect=lambda q: self.gui.search(q)),
            mock.patch.object(sm.time, 'sleep'),
            mock.patch.object(sm.subprocess, 'run', side_effect=run),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_phone_numbers_are_recognised(self):
        d = self.sm._phone_digits
        self.assertEqual(d('+916282321289'), '916282321289')
        self.assertEqual(d('+91 62823 21289'), '916282321289')
        self.assertEqual(d('Noble Andrew', phone='+1 (415) 555-0100'), '14155550100')
        self.assertEqual(d('Noble Andrew'), '')
        self.assertEqual(d('Noble 2'), '')
        self.assertEqual(d('12'), '')

    def test_number_uses_the_whatsapp_link_and_never_claims_sent(self):
        with mock.patch.object(self.sm, '_frontmost_app', return_value='WhatsApp'):
            out = self.sm._send_whatsapp('+916282321289', 'JARVIS alert: check now & reply')
        self.assertIn(['open', 'whatsapp://send?phone=916282321289&text=JARVIS%20alert%3A%20check%20now%20%26%20reply'],
                      self.calls)
        self.gui.press.assert_called_once_with('enter')
        self.assertTrue(out.startswith('status=unverified'), out)
        self.assertNotIn('status=done', out)

    def test_enter_is_not_pressed_when_whatsapp_is_not_in_front(self):
        with mock.patch.object(self.sm, '_frontmost_app', return_value='Ulaa'), \
                mock.patch.object(self.sm.time, 'monotonic', side_effect=[0, 0, 100, 100, 100]):
            out = self.sm._send_whatsapp('+916282321289', 'hi')
        self.gui.press.assert_not_called()
        self.assertTrue(out.startswith('status=unverified'), out)
        self.assertIn('NOT', out)

    def test_contact_name_types_only_while_whatsapp_is_in_front(self):
        with mock.patch.object(self.sm, '_frontmost_app', return_value='WhatsApp'):
            out = self.sm._send_whatsapp('Noble Andrew', 'Hello again')
        self.assertIn(['open', '-a', 'WhatsApp'], self.calls)
        self.gui.search.assert_called_once_with('Noble Andrew')
        self.gui.paste.assert_called_once_with('Hello again')
        self.assertTrue(out.startswith('status=unverified'), out)

    def test_contact_name_stops_if_another_app_is_in_front(self):
        with mock.patch.object(self.sm, '_frontmost_app', return_value='TradingView'), \
                mock.patch.object(self.sm.time, 'monotonic', side_effect=[0, 0, 100]):
            out = self.sm._send_whatsapp('Noble Andrew', 'Hello again')
        self.gui.paste.assert_not_called()
        self.gui.search.assert_not_called()
        self.assertTrue(out.startswith('status=failed'), out)

    def test_no_import_noise(self):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(self.sm, '_frontmost_app', return_value='WhatsApp'):
            self.sm._send_whatsapp('Noble Andrew', 'Hello')
        self.assertNotIn('_whatsapp_core', buf.getvalue())
        self.assertNotIn('driver unavailable', buf.getvalue())
        src = Path(self.sm.__file__).read_text(encoding='utf-8')
        self.assertNotIn('from plugins import _whatsapp_core', src)

    def test_phone_parameter_reaches_whatsapp(self):
        with mock.patch.object(self.sm, '_send_whatsapp', return_value='status=unverified action=send_message') as wa:
            self.sm._send_and_report(None, 'WhatsApp', 'Noble', 'hi', '+916282321289')
        wa.assert_called_once_with('Noble', 'hi', '+916282321289')

    def test_frontmost_app_reads_lsappinfo(self):
        def run(args, **kw):
            if args[:2] == ['lsappinfo', 'front']:
                return _cp(args, out='ASN:0x0-0xea3ea3:\n')
            return _cp(args, out='"WhatsApp" ASN:0x0-0xea3ea3: (in front)\n')
        with mock.patch.object(self.sm.subprocess, 'run', side_effect=run):
            self.assertEqual(self.sm._frontmost_app(), 'WhatsApp')

    def test_tool_description_says_what_works(self):
        desc = self.sm.TOOL['description']
        self.assertIn('phone number', desc)
        self.assertIn('WhatsApp desktop', desc)
        self.assertIn('phone', self.sm.TOOL['parameters']['properties'])


if __name__ == '__main__':
    unittest.main()
