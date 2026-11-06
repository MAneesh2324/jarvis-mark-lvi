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
        elif action == 'send_screenshot':
            from core import remote_armour
            if not link.send_photo(remote_armour.screenshot(), p.get('text') or '🖥 Screen from JARVIS'):
                return outcome.failed('phone_link', 'The phone is not paired yet, or the link is off.')
            return outcome.done('phone_link', sent='screenshot')
        elif action == 'send_file':
            path = p.get('path', '')
            if not path and p.get('query'):
                from core.remote_armour import find_files
                found = find_files(p['query'], limit=5)
                if len(found) != 1:
                    return outcome.untrusted('phone-link', json.dumps(
                        {'sent': False, 'needs_choice': True, 'matches': found,
                         'say': 'Several or no files matched; ask which one, then call again with its path.'},
                        ensure_ascii=False))
                path = found[0]['path']
            if not link.send_document(path, p.get('text') or ''):
                return outcome.failed('phone_link', 'The phone is not paired yet, or the link is off.')
            return outcome.done('phone_link', sent=path)
        elif action == 'configure':
            data = link.configure(enabled=p.get('enabled'), alerts=p.get('alerts'), remote=p.get('remote'),
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
        'when they ask. send_screenshot: send the current screen to the phone. send_file: send a file from this Mac '
        'to the phone ("send me my resume"): pass path, or query to search by name (if several match, ask which). '
        'Keys, credentials and app data are never sent. configure: enabled, alerts on/off, remote on/off (the '
        'virtual-armour remote commands the phone can run: /screen /cam /file /clip /lock /sys /home; the phone can '
        'only turn them OFF, turning them back ON happens here), quiet_start/quiet_end hours. unpair: disconnect the '
        'phone.'
    ),
    'brief': 'Telegram phone link: remote chat, voice notes, alerts, send files/screenshots, remote commands.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['status', 'set_token', 'pair', 'unpair', 'send', 'send_screenshot',
                                                  'send_file', 'configure']},
            'path': {'type': 'STRING', 'description': 'File to send (send_file)'},
            'query': {'type': 'STRING', 'description': 'File name words to search for (send_file)'},
            'remote': {'type': 'BOOLEAN', 'description': 'Allow remote commands from the phone (configure)'},
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
