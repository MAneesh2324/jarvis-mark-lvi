"""Voice tool: the private Telegram phone link."""
import json

from core import outcome


def phone_link(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'status')
    try:
        from core.phone_link import instance
        link = instance()
        if action == 'status':
            data = link.status()
        elif action == 'pair':
            data = link.begin_pairing()
        elif action == 'unpair':
            data = link.unpair()
        elif action == 'send':
            if not link.send(p.get('text', '')):
                return outcome.failed('phone_link', 'The phone is not paired yet, or the link is off.')
            return outcome.done('phone_link', sent=True)
        elif action == 'configure':
            data = link.configure(enabled=p.get('enabled'), alerts=p.get('alerts'),
                                  quiet_start=p.get('quiet_start'), quiet_end=p.get('quiet_end'))
        else:
            raise ValueError('Unknown phone_link action.')
        return outcome.untrusted('phone-link', json.dumps(data, ensure_ascii=False))
    except Exception as exc:
        return outcome.failed('phone_link', str(exc)[:300])


TOOL = {
    'name': 'phone_link',
    'description': (
        'Private Telegram link to the user\'s phone: they can message or send voice notes to JARVIS from anywhere, and '
        'JARVIS pushes its alerts there (finished research, security warnings, break reminders), with quiet hours. '
        'status: whether it is set up and paired. pair: start pairing and get the 6-digit code to read out (the user '
        'sends /pair CODE to their bot). Setup needs a bot token from @BotFather that the user TYPES into JARVIS as '
        '"/phonelink token <token>" — never ask them to say a token aloud. send: send the user\'s phone a message only '
        'when they ask. configure: enabled, alerts on/off, quiet_start/quiet_end hours. unpair: disconnect the phone.'
    ),
    'brief': 'Telegram phone link: remote chat, voice notes and alerts.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['status', 'pair', 'unpair', 'send', 'configure']},
            'text': {'type': 'STRING'},
            'enabled': {'type': 'BOOLEAN'},
            'alerts': {'type': 'BOOLEAN'},
            'quiet_start': {'type': 'INTEGER'},
            'quiet_end': {'type': 'INTEGER'},
        },
        'required': ['action'],
    },
    'handler': phone_link,
    'tier': 'extra',
}
