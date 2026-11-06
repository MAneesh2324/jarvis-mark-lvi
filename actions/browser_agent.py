"""browser_agent tool (declaration shared in actions/mac_tools.py).

The handler lives here rather than in mac_tools so the tool can be forgiving
about the words a model uses, and honest about what a reply turned into:

  * "reply"/"update"/"answer"/"continue" with nothing waiting used to fail with
    "No browser task is waiting for you." and the user's instruction was lost.
    Now an instruction becomes a new task, reported as `started` (it is under
    way, not done).
  * "start" while a task runs replaces the old task (core/browser_agent.start
    cancels it and reports replaced_task=<id>) instead of refusing.
"""
from actions.mac_tools import TOOLS, _out
from core import outcome

_ALIASES = {
    'start': 'start', 'new': 'start', 'run': 'start', 'begin': 'start', 'go': 'start', 'task': 'start',
    'reply': 'reply', 'update': 'reply', 'answer': 'reply', 'continue': 'reply', 'respond': 'reply',
    'approve': 'reply', 'change': 'reply', 'correct': 'reply',
    'status': 'status', 'progress': 'status', 'check': 'status',
    'stop': 'stop', 'cancel': 'stop', 'abort': 'stop', 'quit': 'stop',
}


def browser_agent(parameters, **kwargs):
    p = dict(parameters or {})
    raw = str(p.get('action') or 'start').lower().strip()
    action = _ALIASES.get(raw, raw)
    try:
        from core import browser_agent as ba
        if action == 'start':
            return outcome.started('browser_agent', **ba.start(p.get('goal') or p.get('text', '')))
        if action == 'status':
            return _out('browser-agent', ba.status(p.get('id', '')))
        if action == 'reply':
            approve = bool(p.get('approve')) or raw == 'approve'
            res = ba.reply(p.get('id', ''), approve, p.get('text') or p.get('goal', ''))
            if res.get('started_new_task'):
                return outcome.started('browser_agent', **res)
            return outcome.done('browser_agent', **res)
        if action == 'stop':
            return outcome.done('browser_agent', **ba.stop(p.get('id', '')))
        raise ValueError(f"Unknown browser_agent action '{raw}' - use start, status, reply or stop.")
    except Exception as exc:
        return outcome.failed('browser_agent', str(exc)[:300])


TOOL = dict(
    TOOLS[3],
    handler=browser_agent,
    description=TOOLS[3]['description'] + (
        ' The newest request always wins: start while a task runs cancels the old one (replaced_task=its id). '
        'reply with an instruction when nothing is waiting starts it as a new task (status=started).'),
)
