import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class Find(unittest.TestCase):
    def test_query_building(self):
        from core.mac_find import build_query
        q = build_query('resume', 'pdf', 7)
        self.assertIn('kMDItemDisplayName == "*resume*"cd', q)
        self.assertIn('com.adobe.pdf', q)
        self.assertIn('$time.today(-7)', q)
        self.assertIn('kMDItemWhereFroms', build_query(kind='installer', downloaded=True, days=2))
        self.assertIn('\\"', build_query('say "hi"'))           # quotes are escaped, not injected
        with self.assertRaises(ValueError):
            build_query()
        with self.assertRaises(ValueError):
            build_query(kind='hologram')

    def test_finds_a_real_file(self):
        from core.mac_find import find
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            p = Path(tmp) / 'jarvis_findme_7f3a.txt'
            p.write_text('hello')
            subprocess.run(['mdimport', str(p)], capture_output=True)
            for _ in range(20):
                r = find('jarvis_findme_7f3a', folder=tmp, content=False)
                if r['results']:
                    break
                time.sleep(0.5)
            if not r['results']:
                self.skipTest('Spotlight indexing is disabled or slow here')
            self.assertEqual(r['results'][0]['name'], 'jarvis_findme_7f3a.txt')


class Downloads(unittest.TestCase):
    def test_local_network_and_bad_links_refused(self):
        from core import downloads as dl
        for url in ('http://192.168.1.1/a.zip', 'http://127.0.0.1:8000/x', 'file:///etc/passwd', 'ftp://x/y'):
            with self.assertRaises(ValueError):
                dl.start(url)

    def test_download_completes_with_quarantine(self):
        from core import downloads as dl
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {'content-length': '11', 'content-disposition': 'attachment; filename="report.pdf"'}
        resp.url = 'https://example.com/get'
        resp.iter_content.return_value = [b'hello ', b'world']
        with tempfile.TemporaryDirectory() as tmp, patch.object(dl.requests, 'get', return_value=resp), \
                patch.object(dl, '_public', side_effect=lambda u: u):
            r = dl.start('https://example.com/get', folder=tmp)['download']
            self.assertEqual(r['state'], 'done')
            self.assertEqual(Path(r['path']).read_bytes(), b'hello world')
            self.assertEqual(Path(r['path']).name, 'report.pdf')
            q = subprocess.run(['xattr', '-p', 'com.apple.quarantine', r['path']], capture_output=True, text=True).stdout
            self.assertIn('JARVIS', q)
            self.assertFalse(any(n.endswith('.part') for n in os.listdir(tmp)))

    def test_unique_names(self):
        from core.downloads import unique
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.pdf').write_text('x')
            self.assertEqual(unique(Path(tmp), 'a.pdf').name, 'a (2).pdf')


class MacSystem(unittest.TestCase):
    def test_force_quit_needs_confirmation(self):
        from core import mac_system as ms
        app = MagicMock()
        app.localizedName.return_value = 'Calculator'
        app.activationPolicy.return_value = 0
        ws = MagicMock()
        ws.sharedWorkspace.return_value.runningApplications.return_value = [app]
        with patch.dict('sys.modules', {'AppKit': MagicMock(NSWorkspace=ws)}):
            r = ms.quit_app('calculator', force=True)
        self.assertTrue(r['needs_confirmation'])
        app.forceTerminate.assert_not_called()

    def test_storage_and_battery_shapes(self):
        from core import mac_system as ms
        self.assertGreater(ms.storage()['total_gb'], 0)
        self.assertIn('percent', ms.battery()) if ms.battery().get('percent') is not None else None

    def test_open_refuses_missing_paths(self):
        from core import mac_system as ms
        with self.assertRaises(ValueError):
            ms.open_item('/definitely/not/here.txt')


class BrowserAgentSafety(unittest.TestCase):
    SNAP = {'title': 'Shop', 'url': 'https://shop.example', 'elements': [
        {'id': 1, 'tag': 'button', 'type': 'submit', 'label': 'Place your order', 'href': '', 'visible': True, 'meta': ''},
        {'id': 2, 'tag': 'input', 'type': 'password', 'label': '', 'href': '', 'visible': True, 'meta': 'current-password'},
        {'id': 3, 'tag': 'input', 'type': 'text', 'label': 'Card number', 'href': '', 'visible': True, 'meta': 'cc-number'},
        {'id': 4, 'tag': 'a', 'type': '', 'label': 'Product details', 'href': '/p/1', 'visible': True, 'meta': ''},
        {'id': 5, 'tag': 'input', 'type': 'search', 'label': 'Search', 'href': '', 'visible': True, 'meta': 'q'}]}

    def test_guard_blocks_risky_clicks_and_secrets(self):
        from core.browser_agent import _guard
        self.assertIn('Shall I go ahead', _guard({'action': 'click', 'id': 1}, self.SNAP))
        self.assertIn("won't type", _guard({'action': 'type', 'id': 2, 'text': 'x'}, self.SNAP))
        self.assertIn("won't type", _guard({'action': 'type', 'id': 3, 'text': '4111'}, self.SNAP))
        self.assertIsNone(_guard({'action': 'click', 'id': 4}, self.SNAP))
        self.assertIsNone(_guard({'action': 'type', 'id': 5, 'text': 'shoes'}, self.SNAP))

    def test_agent_pauses_then_continues_only_on_approval(self):
        from core import browser_agent as ba
        steps = iter([{'action': 'click', 'id': 1, 'thought': 'buy it'}, {'action': 'done', 'answer': 'Ordered.'}])
        executed = []
        with patch.object(ba, '_session', return_value=MagicMock()), \
                patch.object(ba, '_snapshot', return_value=self.SNAP), \
                patch.object(ba, '_ask_model', side_effect=lambda prompt: next(steps)), \
                patch.object(ba, '_execute', side_effect=lambda s, step, snap, job: executed.append(step) or 'ok'), \
                patch('core.notify.send'):
            job = ba.start('Buy the item in my cart')
            for _ in range(100):
                if ba.status(job['id'])['state'] == 'waiting_for_user':
                    break
                time.sleep(0.02)
            self.assertEqual(ba.status(job['id'])['state'], 'waiting_for_user')
            self.assertEqual(executed, [])                  # nothing clicked before the user agreed
            ba.reply(job['id'], approve=True)
            for _ in range(100):
                if ba.status(job['id'])['state'] == 'done':
                    break
                time.sleep(0.02)
        self.assertEqual(ba.status(job['id'])['answer'], 'Ordered.')
        self.assertEqual(executed[0]['id'], 1)

    def test_declined_action_is_never_run(self):
        from core import browser_agent as ba
        steps = iter([{'action': 'click', 'id': 1}, {'action': 'done', 'answer': 'Left it in the cart.'}])
        executed = []
        with patch.object(ba, '_session', return_value=MagicMock()), patch.object(ba, '_snapshot', return_value=self.SNAP), \
                patch.object(ba, '_ask_model', side_effect=lambda prompt: next(steps)), \
                patch.object(ba, '_execute', side_effect=lambda s, step, snap, job: executed.append(step) or 'ok'), \
                patch('core.notify.send'):
            job = ba.start('Buy the item in my cart')
            for _ in range(100):
                if ba.status(job['id'])['state'] == 'waiting_for_user':
                    break
                time.sleep(0.02)
            ba.reply(job['id'], approve=False, text='no, not now')
            for _ in range(100):
                if ba.status(job['id'])['state'] == 'done':
                    break
                time.sleep(0.02)
        self.assertEqual(executed, [])


class Browser(unittest.TestCase):
    def test_ulaa_is_supported(self):
        from actions.browser_control import _ALIASES, _resolve_browser
        self.assertEqual(_ALIASES['zoho ulaa'], 'ulaa')
        spec = _resolve_browser('ulaa')
        self.assertEqual(spec['engine'], 'chromium')

    def test_tools_register(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        for name in ('find_files', 'downloads', 'mac_system', 'browser_agent', 'browser_control'):
            self.assertTrue(reg.has(name), name)


if __name__ == '__main__':
    unittest.main()


class BrowserAnswers(unittest.TestCase):
    def test_site_routing(self):
        from actions.browser_control import _site_route
        self.assertEqual(_site_route('MacBook on Flipkart')[2], 'https://www.flipkart.com/search?q=macbook')
        self.assertEqual(_site_route('search for wireless earbuds on amazon')[1], 'wireless earbuds')
        self.assertIsNone(_site_route('MacBooks near me')[2])
        self.assertIsNone(_site_route('facebook')[2])          # just the site name: open it, not a search

    def test_native_search_returns_results_for_answering(self):
        from actions import browser_control as bc
        peek = {'top_results_for_answering': [{'title': 'MacBook Air M5', 'url': 'https://x', 'snippet': 'Rs 1,34,240'}]}
        with patch.object(bc, '_open_native', return_value='status=unverified action=browser_control url=x'), \
                patch.object(bc, '_peek_search', return_value=peek), patch.object(bc._registry, 'has', return_value=False):
            out = bc.browser_control({'action': 'search', 'query': 'MacBook on Flipkart'})
        self.assertIn('MacBook Air M5', out)
        self.assertIn('Rs 1,34,240', out)
