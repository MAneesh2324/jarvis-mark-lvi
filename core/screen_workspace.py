"""Opt-in screen recording and co-pilot state. No capture at import or startup."""
from pathlib import Path
import atexit
import os
import platform
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / 'recordings'


SCREEN_SETTINGS_URL='x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'

def screen_permission_status():
    result={'platform':platform.system(),'required':platform.system()=='Darwin','granted':True,'app_name':'JARVIS','bundle_id':'','settings_url':SCREEN_SETTINGS_URL}
    if result['required']:
        import Quartz
        import Foundation
        bundle=Foundation.NSBundle.mainBundle();info=bundle.infoDictionary() or {}
        result.update(granted=bool(Quartz.CGPreflightScreenCaptureAccess()),app_name=str(info.get('CFBundleDisplayName') or info.get('CFBundleName') or 'the app that launched JARVIS'),bundle_id=str(bundle.bundleIdentifier() or ''))
    return result

def permission_instructions(state=None):
    state=state or screen_permission_status()
    if state.get('bundle_id')=='com.maneesh.marklvi':
        host='Mark LVI';addition='If Mark LVI is missing, click + and add '+str(ROOT.parent/'Mark LVI.app')+'. '
    else:
        host=state['app_name'];addition='For the Desktop installation, launch Mark LVI.app and grant access to Mark LVI. '
    return ('macOS reports Screen Recording access is not granted to '+host+'. Open System Settings → Privacy & Security → Screen & System Audio Recording. '+addition+'Enable that app, then fully quit and reopen Mark LVI. If the switch is already on but this check still fails, turn that app’s Screen & System Audio Recording switch off and back on, authenticate if asked, then quit and reopen Mark LVI. If it still fails, remove only Mark LVI from that list and add the current Desktop app again. Audio-only access does not grant screen access. Granting Terminal or a different Python version does not grant Mark LVI access.')

def request_screen_permission():
    # Called only by the local permission dialog's explicit button on the GUI thread.
    if threading.current_thread() is not threading.main_thread():raise RuntimeError('Request screen permission from the JARVIS permission dialog, not a capture worker.')
    state=screen_permission_status()
    if state['required'] and not state['granted']:
        import Quartz
        Quartz.CGRequestScreenCaptureAccess()
    return screen_permission_status()

def require_screen_permission():
    state=screen_permission_status()
    if not state['granted']:raise PermissionError(permission_instructions(state))


class ScreenRecorder:
    def __init__(self):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._path = None
        self._frames = 0
        self._error = ''
        self._started = 0
        self._fps = 8
        self._notes = None
        self._notes_error = ''
        self._permission_required = False
        self._audio_mode = 'none'
        self._audio_recorded = False
        self._finalizing = False
        self._echo_reduced = False

    def status(self):
        with self._lock:
            active = bool(self._thread and self._thread.is_alive())
            return {'recording': active, 'frames': self._frames, 'path': str(self._path or ''),
                    'error': self._error, 'fps': self._fps,
                    'elapsed_seconds': round(time.monotonic() - self._started, 1) if active else 0,
                    'audio_recorded': self._audio_recorded, 'audio_source': self._audio_mode, 'finalizing': self._finalizing, 'echo_reduced': self._echo_reduced, 'notes_error':self._notes_error,'permission_required':self._permission_required}

    def start(self, monitor=1, fps=8, audio="none"):
        if audio not in ("none", "system", "both"):raise ValueError("Audio must be both, system or none.")
        if audio != "none" and platform.system() != "Darwin":raise RuntimeError("System audio currently requires macOS.")
        try:require_screen_permission()
        except PermissionError as exc:
            with self._lock:self._error=str(exc);self._permission_required=True
            raise
        self._permission_required=False
        monitor, fps = int(monitor), int(fps)
        if monitor < 1 or not 1 <= fps <= 15:
            raise ValueError('Use monitor 1 or higher and a frame rate from 1 to 15.')
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError('A recording is already running. Stop it before starting another.')
            RECORDINGS.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._path = RECORDINGS / (time.strftime('screen-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.mp4')
            self._frames, self._error = 0, ''
            self._notes, self._notes_error = None, ''
            self._fps, self._started = fps, time.monotonic()
            self._audio_mode, self._audio_recorded = audio, False
            self._finalizing, self._echo_reduced = False, False
            self._stop = threading.Event()
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._record, args=(monitor, fps), daemon=True, name='screen-recorder')
            self._thread.start()
        if not self._ready.wait(15):
            self._stop.set()
            raise RuntimeError('Screen capture did not start in time. Check screen permissions.')
        state = self.status()
        if state['error'] or (not state['frames'] and self._audio_mode == 'none'):
            raise RuntimeError(state['error'] or 'No screen frames could be recorded.')
        return state

    def _record(self, monitor, fps):
        writer = None
        try:
            if self._audio_mode in ("system", "both"):
                from core.native_screen_recording import record
                record(self, monitor, fps)
                return
            import cv2
            import mss
            import numpy as np
            with mss.mss() as capture:
                if monitor >= len(capture.monitors):
                    raise ValueError('That display does not exist. Use monitor 1 for the primary display.')
                target = capture.monitors[monitor]
                scale = min(1, 1600 / target['width'], 1000 / target['height'])
                size = (max(2, int(target['width'] * scale) // 2 * 2), max(2, int(target['height'] * scale) // 2 * 2))
                writer = cv2.VideoWriter(str(self._path), cv2.VideoWriter_fourcc(*'mp4v'), fps, size)
                if not writer.isOpened():
                    raise RuntimeError('The MP4 encoder could not open the recording file.')
                os.chmod(self._path, 0o600)
                try:
                    from core.recording_notes import RecordingNotes
                    self._notes = RecordingNotes(self._path)
                except Exception as exc:
                    self._notes_error = str(exc)
                next_frame = time.monotonic()
                while not self._stop.is_set():
                    frame = np.asarray(capture.grab(target))[:, :, :3]
                    if self._stop.is_set():
                        break
                    frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                    writer.write(frame)
                    with self._lock:
                        self._frames += 1
                    self._ready.set()
                    if self._notes is not None:
                        try:self._notes.sample(frame,(self._frames-1)/fps)
                        except Exception as exc:self._notes_error=str(exc)
                    next_frame += 1 / fps
                    delay = next_frame - time.monotonic()
                    if delay < -1 / fps:
                        next_frame = time.monotonic()
                    self._stop.wait(max(0, delay))
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            if writer is not None:
                writer.release()
            self._ready.set()

    def mark(self,note):
        note=str(note).strip()
        if not note:raise ValueError('Give the marker a short note.')
        state=self.status()
        if not state['recording'] or self._notes is None:raise RuntimeError('Start a recording with keyframe notes first.')
        seconds=self._frames/self._fps
        self._notes.mark(seconds,note)
        return {'seconds':round(seconds,2),'note':note[:1000]}

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread:
            thread.join(timeout=25)
        state = self.status()
        path = Path(state['path']) if state['path'] else None
        state['saved'] = bool(not state['recording'] and state['frames'] and path and path.exists() and path.stat().st_size > 0)
        return state


class ScreenWorkspace:
    def __init__(self):
        self.recorder = ScreenRecorder()
        self._lock = threading.RLock()
        self.watch = False
        self.focus = 'Help me understand my current work and suggest one useful next step.'
        self.interval = 30
        self.generation = 0
        self.requested = False
        self.last_error = ''
        self.frames_sent = 0
        self.analysis_active = False
        self.request_mode = 'analyze'
        self.request_args = {}
        self.request_focus = ''

    def status(self):
        with self._lock:
            return {'watching': self.watch, 'focus': self.focus, 'interval_seconds': self.interval,
                    'generation': self.generation, 'analysis_requested': self.requested, 'request_mode': self.request_mode, 'request_args':dict(self.request_args), 'request_focus':self.request_focus,
                    'frames_shared': self.frames_sent, 'analysis_active': self.analysis_active, 'error': self.last_error, 'recorder': self.recorder.status()}

    def control(self, action, focus='', interval=30):
        if action in ('watch', 'analyze'):
            require_screen_permission()
        validated_interval = max(15, min(300, int(interval))) if action == 'watch' else 30
        with self._lock:
            if action == 'watch':
                self.watch = True
                self.interval = validated_interval
                self.generation += 1
            elif action == 'stop':
                self.watch = False
                self.requested = False
                self.analysis_active = False
                self.generation += 1
            elif action == 'analyze':
                self.requested = True
                self.request_mode = 'analyze'
                self.request_args = {}
                self.request_focus = str(focus or self.focus)[:600]
            elif action != 'status':
                raise ValueError('Choose watch, stop, analyze or status.')
            if focus:
                self.focus = str(focus)[:600]
            self.last_error = ''
        return self.status()

    def request_job(self,mode,focus='',args=None):
        if mode not in ('diagnose','check','highlights'):raise ValueError('Unknown screen job.')
        if mode!='highlights':require_screen_permission()
        with self._lock:
            if self.requested or self.analysis_active:raise RuntimeError('Another screen job is pending. Wait for it to finish.')
            self.requested=True
            self.request_mode=mode
            self.request_args=dict(args or {})
            self.request_focus=str(focus or '')[:600]
            self.last_error=''
        return self.status()

    def take_request(self):
        with self._lock:
            value = self.requested
            self.requested = False
            return value

    def pending(self, active=True):
        with self._lock:
            self.analysis_active = bool(active)

    def sent(self):
        with self._lock:
            self.frames_sent += 1

    def fail(self, reason):
        with self._lock:
            self.last_error = str(reason)
            self.analysis_active = False
            self.watch = False
            self.requested = False
            self.generation += 1


workspace = ScreenWorkspace()
atexit.register(workspace.recorder.stop)


def frame_fingerprint(image_bytes):
    import io
    import numpy as np
    from PIL import Image
    with Image.open(io.BytesIO(image_bytes)) as image:
        return np.asarray(image.convert('L').resize((48, 27)), dtype=np.float32)


def screen_changed(previous, current, threshold=5.0):
    import numpy as np
    return previous is None or float(np.abs(current - previous).mean()) >= threshold
