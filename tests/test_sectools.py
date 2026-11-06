"""Ethical-hacking tools reference (explain-only)."""
import json
import unittest
from pathlib import Path


class Knowledge(unittest.TestCase):
    def test_every_tool_is_complete_and_defensible(self):
        from core import sectools as st
        phases = {k for k, _, _ in st.PHASES}
        self.assertGreaterEqual(len(st.TOOLS), 20)
        for t in st.TOOLS:
            for key in ('name', 'purpose', 'usage', 'defend'):
                self.assertTrue(t[key], (t['name'], key))
            self.assertIn(t['category'], phases)            # each tool maps to a real phase
            self.assertTrue(t['usage'] and all(t['usage']))

    def test_find_by_name_and_alias(self):
        from core import sectools as st
        self.assertEqual(st.find('nmap')['name'], 'Nmap')
        self.assertEqual(st.find('Burp')['name'], 'Burp Suite')
        self.assertEqual(st.find('msf')['name'], 'Metasploit Framework')
        self.assertEqual(st.find('jtr')['name'], 'John the Ripper')
        self.assertEqual(st.find('ffuf')['name'].split(' /')[0], 'Gobuster')
        self.assertIsNone(st.find('a flute'))

    def test_phases_group_tools(self):
        from core import sectools as st
        self.assertIn('Nmap', [t['name'] for t in st.in_phase('scanning')])
        self.assertIn('sqlmap', [t['name'] for t in st.in_phase('web')])
        self.assertEqual(st.in_phase('not a phase'), [])


class Tool(unittest.TestCase):
    def test_actions(self):
        from actions.security_toolkit import security_toolkit as t
        listed = json.loads(t({'action': 'list'}))
        self.assertGreaterEqual(len(listed['tools']), 20)
        self.assertEqual(len(listed['phases']), 9)

        explained = json.loads(t({'action': 'explain', 'item': 'sqlmap'}))
        self.assertIn('typical_usage', explained)
        self.assertIn('how_to_detect_and_defend', explained)       # defence is always present

        self.assertTrue(t({'action': 'explain', 'item': 'a flute'}).startswith('status=ask'))

        method = json.loads(t({'action': 'methodology'}))
        self.assertEqual(len(method['engagement_phases']), 9)

        web = json.loads(t({'action': 'phase', 'item': 'web'}))
        self.assertTrue(any('Burp' in x for x in web['tools']))

        lab = json.loads(t({'action': 'lab'}))
        self.assertTrue(any('PortSwigger' in x for x in lab['legal_practice_grounds']))
        self.assertIn('permission', lab['how_to_set_up'])

    def test_no_run_action_exists(self):
        from actions.security_toolkit import TOOL
        self.assertEqual(set(TOOL['parameters']['properties']['action']['enum']),
                         {'list', 'explain', 'phase', 'methodology', 'lab'})   # nothing that executes

    def test_tool_registers(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('security_toolkit'))


if __name__ == '__main__':
    unittest.main()
