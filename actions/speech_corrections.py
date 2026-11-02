"""Names and phrases the user explicitly corrects, persisted locally."""
import json
from core import outcome
from core.undo import push_undo
from memory import conversation_journal as journal


def correct(parameters, **kwargs):
    action = str(parameters.get('action', 'list')).strip().lower()
    if action == 'list':
        return outcome.untrusted('speech-dictionary', json.dumps(journal.corrections(), ensure_ascii=False))
    if action not in ('add', 'remove'):
        return outcome.failed('speech_corrections', 'Choose list, add or remove.')
    heard = str(parameters.get('heard', '')).strip().casefold()
    intended = str(parameters.get('intended', '')).strip()
    if not heard or (action == 'add' and not intended):
        return outcome.failed('speech_corrections', 'An explicit heard phrase and intended phrase are required to add a correction.')
    before = journal.corrections().get(heard)
    expected = intended if action == 'add' else None
    try:
        journal.set_correction(heard, expected)
    except ValueError as exc:
        return outcome.failed('speech_corrections', str(exc))
    def undo():
        if journal.corrections().get(heard) != expected:
            return 'Dictionary entry changed again; undo preserved the newer correction.'
        journal.set_correction(heard, before)
        return 'Speech correction restored.'
    push_undo('speech correction ' + heard, undo)
    return outcome.done('speech_corrections', heard=heard, intended=expected or 'removed',
                        note='Use the intended name in the current conversation. Future connections load this hint automatically. Speech recognition accuracy is not guaranteed; ask when ambiguous.')


TOOL = {'name': 'speech_corrections', 'description': 'Remember an explicit user correction such as "when you hear Navy, I mean Nivi". Add the heard phrase and intended phrase, list corrections, or remove one. This is a persistent interpretation dictionary, not audio-model training. Apply the explicit correction to the current conversation; future sessions load it automatically. Do not infer mappings from unrelated history. Supports undo.',
        'parameters': {'type': 'OBJECT', 'properties': {'action': {'type': 'STRING', 'enum': ['list', 'add', 'remove']}, 'heard': {'type': 'STRING'}, 'intended': {'type': 'STRING'}}, 'required': ['action']},
        'handler': correct, 'tier': 'core'}
