"""In-memory timings only: no prompts, transcripts, or credentials."""
from collections import deque
from threading import Lock
from time import monotonic
import statistics

_lock = Lock()
_samples = deque(maxlen=200)
_pending_typed = None


def record(kind, name, seconds):
    with _lock:
        _samples.append({'kind': kind, 'name': name, 'milliseconds': round(max(0, seconds) * 1000, 1)})


def begin_typed_response():
    global _pending_typed
    with _lock:
        _pending_typed = monotonic()


_pending_voice = None


def voice_heard():
    """Each time a piece of the user's spoken words arrives; the last one is about when they stopped."""
    global _pending_voice
    with _lock:
        _pending_voice = monotonic()


def first_audio():
    global _pending_typed, _pending_voice
    with _lock:
        started, _pending_typed = _pending_typed, None
        heard, _pending_voice = _pending_voice, None
    if started is not None:
        record('response', 'typed_request_to_first_audio_received', monotonic() - started)
    elif heard is not None:
        record('response', 'speech_to_first_audio_received', monotonic() - heard)


def cancel_response():
    global _pending_typed
    with _lock:
        _pending_typed = None


def snapshot():
    with _lock:
        samples = list(_samples)
    groups = {}
    for item in samples:
        groups.setdefault((item['kind'], item['name']), []).append(item['milliseconds'])
    stats = [{'kind': kind, 'name': name, 'samples': len(values),
              'median_ms': round(statistics.median(values), 1), 'last_ms': values[-1],
              'max_ms': max(values)} for (kind, name), values in groups.items()]
    return {'timings': stats, 'recent': samples[-15:],
            'measurement': 'Typed response time is an estimate from sending text to the next audio received, before speaker playback; overlapping audio can affect it. Voice end-of-speech latency is not measured. Timings reset on restart; at most 200 samples are kept.'}
