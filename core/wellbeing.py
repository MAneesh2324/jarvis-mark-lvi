"""Emotion-aware JARVIS: notice how the user sounds, and look after them a little.

Voice mood
    While the user speaks, the microphone blocks JARVIS already streams are also
    measured locally: loudness, pitch, pitch variation and syllable rate. After
    each utterance those are compared with the user's OWN usual voice (a running
    baseline learned over the first utterances and kept updated), so a naturally
    loud or quiet person is not misread. A clear and repeated shift reads as
    stressed, tired or excited; words like "tired" or "frustrated" in what they
    said count too. Only the derived numbers are kept, never audio.

What JARVIS does with it
    A short private note is added to the conversation ("the user sounds tired:
    keep answers shorter and gentler"), at most every few minutes, and the model
    adapts its tone. It does not announce the detection unless asked.

Care
    After a long unbroken stretch of use it suggests a break (default two hours),
    and late at night it says so once. Both are rate-limited and can be turned off.
"""
from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / 'config' / 'wellbeing.json'
BASELINE = BASE / 'memory' / 'voice-baseline.json'
DEFAULTS = {'enabled': True, 'voice_mood': True, 'break_after_minutes': 120, 'late_night_hour': 1}
FEATURES = ('db', 'pitch', 'pitch_var', 'rate')
MIN_BASELINE = 8          # utterances before judging anyone
NOTE_GAP = 300            # seconds between mood notes to the model
BREAK_REPEAT = 3600       # seconds between break reminders
IDLE_RESET = 20 * 60      # this long without activity starts a new working session

_TIRED_WORDS = re.compile(r"\b(tired|exhausted|sleepy|drained|so done|can't think|cannot think|need (a )?rest|need sleep|thak gaya|thaka)\b", re.I)
_STRESS_WORDS = re.compile(r"\b(stress(ed)?|frustrat\w*|annoy\w*|angry|pissed|ugh+|damn|hell|why (is|isn't|won't)|not working again|lost (again|money|it all)|panic\w*|worried|anxious)\b", re.I)
_HAPPY_WORDS = re.compile(r"\b(awesome|amazing|great news|yes+!?|won|profit|nailed it|excited|love it|fantastic)\b", re.I)


def settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def configure(**changes) -> dict:
    from core.mission_store import write_file
    cur = settings()
    for k in ('enabled', 'voice_mood'):
        if changes.get(k) is not None:
            cur[k] = bool(changes[k])
    if changes.get('break_after_minutes') is not None:
        cur['break_after_minutes'] = max(0, min(int(changes['break_after_minutes']), 600))
    CONFIG.parent.mkdir(exist_ok=True)
    write_file(CONFIG, json.dumps(cur))
    return cur


# ── per-block acoustics ─────────────────────────────────────────────────────

def block_features(pcm: np.ndarray, sr: int = 16000):
    """(level_db, pitch_hz or None) for one ~64 ms block."""
    x = np.asarray(pcm, dtype=np.float32).ravel() / 32768.0
    if x.size < 256:
        return -99.0, None
    rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
    db = 20 * math.log10(rms)
    if db < -42:
        return db, None
    x = x - x.mean()
    lo, hi = int(sr / 400), int(sr / 70)            # 70-400 Hz voice range
    ac = np.correlate(x, x, mode='full')[x.size - 1:]
    if ac[0] <= 0:
        return db, None
    seg = ac[lo:hi]
    k = int(np.argmax(seg))
    if seg[k] / ac[0] < 0.35:                       # not periodic enough to be voiced
        return db, None
    return db, sr / (lo + k)


class _Utterance:
    def __init__(self):
        self.dbs, self.pitches, self.env, self.start = [], [], [], time.monotonic()

    def add(self, db, pitch):
        self.env.append(db)
        if db > -42:
            self.dbs.append(db)
        if pitch:
            self.pitches.append(pitch)

    def summary(self, block_s):
        voiced = len(self.dbs)
        if voiced < 8 or len(self.pitches) < 5:      # under ~0.5 s of speech: too little to judge
            return None
        env = np.array(self.env)
        smooth = np.convolve(env, np.ones(3) / 3, mode='same')
        peaks = sum(1 for i in range(1, len(smooth) - 1)
                    if smooth[i] > smooth[i - 1] and smooth[i] >= smooth[i + 1] and smooth[i] > -38)
        p = np.array(self.pitches)
        loud = np.nonzero(env > -42)[0]
        span = (loud[-1] - loud[0] + 1) * block_s if loud.size else voiced * block_s   # pauses count: slow speech is spread out
        return {'db': float(np.mean(self.dbs)), 'pitch': float(np.median(p)),
                'pitch_var': float(np.percentile(p, 75) - np.percentile(p, 25)),
                'rate': peaks / max(span, 0.5), 'span': float(span)}


# ── baseline ────────────────────────────────────────────────────────────────

class Baseline:
    """Running mean/variance per feature (Welford), persisted between sessions."""

    def __init__(self, path: Path | None = None):
        self.path = path or BASELINE        # resolved at call time, so tests and resets use the current location
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {'n': 0, 'stats': {f: [0.0, 0.0] for f in FEATURES}}

    def _count(self, f):
        counts = self.data.setdefault('counts', {})
        return counts.get(f, self.data['n'] if f != 'rate' else 0)

    def update(self, feats):
        """feats[f] may be None (e.g. no pace on a two-word reply): that feature is simply not learned this time."""
        self.data['n'] = min(self.data['n'] + 1, 400)
        counts = self.data.setdefault('counts', {})
        for f in FEATURES:
            if feats.get(f) is None:
                continue
            n = counts[f] = min(self._count(f) + 1, 400)    # capped: slowly follows a changing voice
            mean, m2 = self.data['stats'][f]
            d = feats[f] - mean
            mean += d / n
            m2 += d * (feats[f] - mean)
            self.data['stats'][f] = [mean, m2]

    def z(self, feats):
        """Deviation from the user's usual voice per feature; None for a feature not measured or not yet learned."""
        if self.data['n'] < MIN_BASELINE:
            return None
        out = {}
        for f in FEATURES:
            n = self._count(f)
            if feats.get(f) is None or n < MIN_BASELINE:
                out[f] = None
                continue
            mean, m2 = self.data['stats'][f]
            sd = math.sqrt(max(m2 / max(n - 1, 1), 1e-6))
            floor = {'db': 2.0, 'pitch': 8.0, 'pitch_var': 5.0, 'rate': 0.4}[f]   # ignore trivial wobble
            out[f] = (feats[f] - mean) / max(sd, floor)
        return out

    def save(self):
        from core.mission_store import write_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_file(self.path, json.dumps(self.data))


def classify(z, text=''):
    """(mood, reasons) from z-scores against the user's own voice and the words they used."""
    reasons = []
    if text and _TIRED_WORDS.search(text):
        return 'tired', ['said they are tired']
    if text and _STRESS_WORDS.search(text):
        reasons.append('frustrated wording')
    if z is None:
        return ('stressed' if reasons else 'calm'), reasons
    g = lambda f: z.get(f) if z.get(f) is not None else 0.0
    rate_known = z.get('rate') is not None
    if g('pitch') > 1.0 and (g('db') > 0.8 or g('rate') > 0.8):
        return 'stressed', reasons + ['higher, louder or faster than usual']
    # Tired: quieter and flatter, and slower when pace is known (a stronger drop is needed when it is not).
    if g('pitch_var') < -0.4 and ((rate_known and g('db') < -0.8 and g('rate') < -0.6) or (not rate_known and g('db') < -1.3)):
        return 'tired', ['quieter, slower and flatter than usual']
    if g('pitch_var') > 1.2 and g('db') > 0.5:
        return 'excited', ['more animated than usual']
    if reasons:
        return 'stressed', reasons
    if text and _HAPPY_WORDS.search(text):
        return 'excited', ['upbeat wording']
    return 'calm', []


GUIDANCE = {
    'stressed': 'sounds stressed or frustrated. Be calm, brief and solution-first; acknowledge the difficulty in a few '
                'words at most; no jokes. If it is about a trading loss, be steady and supportive, never pushy.',
    'tired': 'sounds tired. Keep answers short and gentle, avoid long lists, and if it fits, offer to save the rest '
             'for later or suggest a break.',
    'excited': 'sounds upbeat. Match the energy a little, keep it crisp.',
}


class Wellbeing:
    """One per JARVIS process. feed() is safe to call from the audio callback."""

    def __init__(self, block_s: float = 1024 / 16000):
        self.block_s = block_s
        self.q: queue.Queue = queue.Queue(maxsize=400)
        self.baseline = Baseline()
        self.utt: _Utterance | None = None
        self.silent_blocks = 0
        self.history: list[str] = []
        self.mood, self.reasons, self.last_note = 'calm', [], 0.0
        self.session_start, self.last_activity = time.time(), time.time()
        self.last_break, self.late_said = 0.0, ''
        self._done: list[dict] = []
        self._lock = threading.Lock()
        self._busy = False
        threading.Thread(target=self._worker, daemon=True, name='jarvis-wellbeing').start()

    # audio thread
    def feed(self, pcm) -> None:
        try:
            self.q.put_nowait(np.array(pcm, copy=True))
        except queue.Full:
            pass

    def _worker(self):
        while True:
            pcm = self.q.get()
            self._busy = True
            try:
                db, pitch = block_features(pcm)
                if db > -42:
                    self.silent_blocks = 0
                    if self.utt is None:
                        self.utt = _Utterance()
                    self.utt.add(db, pitch)
                elif self.utt is not None:
                    self.silent_blocks += 1
                    self.utt.add(db, None)
                    if self.silent_blocks * self.block_s > 0.9:
                        self._close()
            except Exception as exc:
                print(f'[Wellbeing] {exc}')
            finally:
                self._busy = False

    def _close(self):
        utt, self.utt = self.utt, None
        if utt is None:
            return
        feats = utt.summary(self.block_s)
        if feats:
            with self._lock:
                self._done.append(feats)

    # main thread, once per user turn
    def end_turn(self, text: str = '') -> str | None:
        """Call when the user's turn is complete. Returns a private note for the model, or None."""
        cfg = settings()
        self.activity()
        if not cfg['enabled']:
            return None
        deadline = time.monotonic() + 0.5
        while (not self.q.empty() or self._busy) and time.monotonic() < deadline:
            time.sleep(0.01)       # let the analyser finish this turn's audio before judging it
        self._close()
        with self._lock:
            feats_list, self._done = self._done, []
        z = None
        if cfg['voice_mood'] and feats_list:
            merged = {f: float(np.mean([x[f] for x in feats_list])) for f in FEATURES}
            words = len(re.findall(r"[\w']+", text or ''))
            spoken = sum(x.get('span', 0) for x in feats_list)
            # Pace is words per second from the transcript; on very short replies it is unknown, not guessed,
            # so the baseline never mixes two different measures of pace.
            merged['rate'] = words / spoken if words >= 3 and spoken > 0.8 else None
            z = self.baseline.z(merged)
            if z is None or max(abs(v) for v in z.values() if v is not None) < 2.5:
                self.baseline.update(merged)     # learn from ordinary speech, not from the outliers
                if self.baseline.data['n'] % 5 == 0:
                    self.baseline.save()
        mood, reasons = classify(z, text)
        self.history = (self.history + [mood])[-3:]
        # Two of the last three turns must agree before the mood changes: one odd sentence is noise.
        settled = max(set(self.history), key=self.history.count)
        if self.history.count(settled) >= 2 or reasons and 'said they are tired' in reasons:
            new = mood if reasons and 'said they are tired' in reasons else settled
            if new != self.mood:
                self.mood, self.reasons = new, reasons
                if new != 'calm' and time.time() - self.last_note > NOTE_GAP:
                    self.last_note = time.time()
                    return (f'[Private context from JARVIS\'s voice-tone sensor, not spoken by the user: the user {GUIDANCE[new]} '
                            'Do not mention this detection unless they ask how you knew.]')
        return None

    def activity(self) -> None:
        now = time.time()
        if now - self.last_activity > IDLE_RESET:
            self.session_start = now
        self.last_activity = now

    def care_check(self) -> str | None:
        """Called every minute or so. Returns something worth saying, or None."""
        cfg = settings()
        if not cfg['enabled']:
            return None
        now = time.time()
        if now - self.last_activity > IDLE_RESET:
            return None
        mins = (now - self.session_start) / 60
        limit = cfg['break_after_minutes']
        if limit and mins >= limit and now - self.last_break > BREAK_REPEAT:
            self.last_break = now
            hours = mins / 60
            return (f"You've been at it for {hours:.1f} hours without a proper break. "
                    + ('A five-minute stretch and some water would do you good, sir.' if self.mood != 'stressed'
                       else 'Step away for a few minutes; the markets and the code will still be here.'))
        hour = datetime.now().hour
        today = datetime.now().strftime('%Y-%m-%d')
        if cfg['late_night_hour'] <= hour < 5 and self.late_said != today and mins > 20:
            self.late_said = today
            return "It's past " + str(cfg['late_night_hour']) + " in the morning, sir. Decisions get worse when we're tired; consider calling it a night."
        return None

    def status(self) -> dict:
        n = self.baseline.data['n']
        return {'mood': self.mood, 'why': self.reasons, 'voice_baseline_utterances': n,
                'baseline_ready': n >= MIN_BASELINE, 'session_minutes': round((time.time() - self.session_start) / 60),
                'settings': settings(),
                'note': 'Mood is estimated from loudness, pitch and pace against your own usual voice, plus your words. '
                        'Only these numbers are stored, never audio.'}


_instance: Wellbeing | None = None


def instance() -> Wellbeing:
    global _instance
    if _instance is None:
        _instance = Wellbeing()
    return _instance
