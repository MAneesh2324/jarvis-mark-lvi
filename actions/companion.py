"""Voice tool: JARVIS's own feelings, the user's goals and wins, and focus sessions."""
import json

from core import outcome


def companion(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'status')
    try:
        from core import companion as co
        heart = co.instance()
        if action in ('status', 'feelings'):
            data = heart.status()
        elif action == 'focus_start':
            data = heart.focus_start(p.get('task') or 'deep work', p.get('minutes') or 25)
            return outcome.started('companion', **data,
                                   note='Focus session on. A countdown ring is on the face, notifications that can wait are '
                                        'held until it ends, and JARVIS will tell them when time is up. Keep replies short.')
        elif action == 'focus_stop':
            data = heart.focus_stop()
            return outcome.done('companion', **data)
        elif action == 'focus_status':
            data = {'focus': heart.focus_status(), **heart.focus_totals()}
        elif action == 'add_goal':
            if not p.get('goal'):
                raise ValueError('Say which goal to remember.')
            return outcome.done('companion', **heart.add_goal(p['goal']))
        elif action == 'remove_goal':
            return outcome.done('companion', **heart.remove_goal(p.get('goal') or ''))
        else:
            raise ValueError('Unknown companion action.')
        return outcome.untrusted('companion', json.dumps(data, ensure_ascii=False, default=str))
    except Exception as exc:
        return outcome.failed('companion', str(exc)[:300])


TOOL = {
    'name': 'companion',
    'description': (
        'JARVIS\'s heart: its own current feeling, and what it remembers to look after the user. '
        'feelings / status: how JARVIS feels right now and why, the user\'s goals, recent wins, things to follow up on, '
        'focus minutes today and the streak — use it when asked "how are you feeling", "what are my goals", "how much '
        'did I focus". focus_start: start a focus session (task, minutes; default 25) when the user wants to concentrate, '
        'is procrastinating, or says they cannot focus — a countdown ring shows on the face and non-urgent notifications '
        'wait. focus_stop: end it early. focus_status. add_goal / remove_goal (goal): goals JARVIS uses to motivate them.'
    ),
    'brief': 'JARVIS\'s feelings, the user\'s goals and wins, focus sessions.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['status', 'feelings', 'focus_start', 'focus_stop', 'focus_status',
                                                  'add_goal', 'remove_goal']},
            'task': {'type': 'STRING'},
            'minutes': {'type': 'INTEGER'},
            'goal': {'type': 'STRING'},
        },
        'required': ['action'],
    },
    'handler': companion,
    'tier': 'core',
}
