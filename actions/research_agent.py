"""Voice tool: start and follow background research agents."""
import json

from core import outcome


def research_agent(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'start')
    try:
        from core import research_agent as ra
        if action == 'start':
            data = ra.start(p.get('goal', ''), p.get('depth', 'standard'))
            return outcome.started('research_agent', **data,
                                   note='Working in the background; I will announce when the report is ready.')
        if action == 'status':
            data = ra.status(p.get('id', ''))
        elif action == 'result':
            data = ra.result(p['id'])
        elif action == 'cancel':
            data = ra.cancel(p['id'])
        else:
            raise ValueError('Unknown research_agent action.')
        return outcome.untrusted('research-agent', json.dumps(data, ensure_ascii=False, default=str))
    except Exception as exc:
        return outcome.failed('research_agent', str(exc)[:300])


TOOL = {
    'name': 'research_agent',
    'description': (
        'Background research agent for questions that need several sources: plans sub-questions, searches the web '
        '(and recent news when timely), reads the pages, cross-checks, and writes a cited Markdown report to '
        'Desktop/JARVIS Reports, then announces itself. Use for "research", "compare", "find out everything about", '
        '"make me a report"; answer simple factual questions directly instead. start: goal plus depth quick (1-2 min), '
        'standard (2-4 min) or deep (4-8 min); tell the user it is running and keep talking. status: progress of one '
        'or all jobs. result: the finished report text. cancel: stop a job. Never claim findings before result returns.'
    ),
    'brief': 'Background multi-source research with cited reports.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['start', 'status', 'result', 'cancel']},
            'goal': {'type': 'STRING', 'description': 'What to research, in the user\'s words plus any constraints'},
            'depth': {'type': 'STRING', 'enum': ['quick', 'standard', 'deep']},
            'id': {'type': 'STRING'},
        },
        'required': ['action'],
    },
    'handler': research_agent,
    'tier': 'core',
}
