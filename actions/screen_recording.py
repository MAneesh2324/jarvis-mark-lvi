import json
import platform
from core import outcome
from core.screen_workspace import workspace


def recording(parameters, player=None, **kwargs):
    action = str(parameters.get('action', 'status')).lower()
    try:
        if action == 'start':
            state = workspace.recorder.start(parameters.get('monitor', 1), parameters.get('fps', 8), audio=parameters.get('audio', 'both' if platform.system() == 'Darwin' else 'none'))
            return outcome.done('screen_recording', recording=True, frames=state['frames'], path=state['path'], audio_recorded=state['audio_recorded'], audio_source=state['audio_source'], audio_enabled=state['audio_source'] in ('system','both'), microphone_enabled=state['audio_source']=='both')
        if action == 'stop':
            state = workspace.recorder.stop()
            if state['recording']:
                return outcome.unverified('screen_recording', 'Capture stop requested; the file is still finalizing, including local microphone echo reduction. Use status to check completion; do not start a new recording yet.')
            if not state['saved']:
                return outcome.failed('screen_recording', state['error'] or 'No recorded file is available.')
            if state['error']:
                return outcome.unverified('screen_recording', 'A partial recording was saved, but capture failed: ' + state['error'], path=state['path'])
            return outcome.done('screen_recording', recording=False, path=state['path'], frames=state['frames'], saved=True, echo_reduced=state.get('echo_reduced',False), audio_recorded=state['audio_recorded'], audio_source=state['audio_source'])
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


TOOL = {'name': 'screen_recording', 'description': 'Record the selected display to a local MP4 file when the user explicitly asks. Start, stop/finalize, or inspect status. Default monitor 1, 8 fps; macOS captures system audio AND microphone together by default (audio=both), including JARVIS playback and the user speaking. audio=system excludes the microphone. Set audio=none for silent video. audio_enabled=true on start means sound capture is enabled; audio_recorded=false while recording only means the saved track is not verified yet, not silent recording. Microphone echo reduction runs locally when stopped; finalizing may take time. Audio track is verified after stopping. Recording and AI screen sharing are independent. On macOS the dedicated Desktop app requires access for Mark LVI, not Terminal or another Python version. permission opens the local setup dialog without granting access or starting capture; the user must approve macOS access. status reads actual permission. Do not repeatedly retry denied capture. A recording is only reported saved after stop verifies a nonempty file.',
        'parameters': {'type': 'OBJECT', 'properties': {'action': {'type': 'STRING', 'enum': ['start', 'stop', 'status', 'permission']}, 'monitor': {'type': 'INTEGER'}, 'fps': {'type': 'INTEGER'}, 'audio': {'type': 'STRING', 'enum': ['both', 'system', 'none']}}, 'required': ['action']},
        'handler': recording, 'tier': 'core'}
