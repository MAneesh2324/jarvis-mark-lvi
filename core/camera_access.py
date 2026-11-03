"""One camera owner at a time across snapshots, previews and local gestures."""
from contextlib import contextmanager
import threading
_lock=threading.RLock();_owner=''
def acquire(owner):
 global _owner
 if not _lock.acquire(blocking=False):raise RuntimeError('Camera is busy with '+(_owner or 'another camera feature')+'. Stop it before enabling another camera mode.')
 previous=_owner;_owner=owner;return previous
def release(previous=''):
 global _owner
 _owner=previous;_lock.release()
@contextmanager
def claim(owner):
 previous=acquire(owner)
 try:yield
 finally:release(previous)
