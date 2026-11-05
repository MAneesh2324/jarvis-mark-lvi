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
        elif action == 'set_token':
            try:
                data = link.set_token(p.get('token', ''))
            except Exception as exc:
                return outcome.failed('phone_link', f'Telegram rejected that token ({str(exc)[:80]}). Spoken tokens are '
                                      'often misheard: ask the user to paste it into the JARVIS text box instead — it is '
                                      'detected automatically and never shown.')
            data['say'] = f"Linked. On your phone, open {data['bot']} in Telegram and send: /pair {data['pair_code']}"
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
        'status: whether it is set up and paired. set_token: when the user gives a bot token (from @BotFather), pass it '
        'exactly; it is checked with Telegram, then read out the 6-digit /pair code they must send to their bot. Best is '
        'for the user to PASTE the token into the JARVIS text box (handled automatically, never shown); never ask them '
        'to read a token aloud. pair: a new 6-digit code. send: send the user\'s phone a message only '
        'when they ask. configure: enabled, alerts on/off, quiet_start/quiet_end hours. unpair: disconnect the phone.'
    ),
    'brief': 'Telegram phone link: remote chat, voice notes and alerts.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['status', 'set_token', 'pair', 'unpair', 'send', 'configure']},
            'token': {'type': 'STRING', 'description': 'Telegram bot token from @BotFather'},
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
