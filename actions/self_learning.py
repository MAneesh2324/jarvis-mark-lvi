"""Voice tool: JARVIS's self-learning — its rule book, progress report and teaching."""
import json

from core import outcome


def self_learning(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'report')
    try:
        from core import self_learning as sl
        if action == 'report':
            data = sl.report(int(p.get('days') or 7))
        elif action == 'status':
            data = sl.status()
        elif action == 'rules':
            data = sl.rules(bool(p.get('include_retired')))
        elif action == 'teach':
            return outcome.done('self_learning', **sl.teach(p.get('rule', ''), p.get('category', 'preference')))
        elif action == 'remove':
            return outcome.done('self_learning', **sl.remove(p['rule_id']))
        elif action == 'review_now':
            data = sl.review(force=True)
        else:
            raise ValueError('Unknown self_learning action.')
        return outcome.untrusted('self-learning', json.dumps(data, ensure_ascii=False, default=str))
    except Exception as exc:
        return outcome.failed('self_learning', str(exc)[:300])


TOOL = {
    'name': 'self_learning',
    'description': (
        'JARVIS improves itself: it records how each exchange went (tool failures, slow tools, user corrections, repeats, '
        'interruptions), reviews its mistakes every few hours and writes itself rules about routing, efficiency, the '
        'user\'s style and names, which load at every session start. report: progress over the last days (first-time '
        'success, corrections, failures, slow tools, rules learned) — use for "are you getting better?". rules: the '
        'current rule book with evidence. teach: save a rule the user states ("always answer in short", "my charts '
        'means TradingView"). remove: delete a rule by id when the user asks. review_now: reflect immediately. '
        'status: counts and the last lesson. Rules never loosen safety or confirmation.'
    ),
    'brief': 'Self-improvement: learned rules, teaching, progress report.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['report', 'status', 'rules', 'teach', 'remove', 'review_now']},
            'rule': {'type': 'STRING'},
            'category': {'type': 'STRING', 'enum': ['routing', 'efficiency', 'style', 'naming', 'preference', 'accuracy']},
            'rule_id': {'type': 'INTEGER'},
            'days': {'type': 'INTEGER'},
            'include_retired': {'type': 'BOOLEAN'},
        },
        'required': ['action'],
    },
    'handler': self_learning,
    'tier': 'core',
}
