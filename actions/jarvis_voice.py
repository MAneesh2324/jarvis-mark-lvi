"""Voice tool: mute or unmute JARVIS's own voice (it keeps listening; replies show as text)."""
from core import outcome


def jarvis_voice(parameters, player=None, **kwargs):
    action = str((parameters or {}).get('action') or 'status').lower()
    if player is None or not hasattr(player, 'set_voice_muted'):
        return outcome.failed('jarvis_voice', 'The voice switch needs the desktop window.')
    if action == 'status':
        return outcome.done('jarvis_voice', voice_muted=bool(player.voice_muted))
    if action not in ('mute', 'unmute'):
        return outcome.failed('jarvis_voice', 'Choose mute, unmute or status.')
    player.set_voice_muted(action == 'mute')
    return outcome.done('jarvis_voice', voice_muted=action == 'mute',
                        note=('Muted: your replies now appear as text in the activity log; keep them brief. '
                              'You still hear the user.') if action == 'mute' else 'Your voice is back on.')


TOOL = {
    'name': 'jarvis_voice',
    'description': ('Mute or unmute your own voice. mute when the user says "mute yourself", "be quiet", "stop talking '
                    'out loud" or "text only": you keep listening and working and replies appear as text. unmute when '
                    'they want to hear you again. This is not the microphone (the user mutes that with the mic button '
                    'or F4). status: whether your voice is muted.'),
    'brief': 'Mute or unmute JARVIS\'s voice.',
    'parameters': {'type': 'OBJECT', 'properties': {'action': {'type': 'STRING', 'enum': ['mute', 'unmute', 'status']}},
                   'required': ['action']},
    'handler': jarvis_voice,
    'tier': 'core',
}
