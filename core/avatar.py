"""
Holographic AI head for the HUD centre — the thing that used to be a ring stack
with the assistant's name in the middle.

Design notes
------------
* **The face is real human geometry.** `core.avatar_mesh` builds the head around
  MediaPipe's canonical face model, so eyelids, nostrils, lips and cheekbones
  are measured anatomy rather than fitted curves. This renderer's whole job is
  to light it, pose it and animate it.
* **Software rendered, on purpose.** Everything is QPainter, so there is no
  OpenGL context, no shader compile, no GPU driver to disagree with us and no
  new pip dependency. It looks the same on a gaming rig, a 2013 laptop, a VM
  and a remote desktop session.
* **Lip-sync comes from the audio pipeline, not from the avatar.** `main.py`
  already computes a real RMS level off the PCM (`_pcm_level`) for both the mic
  and JARVIS's own output. The avatar just consumes that number, so there is no
  second audio path to fall out of sync. The mouth only tracks the level while
  JARVIS is *speaking* — during listening the same level drives the aura, so the
  head never lip-syncs to the user's voice.

The renderer is theme-agnostic: `paint()` takes its colours as arguments, which
is what lets the HueWheel accent picker retint the avatar for free.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient

from core.avatar_mesh import JAW_MAX, JAW_PIVOT, get_head_mesh

# Perspective camera distance in head-half-heights. Large enough that the nose
# does not balloon, small enough to keep a sense of depth.
_CAM_D = 4.6

# Wireframe opacity buckets, so the whole lattice draws in a handful of batched
# drawLines() calls instead of one call per line.
_BUCKETS = 4
_MIN_ALPHA = 0.05

# Resolution of the surface-shading colour ramp. Banding across a filled facet
# is far more visible than banding in line alpha, so this is fine-grained — and
# being a lookup it costs nothing per face.
_LUT_N = 192

# How far the brows travel at full lift, in head-half-heights. Derived, not
# tuned: the brow-to-eye gap is 0.198 and a real raise covers about a third of
# it, then the drawn landmarks only carry half the rig weight.
_BROW_LIFT = 0.14

# Mouth timing, as time constants in seconds rather than per-frame fractions.
# A fixed per-frame lerp silently changes speed with the frame rate: the HUD
# runs at 60 Hz here, throttles its paint to 30, and drops to 20 when idle, so
# the same constant meant three different mouths. These do not.
#
# Shutting is the fastest of the three, and it is measured rather than chosen.
# A short closure occupies a single 20 ms schedule frame, so the mouth has one
# step to reach it: at 20 ms the jaw got a third of the way and the closure
# vanished, at 12 ms it arrives, and going below that changes nothing because
# the analysis window is then the limit, not the smoothing. Halving it doubled
# the closures the mouth visibly makes across a test paragraph, 5 of 21 to 10,
# with no loss of opening on the vowels. Only the return to rest, once talking
# has actually stopped, is leisurely.
_TAU_OPEN = 0.022     # jaw dropping toward a vowel
_TAU_SHUT = 0.012     # lips closing on a consonant, mid-word
_TAU_REST = 0.055     # settling back to rest after speech ends
_TAU_SHAPE = 0.018    # viseme openness following the schedule

# Only the microphone path needs a level floor: it has one coarse RMS and no way
# to tell speech from room tone. JARVIS's own voice arrives as a per-20 ms
# schedule whose silences are already silent, so it needs no floor and must not
# have one — a floor there swallows the gaps between words.
_MIC_FLOOR = 0.14

# How far below this voice's own loud level counts as a closure: -20 dB, which
# is what a stop consonant actually drops to. Expressed as a ratio so it holds
# at any speaker volume.
_CLOSE_FRAC = 0.10


def _rate(dt: float, tau: float) -> float:
    """Per-frame lerp factor for an exponential approach with time constant
    `tau`. Frame-rate independent: the motion takes the same wall-clock time at
    20, 30 or 60 fps, and a long frame catches up instead of stalling."""
    return 1.0 - math.exp(-dt / tau)


def _c(col: QColor, a: float) -> QColor:
    """Copy of `col` at alpha `a` (0-255, clamped)."""
    q = QColor(col)
    q.setAlpha(int(max(0.0, min(255.0, a))))
    return q


def _blend(bg: QColor, col: QColor, a: float) -> QColor:
    """`col` at alpha `a` pre-mixed onto `bg`, returned fully **opaque**.

    Qt's raster engine has a fast path for opaque antialiased lines and a much
    slower blended path for everything else — measured at 1.0 ms versus 2.9 ms
    for the same 780 lines. The HUD paints a flat background behind the avatar,
    so mixing the alpha in by hand is visually equivalent and three times cheaper.
    """
    f = max(0.0, min(1.0, a / 255.0))
    return QColor(int(bg.red() + (col.red() - bg.red()) * f),
                  int(bg.green() + (col.green() - bg.green()) * f),
                  int(bg.blue() + (col.blue() - bg.blue()) * f))


# ── animated expressions ─────────────────────────────────────────────────────
# Each clip is (seconds, fn(u) -> {channel: offset}) with u running 0 → 1. Offsets add on top of the
# resting feeling, so a laugh on a proud face is bigger than a laugh on a calm one would look.
# Channels: smile, brow, shape (inner brows + / furrow -), squint, lids (+ wider / - lower),
# wink_l, wink_r (0..1 closed), pitch (+ nods down), yaw, roll (+ tilts right), jaw (mouth open).

def _bell(u: float) -> float:
    return math.sin(math.pi * max(0.0, min(1.0, u))) ** 2


def _ahr(u: float, attack: float = 0.2, release: float = 0.3) -> float:
    """Attack, hold, release — eased at both ends."""
    if u <= 0 or u >= 1:
        return 0.0
    if u < attack:
        x = u / attack
    elif u > 1 - release:
        x = (1 - u) / release
    else:
        return 1.0
    return x * x * (3 - 2 * x)


CLIPS = {
    'nod':        (0.95, lambda u: {'pitch': 0.10 * math.sin(2 * math.pi * 2 * u) * (1 - u) ** 0.6}),
    'shake':      (1.10, lambda u: {'yaw': 0.16 * math.sin(2 * math.pi * 2.5 * u) * (1 - u) ** 0.7, 'shape': 0.3 * _bell(u)}),
    'brow_flash': (0.65, lambda u: {'brow': 1.0 * _bell(u), 'lids': 0.12 * _bell(u)}),
    'smile':      (1.80, lambda u: {'smile': 0.75 * _ahr(u, .25, .35), 'squint': 0.45 * _ahr(u, .3, .35), 'pitch': -0.02 * _ahr(u)}),
    'laugh':      (1.60, lambda u: {'smile': 1.0 * _ahr(u, .12, .3), 'squint': 0.8 * _ahr(u, .12, .3), 'brow': 0.45 * _ahr(u),
                                    'jaw': _ahr(u, .12, .3) * (0.18 + 0.22 * abs(math.sin(2 * math.pi * 4 * u))),
                                    'pitch': -0.05 * _ahr(u) + 0.025 * math.sin(2 * math.pi * 4 * u) * _ahr(u), 'roll': 0.05 * _ahr(u)}),
    'wink':       (0.80, lambda u: {'wink_r': _ahr(u, .25, .35), 'smile': 0.55 * _ahr(u, .2, .4), 'roll': -0.06 * _ahr(u, .2, .4),
                                    'squint': 0.3 * _ahr(u)}),
    'surprise':   (1.30, lambda u: {'brow': 1.25 * _ahr(u, .1, .45), 'lids': 0.32 * _ahr(u, .1, .45), 'jaw': 0.45 * _ahr(u, .12, .4),
                                    'pitch': -0.05 * _ahr(u, .1, .45), 'smile': -0.2 * _ahr(u)}),
    'sigh':       (2.20, lambda u: {'shape': 0.9 * _ahr(u, .3, .35), 'lids': -0.35 * _ahr(u, .3, .35), 'pitch': 0.09 * _ahr(u, .3, .35),
                                    'jaw': 0.10 * _bell(u * 1.6), 'smile': -0.25 * _ahr(u), 'roll': 0.05 * _ahr(u)}),
    'think':      (2.00, lambda u: {'shape': -0.5 * _ahr(u), 'brow': -0.15 * _ahr(u), 'squint': 0.25 * _ahr(u),
                                    'yaw': 0.07 * _ahr(u), 'pitch': -0.06 * _ahr(u), 'roll': -0.05 * _ahr(u)}),
    'tilt':       (1.80, lambda u: {'roll': 0.09 * _ahr(u, .3, .35), 'brow': 0.30 * _ahr(u, .3, .35), 'pitch': 0.03 * _ahr(u)}),
    'micro_smile': (1.40, lambda u: {'smile': 0.35 * _bell(u), 'squint': 0.15 * _bell(u)}),
    'micro_brow': (0.55, lambda u: {'brow': 0.45 * _bell(u)}),
}
EXPRESSIONS = ('nod', 'shake', 'brow_flash', 'smile', 'laugh', 'wink', 'surprise', 'sigh', 'think', 'tilt')
# what the face does the moment a feeling arrives: (clip, delay seconds, strength)
REACTIONS = {
    'proud':      [('brow_flash', 0.0, 1.0), ('smile', 0.15, 1.0), ('nod', 0.5, 0.8)],
    'concerned':  [('sigh', 0.0, 1.0), ('tilt', 0.9, 0.8)],
    'determined': [('nod', 0.0, 1.0)],
    'playful':    [('wink', 0.0, 1.0), ('micro_smile', 0.7, 1.0)],
    'warm':       [('micro_smile', 0.0, 1.0)],
    'calm':       [('micro_smile', 0.0, 0.6)],
}
_CHANNELS = ('smile', 'brow', 'shape', 'squint', 'lids', 'wink_l', 'wink_r', 'pitch', 'yaw', 'roll', 'jaw')


class HoloAvatar:
    """Animated holographic head. One instance per HUD canvas.

    Lifecycle:
        av = HoloAvatar()
        av.step(dt, amp, speaking=..., muted=...)          # once per tick
        av.paint(painter, cx, cy, r, primary, accent, bg)  # once per frame
    """

    # Look: True paints a lit, solid head with a wireframe over it; False is a
    # see-through glass wireframe. Flip here, or per instance.
    shaded = True

    def __init__(self) -> None:
        mesh = get_head_mesh()
        self._v0 = mesh["verts"]
        self._n0 = mesh["normals"]
        self._jaw = mesh["jaw"]
        self._brow_w = mesh["brow"]
        self._lips_w = mesh["lips"]
        self._lip_c = mesh["lip_centre"]
        self._fade = mesh["fade"]
        self._f = mesh["faces"]
        self._fgroup = mesh["face_group"]
        self._fa, self._fb, self._fc = (self._f[:, i] for i in range(3))
        self._e0 = mesh["edges"][:, 0]
        self._e1 = mesh["edges"][:, 1]
        self._lm = mesh["landmarks"]
        self._body = mesh["body"][:, None]           # 1 = stays with the shoulders when the head turns
        self._curves = mesh["curves"]
        # The inner-lip ring runs lower-lip left→right, then upper-lip back.
        # Splitting it lets the upper arc anchor a strip of teeth, which is what
        # keeps an open mouth from reading as a hole punched in the face.
        lips_in = mesh["landmarks"]["lips_in"]
        self._lip_up = np.concatenate([lips_in[10:], lips_in[:1]])

        # Crown (+1.0) down to the bottom of the neck, in head-half-heights.
        # Callers size the head to the room they have with this.
        self.SPAN = mesh["span"][0] - mesh["span"][1]
        lip_x = np.abs(self._v0[self._lips_w > 0.3, 0] - self._lip_c[0]) if np.any(self._lips_w > 0.3) else np.array([0.2])
        self._lip_half = float(max(lip_x.max(), 1e-3))
        brow_x = np.abs(self._v0[self._brow_w > 0.3, 0]) if np.any(self._brow_w > 0.3) else np.array([0.5])
        self._brow_half = float(max(brow_x.max(), 1e-3))

        self._lut_cache: list = []
        self._lut_key = None

        n = self._v0.shape[0]
        self._v = np.empty((n, 3), dtype=np.float32)

        self._t = 0.0
        self._sway = 0.0           # integrated sway phase — see step()
        self._yaw = 0.0
        self._pitch = 0.0
        self._mouth = 0.0          # 0..1 smoothed jaw opening
        self._glow = 0.0           # 0..1 smoothed overall energy
        self._scan = -1.6          # vertical position of the energy sweep
        self._blink = 0.0          # 0 = open, 1 = shut
        self._blink_at = 3.0

        # ── expression ──────────────────────────────────────────────────────
        # Speech is not just a moving jaw. Brows ride the loudness envelope,
        # eyes widen with the brows, and the gaze flicks between fixation
        # points — those three are what make it read as talking rather than as
        # a puppet chewing.
        self._amp_slow = 0.0
        self._expr = 0.0
        self._expr_tgt = 0.0
        self._expr_at = 0.0
        self._brow = 0.0           # smoothed brow lift, -0.4 .. 1.2
        self._emph = 0.0           # syllable emphasis, drives the head nod
        self._gaze = [0.0, 0.0]
        self._gaze_tgt = [0.0, 0.0]
        self._gaze_at = 0.0

        # ── state expression ────────────────────────────────────────────────
        # The face is the fastest status indicator in the app: you read a gaze
        # before you read a word. Saccades orbit a bias that the assistant's
        # state moves — eyes off to the side while it thinks, back on you while
        # it listens, lids low while it sleeps.
        self._gaze_bias = [0.0, 0.0]
        self._bias_tgt = [0.0, 0.0]
        self._bias_at = 0.0
        self._lids = 1.0           # 1 = wide, 0 = shut; low while asleep
        self._brow_bias = 0.0      # concentration pulls the brows down
        self._glance = None        # (dx, dy, until_t) — a deliberate look
        # Feelings (core/companion.py): a resting smile, the brows, the lids and a slight head
        # tilt, each eased so the face changes the way a person's does — never a snap.
        self.feeling, self.feeling_level = 'warm', 0.4
        self._smile = 0.0
        self._feel_brow = 0.0
        self._feel_lids = 1.0
        self._brow_shape = 0.0
        self._squint = 0.0
        self._feel_roll = 0.0
        self._roll = 0.0
        self._clips: list = []           # [name, start_t, seconds, strength]
        self._g = dict.fromkeys(_CHANNELS, 0.0)
        self._idle_at = 6.0               # next little idle expression
        self._last_state = ''
        self._listen_react = -99.0
        self._feel_pitch = 0.0
        self._feel_yaw = 0.0

        # ── viseme ──────────────────────────────────────────────────────────
        # Loudness alone only answers "how far open", which is why an RMS-driven
        # mouth flaps rather than speaks. These two carry the *shape*: how open
        # the jaw is for this sound, and whether the lips are spread (/i/) or
        # rounded (/u/). They come from a formant read of the audio actually
        # being played — see `_pcm_visemes` in main.py.
        self._v_open = 1.0
        self._v_wide = 0.0
        self._wide = 0.0           # smoothed lip spread, -1 round .. +1 spread
        self._v_peak = 0.18        # running estimate of this voice's loud level

    # ── animation ───────────────────────────────────────────────────────────

    # feeling → (smile, brow lift, brow shape, eye opening, smiling eyes, pitch, yaw) at full intensity.
    # brow shape: + raises the inner ends (worry, sympathy), - pulls them down into a furrow (resolve).
    # smiling eyes: the lower lids rise, as in a real (Duchenne) smile.
    FEEL = {
        'warm':       (0.55, 0.10, 0.00, 1.00, 0.25, 0.000, 0.00),
        'calm':       (0.30, 0.00, 0.00, 0.84, 0.10, 0.000, 0.00),
        'concerned':  (-0.60, 0.20, 1.00, 1.08, 0.00, 0.060, 0.09),   # inner brows up, corners down, head bowed aside
        'proud':      (1.00, 0.30, -0.10, 1.00, 0.60, -0.050, 0.00),  # broad smile, smiling eyes, chin up
        'determined': (0.05, -0.30, -1.00, 0.78, 0.15, 0.015, 0.00),  # furrowed brows, narrowed eyes
        'playful':    (0.85, 0.45, 0.30, 1.05, 0.45, -0.015, -0.08),
    }

    def set_feeling(self, feeling: str, level: float = 0.6) -> None:
        if feeling in self.FEEL:
            changed = feeling != self.feeling
            self.feeling, self.feeling_level = feeling, max(0.0, min(1.0, float(level)))
            if changed:                           # react the moment the feeling arrives, then settle into it
                for name, delay, strength in REACTIONS.get(feeling, ()):
                    self.play(name, strength * (0.6 + 0.4 * self.feeling_level), delay)

    def play(self, name: str, strength: float = 1.0, delay: float = 0.0) -> bool:
        """Play an animated expression (see CLIPS). Safe to call from any thread: one list append."""
        if name not in CLIPS:
            return False
        self._clips = [c for c in self._clips if c[0] != name or c[1] > self._t + delay] + \
            [[name, self._t + max(0.0, delay), CLIPS[name][0], max(0.0, min(1.5, float(strength)))]]
        return True

    def _animate(self, t: float, dt: float, live: bool, st: str) -> None:
        """Sum the playing clips into channel offsets, and add the small expressions of a living face."""
        thinking = st in ("THINKING", "PROCESSING")
        asleep = st in ("SLEEPING", "STANDBY", "OFFLINE")
        if st != self._last_state:
            if st == "LISTENING" and t - self._listen_react > 20:
                self._listen_react = t
                self.play('brow_flash', 0.45)     # "I'm listening"
                self.play('tilt', 0.6, 0.25)
            elif thinking:
                self.play('think', 0.8)
            self._last_state = st
        if not live and not thinking and not asleep and t >= self._idle_at:
            self.play(random.choice(('micro_smile', 'micro_brow', 'tilt', 'micro_smile')), random.uniform(0.35, 0.6))
            self._idle_at = t + random.uniform(7.0, 15.0)
        elif live or asleep:
            self._idle_at = max(self._idle_at, t + 4.0)
        g = dict.fromkeys(_CHANNELS, 0.0)
        keep = []
        for clip in self._clips:
            name, start, dur, strength = clip
            if t < start:
                keep.append(clip)
                continue
            u = (t - start) / dur
            if u >= 1:
                continue
            keep.append(clip)
            for ch, val in CLIPS[name][1](u).items():
                g[ch] += val * strength
        self._clips = keep
        self._g = g

    def _mouth_step(self, dt: float, amp: float, live: bool,
                    v_open: float | None, v_level: float | None) -> None:
        """One increment of the jaw. Called once per viseme frame while JARVIS
        speaks, once per rendered frame otherwise."""
        if v_open is None:
            shape = 1.0
        else:
            self._v_open += (v_open - self._v_open) * _rate(dt, _TAU_SHAPE)
            shape = self._v_open

        if v_level is None:
            gated = max(0.0, (amp - _MIC_FLOOR) / (1.0 - _MIC_FLOOR))
            drive = (gated ** 0.6) * (shape ** 0.75)
        else:
            # Speech RMS spends most of its time well below full scale, so the
            # raw value alone would only ever half-open the jaw. Normalise it
            # against a running estimate of this voice's own loud level rather
            # than a constant: it then reads the same whether the user has the
            # volume low or the model happens to be speaking softly.
            self._v_peak = max(v_level, self._v_peak - dt * 0.55)
            ref = max(0.18, self._v_peak)
            # The floor is a fraction of this voice's own loud level, not a
            # fixed number, so it means the same thing at any volume and in any
            # language. A stop consonant drops 20 dB or more below the vowels
            # around it, which is this ratio — so a real closure lands at
            # exactly zero rather than at some small positive value the curve
            # would otherwise lift back up. That lift is what kept the mouth
            # from ever quite shutting between words.
            q = (v_level - _CLOSE_FRAC * ref) / (ref * (1.0 - _CLOSE_FRAC))
            drive = max(0.0, min(1.0, q)) ** 0.85 * (shape ** 0.75)

        target = min(1.0, drive) if live else 0.0
        if target > self._mouth:
            tau = _TAU_OPEN
        elif live:
            tau = _TAU_SHUT      # mid-word: a consonant, and it must shut now
        else:
            tau = _TAU_REST      # speech is over; settle, don't snap
        self._mouth += (target - self._mouth) * _rate(dt, tau)
        if self._mouth < 0.002:
            self._mouth = 0.0

    def step(self, dt: float, amp: float, speaking: bool = False,
             muted: bool = False, state: str = "",
             v_open: float | None = None, v_wide: float = 0.0,
             v_level: float | None = None,
             v_seq: list | None = None, v_hop: float = 0.02) -> None:
        """Advance the animation.

        `amp` is the 0..1 display audio level. `v_open` / `v_wide` / `v_level`
        are the viseme schedule's shape and true level for this instant; passing
        None falls back to loudness-only articulation, which is what the
        microphone path uses. `v_seq` is every schedule frame the last rendered
        frame spanned, so no closure is lost when the paint rate drops.
        """
        dt = max(0.001, min(0.10, float(dt)))
        self._t += dt
        t = self._t
        amp = max(0.0, min(1.0, float(amp)))
        live = speaking and not muted

        # Idle sway. The phase is *integrated* rather than taken as
        # sin(t * rate * speed): multiplying absolute time by a speed that
        # changes when JARVIS starts or stops talking jumps the phase by
        # t * rate * delta, which after a minute of uptime is several radians
        # and visibly teleports the head the instant a sentence ends.
        speed = (1.0 if not muted else 0.55) * (1.25 if live else 1.0)
        self._sway += dt * speed
        s = self._sway
        self._yaw = 0.26 * math.sin(s * 0.31) + 0.09 * math.sin(s * 0.73 + 1.3)
        self._pitch = (0.060 * math.sin(s * 0.23 + 0.7)
                       + 0.024 * math.sin(s * 0.61))

        # Mouth. Which level is driving it matters more than any rate here.
        #
        # `v_level` is this 20 ms frame's own RMS, taken from the very audio
        # about to be heard, so its silences are real silences. `amp` is the
        # waveform display's level, and that one is a *peak hold*: it keeps the
        # loudest value it has seen and decays gently, on purpose, so the bars
        # do not stutter between audio chunks. Driving a mouth from a peak hold
        # is why the gaps between words never closed — the hold spans exactly
        # the consonant it was supposed to reveal. So the schedule drives the
        # jaw whenever there is one, and `amp` is left to the microphone path,
        # which has nothing better.
        # Advance the mouth once per *schedule* frame rather than once per
        # rendered frame. A bilabial closure lasts around 40 ms — two frames of
        # a 50 Hz schedule — and the HUD throttles its paint to 30 fps and to 20
        # when idle. Point-sampling at 20 fps steps 50 ms at a time, so a whole
        # closure can fall between two samples and simply never be seen; that is
        # information loss no smoothing constant can recover. Sub-stepping costs
        # a few float operations per frame and makes the mouth identical at 20,
        # 30 and 60 fps.
        # An empty list is meaningful and is not the same as None: it says a
        # schedule is playing but this tick landed inside a frame already
        # spoken. The mouth's clock is the schedule's, so the right thing then
        # is to do nothing. Re-stepping the same frame — which is what a
        # truthiness test here would do — advances the jaw twice for one 20 ms
        # of audio, and at 60 fps that alone made the mouth behave differently
        # than at 20.
        if v_seq is not None:
            for lv, op, _wd in v_seq:
                self._mouth_step(v_hop, amp, live, op, lv)
        else:
            self._mouth_step(dt, amp, live, v_open, v_level)
        if not live:
            smile_now = self._smile + self._g.get('smile', 0.0)
            # a laugh or a gasp opens the mouth; a big smile parts the lips to show the teeth
            want = max(self._g.get('jaw', 0.0), max(0.0, smile_now - 0.55) * 0.32)
            if want > self._mouth:
                self._mouth += (want - self._mouth) * 0.25

        # Syllable emphasis. Applied unconditionally: `_emph` decays to zero on
        # its own once the mouth closes, whereas gating it on `live` deleted the
        # whole offset in a single frame and snapped the head at sentence end.
        self._emph += (self._mouth - self._emph) * _rate(
            dt, 0.055 if self._mouth > self._emph else 0.32)
        self._pitch -= self._emph * 0.028
        self._yaw += 0.018 * math.sin(t * 1.7) * self._emph

        # Loudness envelope, deliberately lazier than the mouth: brows track the
        # shape of a phrase, not individual syllables.
        env = amp if live else 0.0
        self._amp_slow += (env - self._amp_slow) * _rate(
            dt, 0.16 if env > self._amp_slow else 0.36)

        if live:
            if t >= self._expr_at:
                self._expr_tgt = random.uniform(-0.35, 1.0)
                self._expr_at = t + 1.1 + 2.0 * random.random()
        else:
            self._expr_tgt = 0.0
            self._expr_at = t + 0.8
        self._expr += (self._expr_tgt - self._expr) * 0.075

        smile_t, fbrow, fshape, flids, fsquint, fpitch, fyaw = self.FEEL.get(self.feeling, self.FEEL['warm'])
        k = self.feeling_level
        ease = _rate(dt, 0.9)                     # about a second to change expression
        self._smile += (smile_t * k * (0.6 if live else 1.0) - self._smile) * ease
        self._feel_brow += (fbrow * k - self._feel_brow) * ease
        self._brow_shape += (fshape * k - self._brow_shape) * ease
        self._squint += (fsquint * k - self._squint) * ease
        self._feel_lids += ((1 - (1 - flids) * k) - self._feel_lids) * ease
        self._feel_pitch += (fpitch * k - self._feel_pitch) * ease
        self._feel_yaw += (fyaw * k - self._feel_yaw) * ease
        self._feel_roll += ({'concerned': 0.07, 'playful': -0.05}.get(self.feeling, 0.0) * k - self._feel_roll) * ease
        self._animate(t, dt, live, (state or "").upper())
        g = self._g
        self._pitch += self._feel_pitch + g['pitch']
        self._yaw += self._feel_yaw + g['yaw']
        self._roll = self._feel_roll + g['roll']

        brow_t = 0.55 * self._amp_slow + 0.60 * self._expr + self._brow_bias + self._feel_brow + g['brow']
        self._brow += (max(-0.4, min(1.2, brow_t)) - self._brow) * 0.20

        # ── what the state does to the face ─────────────────────────────────
        st = (state or "").upper()
        thinking = st in ("THINKING", "PROCESSING")
        asleep = st in ("SLEEPING", "STANDBY", "OFFLINE")

        if thinking:
            # People look away to think, and hold it. The direction re-rolls
            # slowly so it reads as thought rather than as scanning.
            if t >= self._bias_at:
                self._bias_tgt = [random.choice((-1.0, 1.0)) * random.uniform(0.45, 0.8),
                                  random.uniform(0.25, 0.55)]
                self._bias_at = t + 1.4 + 1.6 * random.random()
            brow_bias, lid_tgt = -0.28, 0.94
        elif asleep:
            self._bias_tgt = [0.0, -0.25]
            brow_bias, lid_tgt = -0.05, 0.22
        else:
            # LISTENING / idle / speaking: eyes come back to the user.
            self._bias_tgt = [0.0, 0.0]
            self._bias_at = 0.0
            brow_bias = 0.10 if st == "LISTENING" else 0.0
            lid_tgt = 1.0

        for i in (0, 1):
            self._gaze_bias[i] += (self._bias_tgt[i] - self._gaze_bias[i]) * 0.06
        self._lids += (lid_tgt * self._feel_lids - self._lids) * 0.08
        self._brow_bias += (brow_bias - self._brow_bias) * 0.06

        # Gaze: saccades are near-instant jumps between fixations, and they get
        # more frequent when there is something to say. While thinking they slow
        # right down — a darting eye reads as nervous, not thoughtful.
        if t >= self._gaze_at:
            reach = 0.9 if live else (0.35 if thinking else 0.55)
            self._gaze_tgt = [random.uniform(-1.0, 1.0) * reach,
                              random.uniform(-1.0, 1.0) * reach * 0.55]
            if live:
                self._gaze_at = t + 0.55 + 1.7 * random.random()
            elif thinking:
                self._gaze_at = t + 1.8 + 2.4 * random.random()
            else:
                self._gaze_at = t + 1.3 + 2.8 * random.random()

        # A deliberate glance (something appeared on screen) overrides the
        # wandering for a moment, then hands control back.
        if self._glance is not None:
            gx, gy, until = self._glance
            if t < until:
                self._gaze_tgt = [gx, gy]
            else:
                self._glance = None

        for i, b in enumerate(self._gaze_bias):
            tgt = max(-1.0, min(1.0, self._gaze_tgt[i] + b))
            self._gaze[i] += (tgt - self._gaze[i]) * 0.30

        # Lips lead the jaw slightly in real speech, so they track a touch
        # faster; they also relax to neutral the moment the voice stops.
        wide_t = v_wide if (live and v_open is not None) else 0.0
        self._wide += (max(-1.0, min(1.0, wide_t)) - self._wide) * _rate(dt, 0.030)

        self._glow += ((0.0 if muted else amp) - self._glow) * (
            0.35 if (0.0 if muted else amp) > self._glow else 0.10)

        self._scan += dt * (0.55 + 1.5 * self._glow)
        if self._scan > 1.35:
            self._scan = -1.75

        if self._blink > 0.0:
            self._blink = max(0.0, self._blink - dt * 8.5)
        elif t >= self._blink_at:
            # Concentration suppresses blinking; a sleeping face has no need of
            # it at all, since the lids are already down.
            if asleep:
                self._blink_at = t + 6.0
            else:
                self._blink = 1.0
                gap = 5.5 if thinking else 3.4
                self._blink_at = t + gap + 3.1 * random.random()

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Look deliberately somewhere for `hold` seconds, then wander again.

        Used when something appears on screen: a face that looks at what just
        showed up tells the user it landed, without a word being spoken.
        """
        self._glance = (max(-1.0, min(1.0, float(dx))),
                        max(-1.0, min(1.0, float(dy))),
                        self._t + max(0.1, float(hold)))

    # ── posing ──────────────────────────────────────────────────────────────

    def _pose(self):
        """Jaw drop, brow lift and head rotation, applied to the real geometry."""
        v = self._v
        np.copyto(v, self._v0)

        if self._brow > 0.004 or self._brow < -0.004:
            # The brow-to-eye gap is 0.198 head-half-heights and a real raise
            # moves a third of it. The old 0.045 — halved again by the landmark
            # weights, which average 0.5 — worked out to six pixels on a 250 px
            # head, which is to say invisible.
            v[:, 1] += self._brow_w * (self._brow * _BROW_LIFT)
        bshape = self._brow_shape + self._g['shape']
        if abs(bshape) > 0.01:
            # +1 at the inner ends of the brows, -1 at the outer ends: worry lifts the middle, resolve knits it
            shape = np.clip(1.0 - 2.0 * np.abs(v[:, 0]) / self._brow_half, -1.0, 1.0)
            v[:, 1] += self._brow_w * (bshape * 0.10 * shape)

        if abs(self._wide) > 0.01 and self._mouth > 0.0:
            # Spread pulls the corners out and flattens the lips back; rounding
            # draws them in and pushes them forward into a purse.
            k = self._lips_w * (self._wide * self._mouth)
            v[:, 0] += k * (v[:, 0] - self._lip_c[0]) * 0.55
            v[:, 1] += k * (v[:, 1] - self._lip_c[1]) * 0.30
            v[:, 2] -= k * 0.055

        smile = max(-1.0, min(1.5, self._smile + self._g['smile']))
        if abs(smile) > 0.01:
            # A resting smile: the lip corners rise and spread a little; the middle stays put.
            dx = v[:, 0] - self._lip_c[0]
            reach = (dx / self._lip_half) ** 2
            w = self._lips_w * smile
            v[:, 1] += w * reach * 0.12
            v[:, 0] += w * dx * (0.16 if smile > 0 else 0.04)

        if self._mouth > 0.004:
            px, py, pz = JAW_PIVOT
            ang = self._jaw * (self._mouth * JAW_MAX)
            ca, sa = np.cos(ang), np.sin(ang)
            dy = v[:, 1] - py
            dz = v[:, 2] - pz
            v[:, 1] = py + dy * ca - dz * sa
            v[:, 2] = pz + dy * sa + dz * ca

        cy, sy = math.cos(self._yaw + getattr(self,"gesture_yaw",0)), math.sin(self._yaw + getattr(self,"gesture_yaw",0))
        cp, sp = math.cos(self._pitch + getattr(self,"gesture_pitch",0)), math.sin(self._pitch + getattr(self,"gesture_pitch",0))
        m = np.array([
            [cy, 0.0, sy],
            [sp * sy, cp, -sp * cy],
            [-cp * sy, sp, cp * cy],
        ], dtype=np.float32)

        if abs(self._roll) > 1e-4:                # a sideways tilt of the head (sympathy, curiosity, a laugh)
            cr, sr = math.cos(self._roll), math.sin(self._roll)
            m = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32) @ m
        self._m_head, self._m_body = m, self._body_matrix()
        b = self._body
        # Posture: the shoulders stay square while the head turns, nods and tilts; the neck blends between.
        return (v @ m.T) * (1 - b) + (v @ self._m_body.T) * b, (self._n0 @ m.T) * (1 - b) + (self._n0 @ self._m_body.T) * b

    def _body_matrix(self):
        y = 0.2 * (self._yaw + getattr(self, "gesture_yaw", 0))     # the body follows a turn only a little
        cy, sy = math.cos(y), math.sin(y)
        return np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float32)

    # ── rendering ───────────────────────────────────────────────────────────

    def _lut(self, bg: QColor, primary: QColor):
        """Cached ramp of opaque surface brushes from `bg` to `primary`."""
        key = (bg.rgb(), primary.rgb())
        if self._lut_key != key:
            self._lut_cache = [QBrush(_blend(bg, primary, 255.0 * (i + 0.5) / _LUT_N))
                               for i in range(_LUT_N)]
            self._lut_key = key
        return self._lut_cache

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              primary: QColor, accent: QColor, bg: QColor | None = None) -> None:
        """Draw the avatar with its head centre at (cx, cy).

        `r` is the head's half-height in pixels — the caller owns the layout, so
        the HUD can fit the head to whatever room the status line leaves it.
        """
        if bg is None:
            bg = QColor(0, 0, 0)
        amp = self._glow
        verts, norms = self._pose()

        # ── aura ────────────────────────────────────────────────────────────
        ar = r * 1.95
        grad = QRadialGradient(cx, cy, ar)
        grad.setColorAt(0.00, _c(primary, 34 + 66 * amp))
        grad.setColorAt(0.38, _c(primary, 20 + 40 * amp))
        grad.setColorAt(1.00, _c(primary, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(cx - ar, cy - ar, ar * 2, ar * 2))

        # ── project ─────────────────────────────────────────────────────────
        w = _CAM_D - verts[:, 2]
        np.maximum(w, 0.35, out=w)
        k = (_CAM_D / w) * r
        xs = cx + verts[:, 0] * k
        ys = cy - verts[:, 1] * k

        if self.shaded:
            self._paint_surface(p, xs, ys, norms, verts, primary, bg, amp)
        self._paint_wire(p, xs, ys, norms, verts, primary, bg, amp)
        self._paint_features(p, xs, ys, norms, r, primary, accent, bg, amp)
        self._paint_details(p, cx, cy, r, primary, accent, bg, amp)

    def _project(self, pts, cx, cy, r):
        w = np.maximum(_CAM_D - pts[:, 2], 0.35)
        k = (_CAM_D / w) * r
        return cx + pts[:, 0] * k, cy - pts[:, 1] * k

    def _paint_details(self, p, cx, cy, r, primary, accent, bg, amp):
        """The robot's glowing details: ear rings, seams, neck rings, collar, chest plate and core light."""
        if not hasattr(self, '_m_head'):
            return
        p.setBrush(Qt.BrushStyle.NoBrush)
        head_c = np.array([0.0, 0.05, -0.12], dtype=np.float32)
        pulse = 0.75 + 0.25 * math.sin(self._t * 2.2) + 0.35 * amp
        for name, (pts, bw, side) in self._curves.items():
            m = self._m_body if bw >= 0.99 else self._m_head
            q = (pts @ m.T) if bw in (0.0, 1.0) else (pts @ self._m_head.T) * (1 - bw) + (pts @ self._m_body.T) * bw
            if side:                                            # ear: faces sideways
                facing = float((np.array([side, 0.0, 0.0]) @ self._m_head.T)[2])
                if facing < -0.05:
                    continue
                vis = np.full(len(q), 0.35 + 0.65 * max(0.0, facing))
            else:
                centre = (np.array([0.0, float(pts[:, 1].mean()), -0.14]) if bw > 0.2 else head_c)
                c2 = centre @ (self._m_body if bw > 0.2 else self._m_head).T
                d = q - c2
                vis = d[:, 2] / np.maximum(np.linalg.norm(d, axis=1), 1e-6)
            X, Y = self._project(q, cx, cy, r)
            core = name.endswith('_core')
            if core or name == 'chest_core':
                if vis.mean() < 0.1:
                    continue
                poly = QPolygonF([QPointF(float(a), float(b)) for a, b in zip(X, Y)])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(_c(accent, 60 * pulse)))
                br = poly.boundingRect()
                p.drawEllipse(br.center(), br.width() * 0.9, br.height() * 0.9)       # glow
                p.setBrush(QBrush(_c(accent, 230 * min(1.0, pulse))))
                p.drawPolygon(poly)
                p.setBrush(Qt.BrushStyle.NoBrush)
                continue
            bright = name.startswith('ear') or name in ('collar',)
            hair = name.startswith('hair')
            col = accent if bright else primary
            top = 200 if bright else (85 if hair else 150)
            width = 2.0 if bright else (1.0 if hair else 1.4)
            seg_vis = np.minimum(vis[:-1], vis[1:])
            buckets: dict = {}
            for i in np.flatnonzero(seg_vis > 0.05):
                level = min(3, int(seg_vis[i] * 1.6 * 4))
                buckets.setdefault(level, []).append(QLineF(float(X[i]), float(Y[i]), float(X[i + 1]), float(Y[i + 1])))
            for level, lines in buckets.items():       # one draw call per brightness level
                p.setPen(QPen(_c(col, top * (level + 1) / 4), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLines(lines)

    def _paint_surface(self, p: QPainter, xs, ys, norms, verts,
                       primary: QColor, bg: QColor, amp: float) -> None:
        """Fill the camera-facing triangles so the head reads as a lit volume."""
        a, b, c = self._fa, self._fb, self._fc

        # Flat normals, taken from each triangle's own posed geometry — NOT the
        # averaged vertex normals. Averaging smears the nose, lips and brow
        # relief into their neighbours and renders the face as a blank egg;
        # per-facet normals are exactly what makes the anatomy visible.
        fn = np.cross(verts[b] - verts[a], verts[c] - verts[a])
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)

        # Point them outwards by agreeing with the vertex normals, which were
        # oriented at build time. Flipping on the sign of n_z instead would
        # negate x and y as well and scramble the lighting into moiré.
        ref = norms[a] + norms[b] + norms[c]
        fn *= np.sign((fn * ref).sum(1))[:, None]

        nz = fn[:, 2]
        area = np.abs((xs[b] - xs[a]) * (ys[c] - ys[a])
                      - (xs[c] - xs[a]) * (ys[b] - ys[a]))
        vis = np.flatnonzero((nz > 0.015) & (area > 3.0))
        if vis.size == 0:
            return
        fn = fn[vis]
        nz = nz[vis]

        ax, ay = xs[a][vis], ys[a][vis]
        bx, by = xs[b][vis], ys[b][vis]
        cxx, cyy = xs[c][vis], ys[c][vis]

        # A rim term for the glass edge plus a key light high on the left. The
        # light leans off-axis on purpose: weight it towards the camera and
        # every front-facing facet returns the same value, which is a flat mask.
        fres = np.clip(1.0 - nz, 0.0, 2.0) ** 1.7
        lam = np.clip(fn[:, 0] * -0.55 + fn[:, 1] * 0.50 + nz * 0.52, 0.0, 1.0)
        bright = 0.26 + 0.20 * fres + 0.66 * lam ** 1.05
        bright *= (self._fade[a][vis] + self._fade[b][vis] + self._fade[c][vis]) / 3.0
        bright *= 0.78 + 0.24 * amp                # a touch darker than the lines, so the features stand out

        idx = np.clip((bright * _LUT_N).astype(np.int32), 0, _LUT_N - 1)

        # Far facets first: the neck passes behind the jaw and the head is not
        # convex around the chin.
        # Sort far-to-near, but group first: neck facets all draw before head
        # facets, because the two meshes interpenetrate and a pure depth sort
        # interleaves them into a torn seam.
        fz = (verts[a, 2][vis] + verts[b, 2][vis] + verts[c, 2][vis]) * (1.0 / 3.0)
        order = np.argsort(self._fgroup[vis] * 1000.0 + fz, kind="stable")
        tris = np.stack([ax, ay, bx, by, cxx, cyy], axis=1)[order].tolist()
        shade = idx[order].tolist()
        lut = self._lut(bg, primary)

        # Aliased fills: adjacent antialiased polygons leave hairline seams, and
        # the interior of a tiled surface has no silhouette worth smoothing —
        # the antialiased wireframe drawn afterwards covers the outline.
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        for q, sh in zip(tris, shade):
            p.setBrush(lut[sh])
            p.drawPolygon(QPolygonF([QPointF(q[0], q[1]), QPointF(q[2], q[3]),
                                     QPointF(q[4], q[5])]))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _paint_wire(self, p: QPainter, xs, ys, norms, verts,
                    primary: QColor, bg: QColor, amp: float) -> None:
        nz = norms[:, 2]
        fres = np.abs(1.0 - np.abs(nz)) ** 1.5
        if self.shaded:
            # The lit surface underneath is opaque, so back-facing edges would
            # float on top of the face — cull them and let the wire read as
            # structure lines over skin.
            # Quiet on the face itself so the features read clearly, brighter toward the silhouette.
            front = nz > -0.05
            va = np.where(front, 0.03 + 0.46 * fres ** 1.4, 0.0)
            va += 0.22 * np.exp(-((verts[:, 1] - self._scan) / 0.13) ** 2) * front
        else:
            va = np.where(nz < 0.0, 0.13 + 0.26 * fres, 0.28 + 0.72 * fres)
            va += 0.42 * np.exp(-((verts[:, 1] - self._scan) / 0.13) ** 2)
        va *= self._fade * (0.80 + 0.45 * amp)

        ea = 0.5 * (va[self._e0] + va[self._e1])
        keep = np.flatnonzero(ea > _MIN_ALPHA)
        if keep.size == 0:
            return

        # Sort by opacity bucket once so each bucket is a contiguous *slice* of
        # one QLineF list; masking and rebuilding per bucket cost more than the
        # drawing itself.
        bucket = np.clip((ea[keep] * _BUCKETS).astype(np.int32), 0, _BUCKETS - 1)
        order = np.argsort(bucket, kind="stable")
        keep = keep[order]
        bounds = np.searchsorted(bucket[order], np.arange(_BUCKETS + 1))

        e0, e1 = self._e0[keep], self._e1[keep]
        quad = np.stack([xs[e0], ys[e0], xs[e1], ys[e1]], axis=1).tolist()
        lines = [QLineF(q[0], q[1], q[2], q[3]) for q in quad]

        skin = _blend(bg, primary, 132) if self.shaded else bg
        p.setBrush(Qt.BrushStyle.NoBrush)
        for b in range(_BUCKETS):
            lo, hi = int(bounds[b]), int(bounds[b + 1])
            if hi <= lo:
                continue
            seg = lines[lo:hi]
            a = 255.0 * min(1.0, (b + 0.5) / _BUCKETS)
            if self.shaded:
                # These sit on lit skin, so pre-mix against a representative
                # *skin* tone rather than the background — same fast opaque
                # path, and the lines still read as highlights over the face.
                p.setPen(QPen(_blend(skin, primary, a * 0.75), 1.0))
            else:
                p.setPen(QPen(_blend(bg, primary, a), 1.0))
            p.drawLines(seg)

    def _ring(self, xs, ys, idx) -> QPolygonF:
        return QPolygonF([QPointF(float(x), float(y))
                          for x, y in zip(xs[idx], ys[idx])])

    def _paint_features(self, p: QPainter, xs, ys, norms, r: float,
                        primary: QColor, accent: QColor, bg: QColor,
                        amp: float) -> None:
        """Eyes, brows and the mouth cavity, drawn from the real landmark rings.

        The canonical model's eyes and lips are closed skin — the geometry gives
        the *shape* of the lids and mouth but no opening, so the openings are
        painted here, exactly on the landmarks that bound them.
        """
        face = max(0.0, math.cos(self._yaw) * math.cos(self._pitch)) ** 2
        if face < 0.02:
            return

        lm = self._lm
        vis = 1.0 - self._blink

        # ── eyes ────────────────────────────────────────────────────────────
        for key in ("eye_l", "eye_r"):
            idx = lm[key]
            ex, ey = xs[idx], ys[idx]
            mid_y = float(ey.mean())
            g = self._g
            wink = g['wink_l'] if key == 'eye_l' else g['wink_r']
            open_k = max(0.04, vis * max(0.05, self._lids + g['lids']) * (1.0 - 0.96 * min(1.0, wink)))
            squint = max(0.0, min(1.0, self._squint + g['squint']))
            upper = ey < mid_y                              # screen y grows downwards
            # the upper lid follows openness; the lower lid rises with a real smile
            ey = np.where(upper, mid_y + (ey - mid_y) * open_k,
                          mid_y + (ey - mid_y) * open_k * (1.0 - 0.55 * squint))
            poly = QPolygonF([QPointF(float(a), float(b)) for a, b in zip(ex, ey)])

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_blend(bg, primary, 14)))       # socket shadow
            p.drawPolygon(poly)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_c(primary, 245 * face), 1.9))      # lid line
            p.drawPolygon(poly)

            if vis > 0.35 and open_k > 0.15:
                br = poly.boundingRect()
                gx = br.center().x() + self._gaze[0] * br.width() * 0.16
                gy = br.center().y() + self._gaze[1] * br.height() * 0.20
                cpt = QPointF(gx, gy)
                rad = br.width() * 0.19                     # a real-sized iris, cut by the lids like a real one
                p.save()
                clip = QPainterPath()
                clip.addPolygon(poly)
                p.setClipPath(clip)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(_c(accent, (150 + 60 * amp) * face * vis)))
                p.drawEllipse(cpt, rad, rad)                  # iris
                p.setBrush(QBrush(_c(accent, 245 * face * vis)))
                p.setBrush(QBrush(_blend(bg, accent, 90)))
                p.drawEllipse(cpt, rad * 0.45, rad * 0.45)    # pupil
                p.setBrush(QBrush(_c(accent, 245 * face * vis)))
                p.drawEllipse(cpt, rad * 0.22, rad * 0.22)    # glowing core
                p.setBrush(QBrush(QColor(255, 255, 255, int(220 * face * vis))))
                p.drawEllipse(QPointF(gx - rad * 0.28, gy - rad * 0.30), rad * 0.16, rad * 0.16 * vis)   # catch-light
                p.restore()

        # ── nose: the bridge and the nostril line, so the profile reads ──────
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary, 120 * face), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(self._ring(xs, ys, np.array([168, 6, 197, 195, 5, 4])))
        p.setPen(QPen(_c(primary, 200 * face), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(self._ring(xs, ys, np.array([129, 98, 97, 2, 326, 327, 358])))
        # ── forehead sensor ───────────────────────────────────────────────
        sx, sy = float(xs[151]), float(ys[151])
        sp = 0.6 + 0.4 * math.sin(self._t * 1.7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_c(accent, 70 * sp * face)))
        p.drawEllipse(QPointF(sx, sy), r * 0.035, r * 0.035)
        p.setBrush(QBrush(_c(accent, 240 * face)))
        p.drawEllipse(QPointF(sx, sy), r * 0.013, r * 0.013)

        # ── brows ───────────────────────────────────────────────────────────
        p.setBrush(Qt.BrushStyle.NoBrush)
        glow = QColor(primary)
        for width, alpha in ((6.0, 45), (3.2, 245)):        # a soft glow under a bold brow line
            p.setPen(QPen(_c(glow, alpha * face), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for key in ("brow_l", "brow_r"):
                p.drawPolyline(self._ring(xs, ys, lm[key]))

        # ── mouth ───────────────────────────────────────────────────────────
        inner = self._ring(xs, ys, lm["lips_in"])
        open_h = inner.boundingRect().height()

        p.setPen(Qt.PenStyle.NoPen)
        if self._mouth > 0.02:
            # The cavity is dark but never pure black — a black oval on a glowing
            # head reads as a hole, not a mouth. Tinting it with the theme keeps
            # it part of the hologram.
            p.setBrush(QBrush(_blend(bg, primary, 16 + 26 * self._mouth)))
            p.drawPolygon(inner)

            # Upper teeth: a bright strip hanging from the upper lip. It is the
            # single cheapest thing that makes an open mouth look like speech.
            ux, uy = xs[self._lip_up], ys[self._lip_up]
            th = open_h * 0.30
            pts = [QPointF(float(x), float(y)) for x, y in zip(ux, uy)]
            pts += [QPointF(float(x), float(y) + th)
                    for x, y in zip(ux[::-1], uy[::-1])]
            p.setBrush(QBrush(_blend(bg, primary, 150 + 60 * self._mouth)))
            p.drawPolygon(QPolygonF(pts))

            # A warm pool at the back of the throat, strongest when wide open.
            p.setBrush(QBrush(_c(accent, 40 * self._mouth * face)))
            p.drawPolygon(inner)

        # the lips as a solid plate, a shade brighter than the skin
        outer = self._ring(xs, ys, lm["lips_out"])
        path = QPainterPath(); path.addPolygon(outer); path.closeSubpath()
        if self._mouth > 0.02:
            hole = QPainterPath(); hole.addPolygon(inner); hole.closeSubpath()
            path = path.subtracted(hole)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_c(primary, 70 * face)))
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary, 50 * face), 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(inner)                       # glow along the lip seam: the line that smiles or frowns
        p.setPen(QPen(_c(primary, 250 * face), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(inner)                       # lip edge
        p.setPen(QPen(_c(primary, 170 * face), 1.5))
        p.drawPolygon(self._ring(xs, ys, lm["lips_out"]))
