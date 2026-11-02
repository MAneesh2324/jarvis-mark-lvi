"""Explicit speech turn-end presets, adjustable by voice."""
from core import outcome
from core.undo import push_undo
from memory import config_manager as cfg

PRESETS = {
    'natural': {'enabled': False, 'silence_ms': 700, 'prefix_ms': 150},
    'patient': {'enabled': True, 'silence_ms': 1200, 'prefix_ms': 250},
    'quick': {'enabled': True, 'silence_ms': 400, 'prefix_ms': 150},
}


def configure(parameters, **kwargs):
    preset = str(parameters.get('preset', 'status')).strip().lower()
    if preset == 'status':
        return str(cfg.get_turn_tuning()) + '. Presets: natural (server default), patient (longer pauses), quick (short pauses).'
    if preset not in PRESETS:
        return outcome.failed('voice_pacing', 'Choose natural, patient, quick, or status.')
    old = cfg.get_turn_tuning()
    from core.response_speed import get_profile,set_profile
    old_profile=get_profile()
    set_profile('standard')  # An explicit listening preference overrides Fast.
    cfg.save_turn_tuning(PRESETS[preset])
    push_undo('voice pacing → ' + preset, lambda: _restore(old,old_profile))
    return outcome.done('voice_pacing', preset=preset, saved=cfg.get_turn_tuning() == {**old, **PRESETS[preset]},
                        activation='next connection or app restart; current connection is unchanged',
                        note='Patient mode allows longer pauses. Quick mode can clip speech. These presets apply to Gemini Live; local engines use their own turn detector.')


def _restore(old,profile='standard'):
    from core.response_speed import set_profile
    set_profile(profile)
    cfg.save_turn_tuning(old)
    return 'Previous voice pacing restored; applies on the next connection.'


TOOL = {'name': 'voice_pacing', 'description': 'When explicitly asked, adjust Gemini Live listening patience: patient for pauses/cut-off speech, quick for short pauses, natural for server defaults, status to inspect. Saved settings apply on the next connection or restart, not immediately. Does not change the local pipeline turn detector. Changes support undo.',
        'parameters': {'type': 'OBJECT', 'properties': {'preset': {'type': 'STRING', 'enum': ['status', 'natural', 'patient', 'quick']}}, 'required': ['preset']},
        'handler': configure, 'tier': 'core'}
