"""Voice-accessible, non-recording audio diagnostics."""
import json
from core import outcome


def diagnose(parameters, **kwargs):
    import sounddevice as sd
    from memory import config_manager as cfg
    checks = []
    devices = [dict(d) for d in sd.query_devices()]
    defaults = list(sd.default.device)
    for kind, rate, saved in [('input', 16000, cfg.get_input_device()), ('output', 24000, cfg.get_output_device())]:
        candidates = [i for i, d in enumerate(devices) if d['max_' + kind + '_channels'] > 0 and (not saved or d['name'] == saved)]
        idx = candidates[0] if saved and candidates else defaults[0 if kind == 'input' else 1]
        result = {'kind': kind, 'saved': saved or 'System default', 'sample_rate': rate}
        if saved and not candidates:
            result.update(ok=False, issue='Saved device is disconnected or renamed; choose an available device in Audio Devices.')
        elif idx is None or idx < 0 or idx >= len(devices):
            result.update(ok=False, issue='No default device. Check System Settings → Sound and connect a microphone or speaker.')
        else:
            result['device'] = devices[idx]['name']
            try:
                getattr(sd, 'check_' + kind + '_settings')(device=idx, channels=1, dtype='int16', samplerate=rate)
                result.update(ok=True, note='Format supported; actual audibility and microphone permission still need the UI TEST button.')
            except Exception as exc:
                result.update(ok=False, issue=str(exc))
        checks.append(result)
    report = {'checks': checks, 'voice': cfg.get_voice(), 'push_to_talk': cfg.get_push_to_talk_enabled(),
              'wake_word': cfg.get_wake_word_enabled(), 'turn_tuning': cfg.get_turn_tuning(),
              'available_devices': [{'name': d['name'], 'input': d['max_input_channels'] > 0, 'output': d['max_output_channels'] > 0} for d in devices],
              'help': 'If replies are clipped, try headphones and disable aggressive turn tuning. On macOS, check Microphone permission for Mark LVI when using the Desktop app. This check does not record audio or play a sound.'}
    return outcome.untrusted('audio-diagnostics', json.dumps(report, ensure_ascii=False))


TOOL = {'name': 'voice_diagnostics', 'description': 'Diagnose why you cannot hear the user or why voice replies are silent. Lists microphones and speakers, saved devices, sample-rate support, voice, push-to-talk and wake-word settings. Does not record audio or play sound. Report supported formats separately from actual microphone audibility.',
        'parameters': {'type': 'OBJECT', 'properties': {}}, 'handler': diagnose, 'tier': 'core'}
