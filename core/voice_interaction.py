"""Voice barge-in: pause the moment the user starts talking, stop if they keep talking.

How a person handles being interrupted, in three steps:

  1. A hint of a voice (~130 ms that the echo guard says is not our own audio)
     → PAUSE. JARVIS holds its sentence instead of talking over the user.
     Pausing also removes the echo, which makes the next decision far easier.
  2. The voice continues (the echo guard's required run, ~0.3-0.8 s depending on
     the room; short gaps between syllables do not reset it)
     → INTERRUPT. The answer is dropped and what the user said so far is sent
     to the model, so nothing they said is lost.
  3. It was a cough, a door, a keystroke: nothing more for RESUME_AFTER seconds
     → RESUME exactly where it paused.

On by default. /voiceinterrupt off (or the Mission Control checkbox) turns it off.
"""
from collections import deque
from pathlib import Path
import json
import time

CONFIG = Path(__file__).resolve().parent.parent / 'config' / 'voice-interaction.json'
_enabled = None

PAUSE_BLOCKS = 2      # ~130 ms of a different voice → hold the speech
GAP_TOLERANCE = 3     # non-voice blocks (~190 ms) allowed between syllables
RESUME_AFTER = 0.7    # seconds of quiet while paused → it was not an interruption
MAX_PAUSE = 2.5       # never hold an answer longer than this without a decision


def enabled():
    global _enabled
    if _enabled is None:
        try:
            _enabled = bool(json.loads(CONFIG.read_text()).get('voice_interrupt', True))
        except (OSError, ValueError):
            _enabled = True
    return _enabled


def set_enabled(value):
    global _enabled
    from core.mission_store import write_file
    _enabled = bool(value)
    write_file(CONFIG, json.dumps({'voice_interrupt': _enabled}))
    return _enabled


class VoiceInterrupt:
    """Fed every microphone block while JARVIS is speaking.

    feed() returns (action, blocks): action is 'none', 'pause', 'resume' or
    'interrupt'; blocks is the user's audio so far, only for 'interrupt'.
    """

    def __init__(self):
        self.blocks = deque(maxlen=48)   # ~3 s of the user's words
        self.hits = 0
        self.gaps = 0
        self.paused = False
        self.paused_at = 0.0
        self.last_voice = 0.0

    def reset(self):
        self.blocks.clear()
        self.hits = self.gaps = 0
        self.paused = False

    def _resume(self):
        self.reset()
        return 'resume', []

    def feed(self, pcm, sample_rate, level, echo, allowed=True, now=None):
        now = time.monotonic() if now is None else now
        if not allowed or not enabled():
            return self._resume() if self.paused else (self.reset() or ('none', []))
        try:
            voice = echo.is_user_speech(pcm, sample_rate, level)
        except Exception:
            voice = False
        if voice:
            self.hits += 1
            self.gaps = 0
            self.last_voice = now
            self.blocks.append(pcm.tobytes())
            if self.hits >= echo.required_blocks:
                words = list(self.blocks)
                self.reset()
                return 'interrupt', words
            if not self.paused and self.hits >= PAUSE_BLOCKS:
                self.paused, self.paused_at = True, now
                return 'pause', []
            return 'none', []
        # Not a voice in this block.
        if self.paused:
            self.blocks.append(pcm.tobytes())   # keep the gaps, so the model hears whole words
            if now - self.last_voice >= RESUME_AFTER or now - self.paused_at >= MAX_PAUSE:
                return self._resume()
            return 'none', []
        if self.hits:
            self.gaps += 1
            self.blocks.append(pcm.tobytes())
            if self.gaps > GAP_TOLERANCE:
                self.reset()
        return 'none', []
