"""OWASP Top 10:2025 reference knowledge and the code pattern check."""
import json
import tempfile
import unittest
from pathlib import Path


class Knowledge(unittest.TestCase):
    def test_the_2025_list_in_order(self):
        from core import owasp
        names = [c['name'] for c in owasp.TOP10]
        self.assertEqual(names, ['Broken Access Control', 'Security Misconfiguration', 'Software Supply Chain Failures',
                                 'Cryptographic Failures', 'Injection', 'Insecure Design', 'Authentication Failures',
                                 'Software or Data Integrity Failures', 'Security Logging and Alerting Failures',
                                 'Mishandling of Exceptional Conditions'])
        for c in owasp.TOP10:
            for key in ('summary', 'examples', 'cwe', 'prevent', 'test', 'was_2021'):
                self.assertTrue(c[key], (c['id'], key))

    def test_finding_by_number_topic_and_old_number(self):
        from core import owasp
        self.assertEqual(owasp.find('A03')['name'], 'Software Supply Chain Failures')
        self.assertEqual(owasp.find('5')['name'], 'Injection')
        self.assertEqual(owasp.find('SQL injection')['id'], 'A05')
        self.assertEqual(owasp.find('ssrf')['id'], 'A01')
        self.assertEqual(owasp.find('A03:2021')['id'], 'A05')            # 2021 Injection is 2025 A05
        self.assertEqual(owasp.find('A10:2021')['id'], 'A01')            # SSRF merged into access control
        self.assertEqual(owasp.find('A06:2021')['id'], 'A03')
        self.assertIsNone(owasp.find('quantum banana'))

    def test_quiz_answer_matches_the_example(self):
        from core import owasp
        q = owasp.quiz(seed=3)
        cid = q['answer'].split()[0]
        example = q['question'].split('"')[1]
        self.assertIn(example, owasp.find(cid)['examples'])


class CodeCheck(unittest.TestCase):
    RISKY = '''import hashlib, pickle, subprocess, requests
DEBUG = True
API_KEY = "sk_live_abcdef123456"
def view(request, cur):
    cur.execute(f"SELECT * FROM users WHERE id = {request.GET['id']}")
    subprocess.run("ping " + request.GET["host"], shell=True)
    data = pickle.loads(request.body)
    pw = hashlib.md5(request.POST["password"].encode()).hexdigest()
    requests.get(url, verify=False)
    try:
        check_permission(request.user)
    except Exception: pass
    try:
        audit(request)
    except Exception:
        pass
'''
    SAFE = '''import secrets
def view(request, cur):
    cur.execute("SELECT * FROM users WHERE id = %s", (request.GET["id"],))
    token = secrets.token_urlsafe(32)
    # eval(x) mentioned only in a comment
    return token
'''

    def test_flags_each_risk_with_its_category(self):
        from core import owasp
        out = owasp.check_code(self.RISKY)
        cats = {f['category'].split()[0] for f in out['findings']}
        self.assertTrue({'A02', 'A04', 'A05', 'A07', 'A08', 'A10'} <= cats, cats)
        self.assertIn(5, [f['line'] for f in out['findings'] if f['category'].startswith('A05')])
        self.assertEqual(sum(f['issue'] == 'Exception silently swallowed' for f in out['findings']), 2)

    def test_safe_code_is_quiet(self):
        from core import owasp
        self.assertEqual(owasp.check_code(self.SAFE)['findings'], [])


class Tool(unittest.TestCase):
    def test_tool_actions(self):
        from actions.owasp_top10 import owasp_top10 as t
        self.assertEqual(len(json.loads(t({'action': 'list'}))['categories']), 10)
        self.assertIn('Injection', t({'action': 'explain', 'item': 'xss'}))
        self.assertIn('checklist', json.loads(t({'action': 'checklist', 'item': 'A07'})))
        self.assertIn('A10:2021', t({'action': 'changes'}))
        self.assertTrue(t({'action': 'explain', 'item': 'quantum banana'}).startswith('status=ask'))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'app.py'
            f.write_text(CodeCheck.RISKY)
            out = t({'action': 'check_code', 'file_path': str(f)})
        self.assertIn('UNTRUSTED', out)
        self.assertIn('Unsafe deserialisation', out)

    def test_tool_registers(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('owasp_top10'))


if __name__ == '__main__':
    unittest.main()
