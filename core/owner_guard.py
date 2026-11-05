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
FACE_MATCH, FACE_STRANGER = 0.40, 0.25        # SFace cosine: OpenCV's published same-person threshold is 0.363
VOICE_MATCH, VOICE_STRANGER = 0.55, 0.30      # WeSpeaker cosine. VOICE_MATCH is the most the owner threshold asks for;
VOICE_FLOOR = 0.45                            # it is tuned down to how consistent the owner's own samples are, never below this
VOICE_JUDGE_SECONDS = 2.5                     # a 'stranger' verdict needs this much speech; shorter is only 'uncertain'
VOICE_ALARM = 0.20                            # one turn this far from the owner raises the alarm at once; otherwise two in a row
PROFILE_MAX = 40                              # samples kept per profile (it keeps learning from confident matches)


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


def _unit(a):
    a = np.asarray(a, dtype=np.float32)
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


def match_score(profile, emb) -> float:
    """How well one signature matches a profile of several.

    The best single sample (the old rule) is noisy: one lucky or unlucky sample decides. This
    uses the mean of the three closest samples, or the profile's centre, whichever is higher, so
    a match has to agree with several moments of the person, not one."""
    o, e = _unit(profile), _unit(emb)
    sims = np.sort(o @ e)[::-1]
    top = float(sims[:min(3, len(sims))].mean())
    return max(top, float(_unit(o.mean(0)) @ e))


def owner_threshold(profile, ceiling=VOICE_MATCH, floor=VOICE_FLOOR) -> float:
    """The score the owner must reach, tuned to how alike the owner's own samples are.

    Someone whose samples agree at 0.9 can be held to the ceiling; a profile whose samples agree
    at 0.6 (different mics, rooms, moods) gets a lower bar, so the owner is not turned away. It
    never drops below the floor, which sits well above how strangers score (about 0.0-0.3)."""
    o = _unit(profile)
    if len(o) < 3:
        return ceiling
    loo = [match_score(np.delete(o, i, 0), o[i]) for i in range(len(o))]
    return round(float(min(ceiling, max(floor, np.percentile(loo, 20) - 0.08))), 3)


def _learn(profile, emb, near=0.97):
    """Add a confident new sample, unless it repeats one already there; drop the most redundant past the cap."""
    o, e = _unit(profile), _unit(emb)
    if float(np.max(o @ e)) >= near:
        return None
    o = np.vstack([o, e[None]])
    if len(o) > PROFILE_MAX:
        sims = o @ o.T
        np.fill_diagonal(sims, -1)
        o = np.delete(o, int(np.argmax(sims.max(1)[:-1])), 0)   # the newest sample always stays
    return o


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

    def good(self, img, face) -> bool:
        """Only clear faces count: big enough, confidently found, sharp, and neither too dark nor blown out."""
        x, y, w, h = (int(v) for v in face[:4])
        if w < 80 or h < 80 or float(face[-1]) < 0.85:
            return False
        crop = img[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            return False
        grey = self.cv2.cvtColor(crop, self.cv2.COLOR_BGR2GRAY)
        light = float(grey.mean())
        return 45 <= light <= 215 and float(self.cv2.Laplacian(grey, self.cv2.CV_64F).var()) >= 25

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
                # let auto-exposure settle: the first frames from a Mac camera are dark, and a dark face
                # scores like a stranger. Wait until brightness stops changing (at most ~2 s).
                started, last = time.monotonic(), None
                while time.monotonic() - started < 2.0:
                    ok, img = cap.read()
                    if not ok or img is None:
                        continue
                    light = float(img.mean())
                    if last is not None and abs(light - last) < 2.0 and time.monotonic() - started > 0.7:
                        break
                    last = light
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


def enroll_face(samples: int = 24) -> dict:
    """About 8 seconds of frames. Turning the head a little and changing expression while it runs gives
    a profile that still recognises you from a slight angle or in other light."""
    eng = _face_engine()
    embs = []
    for img in eng.frames(samples, 0.33):
        found = eng.faces(img)
        if len(found) == 1 and eng.good(img, found[0]):
            e = _unit(eng.embed(img, found[0]))
            if not embs or float(np.max(np.array(embs) @ e)) < 0.985:     # skip near-identical frames
                embs.append(e)
    if len(embs) < 6:
        raise RuntimeError(f'Only {len(embs)} clear single-face frames. Sit facing the camera, alone, about an arm\'s '
                           'length away, in good even light, and retry.')
    embs = np.array(embs)
    _save_vec('face.npy', embs)
    return {'enrolled': True, 'frames_used': len(embs), 'consistency': round(float(np.mean(embs @ _unit(embs.mean(0)))), 3),
            'tip': 'Accuracy improves further as JARVIS adds confident matches over the next days.'}


def check_face(frames: int = 6) -> dict:
    owner = _load_vec('face.npy')
    if owner is None:
        return {'result': 'not_enrolled'}
    eng = _face_engine()
    scores, people, seen, best_emb = [], 0, 0, None
    for img in eng.frames(frames, 0.22):
        found = eng.faces(img)
        people = max(people, len(found))
        frame_best = None
        for f in found[:3]:
            seen += 1
            if not eng.good(img, f):
                continue
            e = eng.embed(img, f)
            sc = match_score(owner, e)
            if frame_best is None or sc > frame_best[0]:
                frame_best = (sc, e)
        if frame_best:
            scores.append(frame_best[0])
            if best_emb is None or frame_best[0] > best_emb[0]:
                best_emb = frame_best
    if people == 0:
        return {'result': 'no_face', 'people': 0}
    if len(scores) < 2:
        return {'result': 'unclear', 'people': people,
                'hint': 'A face is there but not clearly: too dark, too far, blurred or turned away.'}
    scores.sort(reverse=True)
    steady = scores[1]                                  # the second-best frame: one lucky frame is not enough
    result = 'owner' if steady >= FACE_MATCH else 'stranger' if scores[0] < FACE_STRANGER else 'uncertain'
    if result == 'owner' and steady >= FACE_MATCH + 0.1 and best_emb is not None:
        grown = _learn(owner, best_emb[1])              # keep learning the owner's face in new light
        if grown is not None:
            _save_vec('face.npy', grown)
    return {'result': result, 'score': round(steady, 3), 'best': round(scores[0], 3), 'frames': len(scores), 'people': people}


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
        self.threshold = owner_threshold(self.owner) if self.owner is not None else VOICE_MATCH
        self.last = None              # {'result', 'score', 'at'}
        self.strangers = 0
        self.noise = 0.004            # running estimate of the room's background level
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True, name='jarvis-voice-guard').start()

    def feed(self, pcm) -> None:
        try:
            self.q.put_nowait(np.array(pcm, dtype=np.int16, copy=True).ravel())
        except queue.Full:
            pass

    def _speech(self, block):
        """Keep only the 20 ms frames that are speech, judged against the room's own background level,
        so fans, typing and silence do not blur the voice signature."""
        n = block.size // 320
        if n == 0:
            return block[:0]
        frames = block[:n * 320].reshape(n, 320)
        rms = np.sqrt(np.mean((frames.astype(np.float32) / 32768) ** 2, axis=1))
        quiet = float(rms.min())
        # the background estimate falls quickly to a quieter block but rises only slowly, so speech
        # (which is never quiet for long) cannot drag it up
        self.noise = 0.99 * self.noise + 0.01 * quiet if quiet > self.noise else 0.6 * self.noise + 0.4 * quiet
        return frames[rms > max(0.005, self.noise * 2.5)].ravel()

    def _worker(self):
        while True:
            speech = self._speech(self.q.get())
            if speech.size:
                with self._lock:
                    self.buf.append(speech)
                    total = sum(b.size for b in self.buf)
                    while total > 16000 * 10 and len(self.buf) > 1:      # keep the last ~10 s of speech
                        total -= self.buf.pop(0).size

    def verdict(self, emb, seconds) -> dict:
        score = match_score(self.owner, emb)
        if score >= self.threshold:
            result = 'owner'
        elif score < VOICE_STRANGER and seconds >= VOICE_JUDGE_SECONDS:
            result = 'stranger'
        else:
            result = 'uncertain'                  # too short to judge, or in between: never an alarm
        return {'result': result, 'score': round(score, 3), 'threshold': self.threshold, 'seconds': round(seconds, 1)}

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
        return self.verdict(emb, min(audio.size, 16000 * 8) / 16000)

    def start_enrolment(self, utterances=6) -> dict:
        self.enrolling, self.enroll_target = [], max(3, min(int(utterances), 12))
        return {'enrolling': True, 'say': f'Speak normally for your next {self.enroll_target} sentences, each a full sentence '
                                          'of a couple of seconds; I will learn your voice.'}

    def _finish_enrolment(self):
        arr = _unit(np.array(self.enrolling))
        if len(arr) >= 5:                         # drop a sample that does not sound like the rest (a cough, someone else)
            fit = np.array([match_score(np.delete(arr, i, 0), arr[i]) for i in range(len(arr))])
            arr = arr[fit >= np.median(fit) - 0.15]
        _save_vec('voice.npy', arr)
        self.owner, self.enrolling = arr, None
        self.threshold = owner_threshold(arr)
        return {'enrolled': True, 'samples': len(arr), 'threshold': self.threshold}

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
        seconds = min(audio.size, 16000 * 8) / 16000
        if self.enrolling is not None:
            if seconds < 2.0:
                return {'enrolling': True, 'collected': len(self.enrolling), 'of': self.enroll_target,
                        'note': 'That was short; say a full sentence.'}
            self.enrolling.append(emb)
            if len(self.enrolling) >= self.enroll_target:
                return self._finish_enrolment()
            return {'enrolling': True, 'collected': len(self.enrolling), 'of': self.enroll_target}
        if self.owner is None or not settings()['voice_guard']:
            return None
        v = self.verdict(emb, seconds)
        if v['result'] == 'stranger':
            self.strangers += 1
        elif v['result'] == 'owner':
            self.strangers = 0
            if v['score'] >= self.threshold + 0.05 and seconds >= VOICE_JUDGE_SECONDS:
                grown = _learn(self.owner, emb)  # keep learning the owner's voice: new rooms, moods, mics
                if grown is not None:
                    _save_vec('voice.npy', grown)
                    self.owner = grown
                    self.threshold = owner_threshold(grown)
        # one clearly different voice, or two strangers in a row, raise the alarm; a single borderline turn does not
        alarm = v['result'] == 'stranger' and (self.strangers >= 2 or v['score'] < VOICE_ALARM)
        self.last = dict(v, at=time.time())
        return dict(self.last, consecutive_strangers=self.strangers, alarm=alarm)


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
