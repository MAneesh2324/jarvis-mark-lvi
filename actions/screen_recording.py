import json
from core import outcome
from core.screen_workspace import workspace


def recording(parameters, player=None, **kwargs):
    action = str(parameters.get('action', 'status')).lower()
    try:
        if action == 'start':
            state = workspace.recorder.start(parameters.get('monitor', 1), parameters.get('fps', 8))
            return outcome.done('screen_recording', recording=True, frames=state['frames'], path=state['path'], audio_recorded=False)
        if action == 'stop':
            state = workspace.recorder.stop()
            if state['recording']:
                return outcome.unverified('screen_recording', 'Stop requested but the capture worker has not finished; the file is not verified yet.')
            if not state['saved']:
                return outcome.failed('screen_recording', state['error'] or 'No recorded file is available.')
            if state['error']:
                return outcome.unverified('screen_recording', 'A partial recording was saved, but capture failed: ' + state['error'], path=state['path'])
            return outcome.done('screen_recording', recording=False, path=state['path'], frames=state['frames'], saved=True)
        if action == 'permission':
            from core.screen_workspace import screen_permission_status
            state=screen_permission_status()
            if not state['granted'] and player is not None and hasattr(player,'request_screen_permission'):player.request_screen_permission()
            return json.dumps(state)
        if action == 'status':
            from core.screen_workspace import screen_permission_status
            return json.dumps({**workspace.recorder.status(),'permission':screen_permission_status()})
        return outcome.failed('screen_recording', 'Choose start, stop, status or permission.')
    except PermissionError as exc:
        if player is not None and hasattr(player,'request_screen_permission'):player.request_screen_permission()
        return outcome.failed('screen_recording',str(exc),permission_required=True)
    except Exception as exc:
        return outcome.failed('screen_recording', str(exc))


TOOL = {'name': 'screen_recording', 'description': 'Record the selected display to a local MP4 file when the user explicitly asks. Start, stop/finalize, or inspect status. Default monitor 1, 8 fps; microphone/system audio is not recorded. Recording and AI screen sharing are independent. On macOS the dedicated Desktop app requires access for Mark LVI, not Terminal or another Python version. permission opens the local setup dialog without granting access or starting capture; the user must approve macOS access. status reads actual permission. Do not repeatedly retry denied capture. A recording is only reported saved after stop verifies a nonempty file.',
        'parameters': {'type': 'OBJECT', 'properties': {'action': {'type': 'STRING', 'enum': ['start', 'stop', 'status', 'permission']}, 'monitor': {'type': 'INTEGER'}, 'fps': {'type': 'INTEGER'}}, 'required': ['action']},
        'handler': recording, 'tier': 'core'}
