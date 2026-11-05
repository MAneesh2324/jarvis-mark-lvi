"""One place for JARVIS to tell the user something it noticed on its own.

Background features (research agents, wellbeing reminders, the owner guard, the
phone link) call send(); main.py registers the sinks: the activity log, the
voice, and the phone. A failing sink never stops the others.
"""
from __future__ import annotations

import threading
import time

_sinks: list = []
_recent: dict[str, float] = {}
_lock = threading.Lock()


def register(fn) -> None:
    """fn(kind, text, speak, urgent) — called for every notification."""
    if fn not in _sinks:
        _sinks.append(fn)


def unregister(fn) -> None:
    if fn in _sinks:
        _sinks.remove(fn)


def send(kind: str, text: str, speak: bool = False, urgent: bool = False, dedupe_seconds: float = 0) -> bool:
    """Deliver to every sink. dedupe_seconds drops the same kind+text repeated within that window."""
    text = str(text or '').strip()
    if not text:
        return False
    if dedupe_seconds:
        key = kind + '|' + text
        with _lock:
            now = time.monotonic()
            if now - _recent.get(key, -1e9) < dedupe_seconds:
                return False
            _recent[key] = now
    delivered = False
    for fn in list(_sinks):
        try:
            fn(kind, text, speak, urgent)
            delivered = True
        except Exception as exc:
            print(f'[Notify] sink failed: {exc}')
    if not _sinks:
        print(f'[Notify] {kind}: {text}')
    return delivered
