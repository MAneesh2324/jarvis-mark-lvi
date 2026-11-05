"""Who the user is talking to: JARVIS, or someone else in the room or on a call.

The model already judges each sentence by its content (proactive audio plus the [WHO YOU ANSWER]
rules). This adds a signal content alone cannot give: a second voice. The owner's voice profile
(core/owner_guard.py) tells the owner apart from everyone else, so when another person's voice is
heard, a conversation with someone else is going on. JARVIS is told so privately once, and told
again when that voice has been quiet for a while, instead of guessing from words alone.
"""
from __future__ import annotations

import time

OTHER_WINDOW = 45.0          # seconds a second voice keeps the room "in conversation"

ON_NOTE = ('[Private context from JARVIS\'s voice sense, not spoken by the user: a second voice is in the room — '
           'the user is talking with someone else, in person or on a call. That conversation is not for you. '
           'Stay silent unless the user turns to you: says your name, asks you something directly, or follows up '
           'on what you just said. Never comment on what they said to each other.]')
OFF_NOTE = ('[Private context from JARVIS\'s voice sense: the other voice has gone quiet. Answer the user normally '
            'again when they speak to you.]')


def other_voice(verdict: dict | None) -> bool:
    """True when a voice-guard verdict says this turn was someone other than the owner."""
    if not verdict or 'result' not in verdict:
        return False
    if verdict['result'] == 'stranger':
        return True
    return verdict['result'] == 'uncertain' and float(verdict.get('score', 1)) < 0.30 \
        and float(verdict.get('seconds', 0)) >= 1.5


class RoomSense:
    def __init__(self):
        self.other_at = -1e9
        self.active = False

    def heard(self, verdict: dict | None, now: float | None = None) -> str | None:
        """After each spoken turn. Returns a private note when the room changes, else None."""
        now = time.monotonic() if now is None else now
        if other_voice(verdict):
            self.other_at = now
        return self._update(now)

    def tick(self, now: float | None = None) -> str | None:
        """Called now and then: notices that the other voice has gone quiet."""
        return self._update(time.monotonic() if now is None else now)

    def _update(self, now: float) -> str | None:
        active = now - self.other_at < OTHER_WINDOW
        if active == self.active:
            return None
        self.active = active
        return ON_NOTE if active else OFF_NOTE
