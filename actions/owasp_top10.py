"""Voice tool: OWASP Top 10 (2025) — explain, compare with 2021, checklists, quiz, and a quick code check."""
import json

from core import outcome


def owasp_top10(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'list')
    try:
        from core import owasp
        item = str(p.get('item') or '').strip()
        if action == 'list':
            data = {'edition': owasp.EDITION, 'source': owasp.SOURCE,
                    'categories': [f"{c['id']} {c['name']} — {c['summary']}" for c in owasp.TOP10]}
        elif action in ('explain', 'checklist'):
            c = owasp.find(item)
            if c is None:
                return outcome.ask('owasp_top10', f'Which category did you mean? "{item}" did not match one. '
                                   'Name it by number (A01-A10) or topic (SQL injection, SSRF, passwords...).')
            data = dict(c, edition=owasp.EDITION, source=owasp.SOURCE) if action == 'explain' else \
                {'category': f"{c['id']} {c['name']}", 'checklist': c['prevent'], 'how_to_test_your_own_system': c['test']}
        elif action == 'changes':
            data = {'from': 'OWASP Top 10:2021', 'to': owasp.EDITION,
                    'mapping': [f"{c['id']} {c['name']} ← {c['was_2021']}" for c in owasp.TOP10],
                    'source': owasp.SOURCE}
        elif action == 'quiz':
            data = owasp.quiz()
            data['how_to_ask'] = 'Read the question and the choices; wait for the user\'s answer before revealing it.'
        elif action == 'check_code':
            code = p.get('code') or ''
            if not code and p.get('file_path'):
                from core import paths
                path = paths.resolve(p['file_path'])
                if not path.is_file():
                    return outcome.failed('owasp_top10', f'File not found: {path}')
                code = path.read_text(errors='replace')[:400_000]
            if not str(code).strip():
                return outcome.ask('owasp_top10', 'Which file or code should I check?')
            return outcome.untrusted('owasp-code-check', json.dumps(owasp.check_code(code), ensure_ascii=False))
        else:
            raise ValueError('Use list, explain, checklist, changes, quiz or check_code.')
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        return outcome.failed('owasp_top10', str(exc)[:300])


TOOL = {
    'name': 'owasp_top10',
    'description': (
        'Local reference for the OWASP Top 10:2025 web-application risks (the current edition; categories were '
        'reordered from 2021, so use this instead of memory). list: all ten with one-line summaries. explain: one '
        'category by id ("A03") or topic ("SQL injection", "SSRF", "passwords") — what it is, examples, typical CWEs, '
        'prevention, how to test your own system. checklist: prevention checklist for a category. changes: 2025 vs '
        '2021 mapping. quiz: one practice question; wait for the user\'s answer before revealing it. check_code: flag '
        'lines in a file (file_path) or snippet (code) matching common Top 10 patterns — hints for review of the '
        'user\'s own code, not a verdict. For defence, learning and authorised testing.'
    ),
    'brief': 'OWASP Top 10:2025: explain, checklist, 2021 changes, quiz, code check.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['list', 'explain', 'checklist', 'changes', 'quiz', 'check_code']},
            'item': {'type': 'STRING', 'description': 'Category id (A01-A10) or topic, for explain/checklist.'},
            'file_path': {'type': 'STRING', 'description': 'File to check, for check_code.'},
            'code': {'type': 'STRING', 'description': 'Code snippet to check, for check_code.'},
        },
        'required': ['action'],
    },
    'handler': owasp_top10,
    'tier': 'core',
}
