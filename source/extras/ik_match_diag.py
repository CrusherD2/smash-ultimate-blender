"""Opt-in stage timings and always-on fallback reason codes for IK matching.

Timings are opt-in because the thing being measured is the thing being
optimised: a `perf_counter` pair around each of the several thousand graph
updates a match performs is not free. Reason codes are always on -- a guard
rejects at most once per match, and the case where the reason matters is
exactly the slow user rig nobody can reproduce.
"""
from contextlib import contextmanager
import os
import time

_RECORD = {'reasons': {}, 'stages': {}, 'counts': {}}
_ENABLED = None


def enabled():
    """True when SUB_IK_DIAG=1 asked for stage timings.

    Cached so the ~4,292-iteration search loop pays one dict/attribute read
    per update, never an `os.environ` lookup. `reset()` refreshes the cache
    from the environment at the start of every match, so a test that flips
    `SUB_IK_DIAG` around a `match()` call still sees the change take effect.
    A process that never calls `reset()` (e.g. importing this module without
    running a match) still gets a correct answer via this lazy fallback.
    """
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = os.environ.get('SUB_IK_DIAG') == '1'
    return _ENABLED


def reset():
    global _ENABLED
    _ENABLED = os.environ.get('SUB_IK_DIAG') == '1'
    _RECORD['reasons'] = {}
    _RECORD['stages'] = {}
    _RECORD['counts'] = {}


def record():
    """Snapshot of the current match's diagnostics."""
    return {'reasons': dict(_RECORD['reasons']),
            'stages': dict(_RECORD['stages']),
            'counts': dict(_RECORD['counts'])}


def reject(guard, code):
    """Record why `guard` declined. Returns None so guards can `return` it."""
    _RECORD['reasons'][guard] = code
    return None


def accept(guard):
    _RECORD['reasons'][guard] = 'ok'


def add(name, seconds, count=0):
    _RECORD['stages'][name] = _RECORD['stages'].get(name, 0.0) + seconds
    if count:
        _RECORD['counts'][name] = _RECORD['counts'].get(name, 0) + count


@contextmanager
def stage(name):
    """Time a coarse stage. One boolean test when diagnostics are off."""
    if not enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        add(name, time.perf_counter() - start)
