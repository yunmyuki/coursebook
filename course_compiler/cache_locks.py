"""Coalesce identical concurrent requests without serializing different pages."""
import threading
import weakref
_guard=threading.Lock()
_locks=weakref.WeakValueDictionary()

def request_lock(key):
    with _guard:
        lock=_locks.get(key)
        if lock is None:lock=threading.Lock();_locks[key]=lock
        return lock
