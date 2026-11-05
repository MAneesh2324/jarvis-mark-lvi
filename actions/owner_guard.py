"""Voice tool: owner face and voice recognition."""
import json

from core import outcome


def owner_guard(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'status')
    try:
        from core import owner_guard as og
        if action == 'status':
            data = og.status()
        elif action == 'enroll_face':
            data = og.enroll_face()
            return outcome.done('owner_guard', **data, note='Face learned. Only a numeric signature was stored.')
        elif action == 'check_face':
            data = og.check_face()
        elif action == 'enroll_voice':
            data = og.voice().start_enrolment(int(p.get('sentences') or 5))
            return outcome.started('owner_guard', **data)
        elif action == 'configure':
            data = og.configure(face_guard=p.get('face_guard'), voice_guard=p.get('voice_guard'),
                                check_minutes=p.get('check_minutes'), owner_name=p.get('owner_name'))
            return outcome.done('owner_guard', **data)
        elif action == 'forget':
            data = og.forget(p.get('what', 'all'))
            return outcome.done('owner_guard', **data)
        else:
            raise ValueError('Unknown owner_guard action.')
        return outcome.untrusted('owner-guard', json.dumps(data, ensure_ascii=False))
    except Exception as exc:
        return outcome.failed('owner_guard', str(exc)[:300])


TOOL = {
    'name': 'owner_guard',
    'description': (
        'Recognises the owner by face (webcam) and voice, locally. enroll_face: learn the owner\'s face now (ask them to '
        'face the camera alone, ~5 seconds). check_face: who is at the computer (owner, stranger, uncertain, no_face). '
        'enroll_voice: learn the owner\'s voice from their next spoken sentences (sentences, default 5). configure: '
        'face_guard (periodic camera checks that warn if someone else is at the computer), check_minutes, voice_guard '
        '(treat unrecognised voices as guests: sensitive actions are blocked until the owner confirms), owner_name. '
        'forget: delete face, voice or all signatures. status: what is enrolled and the last voice check. Only numeric '
        'signatures are stored, never photos or audio.'
    ),
    'brief': 'Owner face and voice recognition; guest protection.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['status', 'enroll_face', 'check_face', 'enroll_voice', 'configure', 'forget']},
            'sentences': {'type': 'INTEGER'},
            'face_guard': {'type': 'BOOLEAN'},
            'voice_guard': {'type': 'BOOLEAN'},
            'check_minutes': {'type': 'INTEGER'},
            'owner_name': {'type': 'STRING'},
            'what': {'type': 'STRING', 'enum': ['face', 'voice', 'all']},
        },
        'required': ['action'],
    },
    'handler': owner_guard,
    'tier': 'extra',
}
