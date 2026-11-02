"""One ordered, bounded disk-write queue, separate from the audio executor."""
import atexit
import queue
import threading
import time
from core.performance import record


class BackgroundWriter:
    def __init__(self, on_error=None, capacity=256):
        self._queue = queue.Queue(maxsize=capacity)
        self._on_error = on_error or (lambda exc: None)
        self._thread = threading.Thread(target=self._run, daemon=True, name='conversation-writer')
        self._thread.start()
        atexit.register(self.flush, 1.5)

    def submit(self, fn, *args):
        try:
            self._queue.put_nowait((fn, args, True))
            return True
        except queue.Full:
            self._report_error(RuntimeError('Conversation saving queue is full; this turn could not be saved.'))
            return False

    def _report_error(self, exc):
        try:
            self._on_error(exc)
        except Exception:
            pass  # A destroyed UI must not kill the disk writer.

    def _run(self):
        while True:
            fn, args, measure = self._queue.get()
            start = time.monotonic()
            try:
                fn(*args)
            except Exception as exc:
                self._report_error(exc)
            finally:
                if measure:
                    record('storage', 'conversation_write', time.monotonic() - start)
                self._queue.task_done()

    def flush(self, timeout=2.0):
        """Wait for a barrier; never let shutdown wait indefinitely."""
        deadline = time.monotonic() + timeout
        barrier = threading.Event()
        try:
            self._queue.put((barrier.set, (), False), timeout=max(0, deadline - time.monotonic()))
        except queue.Full:
            return False
        return barrier.wait(max(0, deadline - time.monotonic()))
