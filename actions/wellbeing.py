"""Voice tool: how the user seems, and the break / late-night reminders."""
import json

from core import outcome


def wellbeing(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'status')
    try:
        from core import wellbeing as wb
        if action == 'status':
            data = wb.instance().status()
        elif action == 'configure':
            data = wb.configure(enabled=p.get('enabled'), voice_mood=p.get('voice_mood'),
                                break_after_minutes=p.get('break_after_minutes'))
            return outcome.done('wellbeing', **data)
        elif action == 'reset_voice_baseline':
            inst = wb.instance()
            inst.baseline = wb.Baseline(); inst.baseline.data = {'n': 0, 'stats': {f: [0.0, 0.0] for f in wb.FEATURES}}
            inst.baseline.save()
            return outcome.done('wellbeing', reset=True, note='Relearning your usual voice over the next few sentences.')
        else:
            raise ValueError('Unknown wellbeing action.')
        return outcome.untrusted('wellbeing', json.dumps(data, ensure_ascii=False))
    except Exception as exc:
        return outcome.failed('wellbeing', str(exc)[:300])


TOOL = {
    'name': 'wellbeing',
    'description': (
        'JARVIS reads the user\'s tone (loudness, pitch and pace against their own usual voice, plus their words) and '
        'reminds them to take breaks after long sessions and late at night. status: current estimated mood, reasons and '
        'session length — use when they ask how they sound or how long they have been working. configure: enable/disable, '
        'voice_mood on/off, break_after_minutes (0 = off). reset_voice_baseline: relearn their usual voice. Treat the mood '
        'as a gentle estimate, never a diagnosis.'
    ),
    'brief': 'Tone-aware replies and break reminders.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['status', 'configure', 'reset_voice_baseline']},
            'enabled': {'type': 'BOOLEAN'},
            'voice_mood': {'type': 'BOOLEAN'},
            'break_after_minutes': {'type': 'INTEGER'},
        },
        'required': ['action'],
    },
    'handler': wellbeing,
    'tier': 'extra',
}
