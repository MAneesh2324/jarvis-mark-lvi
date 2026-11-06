"""Voice tool: play an animated expression on JARVIS's face. Non-blocking: speech never waits for it."""
from core import outcome

EXPRESSIONS = ['nod', 'shake', 'brow_flash', 'smile', 'laugh', 'wink', 'surprise', 'sigh', 'think', 'tilt']


def face_expression(parameters, player=None, **kwargs):
    name = str((parameters or {}).get('expression') or '').lower()
    if name not in EXPRESSIONS:
        return outcome.failed('face_expression', 'Expression must be one of: ' + ', '.join(EXPRESSIONS))
    if player is None or not hasattr(player, 'express') or not player.express(name):
        return outcome.failed('face_expression', 'The face is not showing right now.')
    return outcome.done('face_expression', expression=name)


TOOL = {
    'name': 'face_expression',
    'description': ('Play an animated expression on your own face: nod, shake, brow_flash, smile, laugh, wink, surprise, '
                    'sigh, think, tilt. Only when the user asks you to make an expression ("smile", "wink at me"). '
                    'Your face already reacts to the conversation by itself, so never call this on your own. Keep '
                    'talking while it plays; do not mention the result.'),
    'brief': 'Make a face expression when asked.',
    'parameters': {'type': 'OBJECT', 'properties': {'expression': {'type': 'STRING', 'enum': EXPRESSIONS}},
                   'required': ['expression']},
    'handler': face_expression,
    'behavior': 'NON_BLOCKING',
    'scheduling': 'SILENT',
    'tier': 'core',
}
