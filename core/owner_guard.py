"""Owner recognition: JARVIS knows your face and your voice.

Face  — OpenCV YuNet finds faces, SFace turns a face into a 128-number signature.
        Enrolment takes a dozen webcam frames of the owner; a check takes a few
        frames and compares signatures. Used to greet the owner, and (when the guard
        is on) to warn if someone else is at the computer.
Voice — the WeSpeaker ResNet34 model turns a few seconds of speech into a voice
        signature. Enrolment learns from the owner's next few sentences; after that,
        every spoken turn is checked. If a different voice gives commands, JARVIS is
        told privately to treat it as a guest (no sending, buying, deleting or private
        information without the owner) and the owner is alerted.

Everything runs on this Mac. Only the signatures are stored (memory/owner/, git-ignored,
owner-only file permissions), never photos or recordings. The camera is used only for
enrolment and checks, and never while another camera feature holds it.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
MODELS = BASE / 'models' / 'owner'
STORE = BASE / 'memory' / 'owner'
CONFIG = BASE / 'config' / 'owner-guard.json'
DEFAULTS = {'face_guard': False, 'check_minutes': 10, 'voice_guard': True, 'owner_name': ''}
FACE_MATCH, FACE_STRANGER = 0.42, 0.28        # SFace cosine: OpenCV's published same-person threshold is 0.363
VOICE_MATCH, VOICE_STRANGER = 0.55, 0.35      # WeSpeaker cosine


def settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def configure(**changes) -> dict:
    from core.mission_store import write_file
    cur = settings()
    for k in ('face_guard', 'voice_guard'):
        if changes.get(k) is not None:
            cur[k] = bool(changes[k])
    if changes.get('check_minutes') is not None:
        cur['check_minutes'] = max(2, min(int(changes['check_minutes']), 120))
    if changes.get('owner_name'):
        cur['owner_name'] = str(changes['owner_name'])[:40]
    CONFIG.parent.mkdir(exist_ok=True)
    write_file(CONFIG, json.dumps(cur))
    return cur


def _save_vec(name, arr):
    STORE.mkdir(parents=True, exist_ok=True)
    path = STORE / name
    np.save(path, arr.astype(np.float32))
    os.chmod(str(path) if str(path).endswith('.npy') else str(path) + '.npy', 0o600)


def _load_vec(name):
    p = STORE / name
    return np.load(p) if p.exists() else None


def _cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# ── face ────────────────────────────────────────────────────────────────────

class Face:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(str(MODELS / 'yunet.onnx'), '', (320, 320), 0.8, 0.3, 50)
        self.rec = cv2.FaceRecognizerSF.create(str(MODELS / 'sface.onnx'), '')

    def faces(self, img):
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, found = self.det.detect(img)
        return [] if found is None else sorted(found, key=lambda f: -f[2] * f[3])

    def embed(self, img, face):
        aligned = self.rec.alignCrop(img, face)
        return self.rec.feature(aligned).ravel()

    def frames(self, count=6, gap=0.25):
        """Grab frames from the webcam, holding the shared camera lock for the shortest time."""
        from core import camera_access
        from actions.screen_processor import _load_config, _cv2_backend
        out = []
        with camera_access.claim('owner recognition'):
            cap = self.cv2.VideoCapture(int(_load_config().get('camera_index', 0)), _cv2_backend())
            try:
                if not cap.isOpened():
                    raise RuntimeError('The camera could not be opened (check camera permission for Mark LVI).')
                for _ in range(5):        # let exposure settle
                    cap.read()
                for _ in range(count):
                    ok, img = cap.read()
                    if ok and img is not None:
                        out.append(img)
                    time.sleep(gap)
            finally:
                cap.release()
        return out


_face: Face | None = None


def _face_engine() -> Face:
    global _face
    if _face is None:
        _face = Face()
    return _face


def enroll_face(samples: int = 14) -> dict:
    eng = _face_engine()
    embs = []
    for img in eng.frames(samples, 0.3):
        found = eng.faces(img)
        if len(found) == 1:
            embs.append(eng.embed(img, found[0]))
    if len(embs) < 5:
        raise RuntimeError(f'Only {len(embs)} clear single-face frames. Sit facing the camera, alone, in good light, and retry.')
    embs = np.array(embs)
    _save_vec('face.npy', embs)
    spread = float(np.mean([_cos(e, embs.mean(0)) for e in embs]))
    return {'enrolled': True, 'frames_used': len(embs), 'consistency': round(spread, 3)}


def check_face(frames: int = 4) -> dict:
    owner = _load_vec('face.npy')
    if owner is None:
        return {'result': 'not_enrolled'}
    eng = _face_engine()
    best, people = -1.0, 0
    for img in eng.frames(frames, 0.2):
        found = eng.faces(img)
        people = max(people, len(found))
        for f in found[:3]:
            e = eng.embed(img, f)
            best = max(best, max(_cos(e, o) for o in owner))
    if people == 0:
        return {'result': 'no_face', 'people': 0}
    result = 'owner' if best >= FACE_MATCH else 'stranger' if best < FACE_STRANGER else 'uncertain'
    return {'result': result, 'score': round(best, 3), 'people': people}


# ── voice ───────────────────────────────────────────────────────────────────

def _mel_banks(n_mels=80, n_fft=512, sr=16000, low=20.0, high=8000.0):
    mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)
    bins = n_fft // 2
    freqs = np.arange(bins) * sr / n_fft
    mf = mel(freqs)
    edges = np.linspace(mel(low), mel(high), n_mels + 2)
    banks = np.zeros((n_mels, bins), dtype=np.float32)
    for m in range(n_mels):
        l, c, r = edges[m], edges[m + 1], edges[m + 2]
        up = (mf - l) / (c - l)
        down = (r - mf) / (r - c)
        banks[m] = np.clip(np.minimum(up, down), 0, None)
    return banks


_BANKS = None


def fbank(pcm16: np.ndarray, sr=16000) -> np.ndarray:
    """Kaldi-style 80-bin log mel filterbank (25 ms Povey window, 10 ms hop, pre-emphasis 0.97), mean-normalised."""
    global _BANKS
    x = np.asarray(pcm16, dtype=np.float32).ravel()           # int16 scale, as Kaldi expects
    fl, hop, nfft = int(0.025 * sr), int(0.010 * sr), 512
    if x.size < fl:
        return np.zeros((0, 80), dtype=np.float32)
    n = 1 + (x.size - fl) // hop
    idx = np.arange(fl)[None, :] + hop * np.arange(n)[:, None]
    fr = x[idx]
    fr = fr - fr.mean(axis=1, keepdims=True)
    fr = np.concatenate([fr[:, :1] * (1 - 0.97), fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1)
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(fl) / (fl - 1))) ** 0.85
    spec = np.abs(np.fft.rfft(fr * win, n=nfft)) ** 2
    if _BANKS is None:
        _BANKS = _mel_banks()
    feats = np.log(np.maximum(spec[:, :nfft // 2] @ _BANKS.T, np.finfo(np.float32).eps))
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


class Speaker:
    def __init__(self):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(str(MODELS / 'speaker.onnx'), opts, providers=['CPUExecutionProvider'])

    def embed(self, pcm16: np.ndarray) -> np.ndarray | None:
        f = fbank(pcm16)
        if f.shape[0] < 100:                      # under a second of audio: too little to judge
            return None
        return self.sess.run(None, {'feats': f[None]})[0][0]


_speaker: Speaker | None = None


def _speaker_engine() -> Speaker:
    global _speaker
    if _speaker is None:
        _speaker = Speaker()
    return _speaker


class VoiceGuard:
    """Collects the user's speech from the mic stream and checks each turn against the owner's voice."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=600)
        self.buf: list[np.ndarray] = []
        self.enrolling: list[np.ndarray] | None = None
        self.enroll_target = 5
        self.owner = _load_vec('voice.npy')
        self.last = None              # {'result', 'score', 'at'}
        self.strangers = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True, name='jarvis-voice-guard').start()

    def feed(self, pcm) -> None:
        try:
            self.q.put_nowait(np.array(pcm, dtype=np.int16, copy=True).ravel())
        except queue.Full:
            pass

    def _worker(self):
        while True:
            block = self.q.get()
            level = float(np.sqrt(np.mean((block.astype(np.float32) / 32768) ** 2)))
            if level > 0.008:                     # keep speech, drop silence so signatures are about the voice
                with self._lock:
                    self.buf.append(block)
                    if len(self.buf) > 160:       # ~10 s
                        self.buf = self.buf[-160:]

    def check_now(self) -> dict | None:
        """Verdict on the speech heard so far this turn, without consuming it (used to gate sensitive actions)."""
        if self.owner is None or self.enrolling is not None:
            return None
        with self._lock:
            audio = np.concatenate(self.buf) if self.buf else np.zeros(0, np.int16)
        if audio.size < 16000 * 1.2:
            return None
        emb = _speaker_engine().embed(audio[-16000 * 8:])
        if emb is None:
            return None
        score = max(_cos(emb, o) for o in self.owner)
        return {'result': 'owner' if score >= VOICE_MATCH else 'stranger' if score < VOICE_STRANGER else 'uncertain',
                'score': round(score, 3)}

    def start_enrolment(self, utterances=5) -> dict:
        self.enrolling, self.enroll_target = [], utterances
        return {'enrolling': True, 'say': f'Speak normally for your next {utterances} sentences; I will learn your voice.'}

    def end_turn(self) -> dict | None:
        """Call when the user's spoken turn is complete. Returns a verdict, an enrolment update, or None."""
        with self._lock:
            audio = np.concatenate(self.buf) if self.buf else np.zeros(0, np.int16)
            self.buf = []
        if audio.size < 16000 * 1.2:
            return None
        try:
            emb = _speaker_engine().embed(audio[-16000 * 8:])
        except Exception as exc:
            return {'error': str(exc)[:160]}
        if emb is None:
            return None
        if self.enrolling is not None:
            self.enrolling.append(emb)
            if len(self.enrolling) >= self.enroll_target:
                arr = np.array(self.enrolling)
                _save_vec('voice.npy', arr)
                self.owner, self.enrolling = arr, None
                return {'enrolled': True, 'samples': len(arr)}
            return {'enrolling': True, 'collected': len(self.enrolling), 'of': self.enroll_target}
        if self.owner is None or not settings()['voice_guard']:
            return None
        score = max(_cos(emb, o) for o in self.owner)
        result = 'owner' if score >= VOICE_MATCH else 'stranger' if score < VOICE_STRANGER else 'uncertain'
        self.strangers = self.strangers + 1 if result == 'stranger' else 0
        self.last = {'result': result, 'score': round(score, 3), 'at': time.time()}
        return dict(self.last, consecutive_strangers=self.strangers)


_voice: VoiceGuard | None = None


def voice() -> VoiceGuard:
    global _voice
    if _voice is None:
        _voice = VoiceGuard()
    return _voice


GUEST_NOTE = ('[Private security context from JARVIS\'s voice recognition, not spoken by the user: the last command came '
              'from a voice that does not match the owner. Treat the speaker as a guest: be polite, but do not send '
              'messages, make purchases, delete or move files, change settings, or reveal the owner\'s private '
              'information, memory or finances until the owner confirms. Do not mention this check unless asked.]')
OWNER_BACK_NOTE = '[Private context: the owner\'s voice is recognised again; normal permissions resume.]'


def status() -> dict:
    v = voice()
    return {'face_enrolled': (STORE / 'face.npy').exists(), 'voice_enrolled': v.owner is not None,
            'voice_enrolling': v.enrolling is not None, 'last_voice_check': v.last, 'settings': settings(),
            'models_present': all((MODELS / m).exists() for m in ('yunet.onnx', 'sface.onnx', 'speaker.onnx')),
            'stored': 'Only face and voice signatures (numbers), never photos or audio.'}


def forget(what: str = 'all') -> dict:
    removed = []
    for name in (['face.npy'] if what == 'face' else ['voice.npy'] if what == 'voice' else ['face.npy', 'voice.npy']):
        p = STORE / name
        if p.exists():
            p.unlink(); removed.append(name)
    if what in ('voice', 'all'):
        voice().owner = None
    return {'removed': removed}
