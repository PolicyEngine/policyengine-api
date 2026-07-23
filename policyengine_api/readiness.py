"""Tracks whether the API has finished warming up and can serve real requests.

The API builds its tax-benefit systems at import, but the *first* calculate on a
fresh worker still pays a large one-time cost to compile the per-simulation
machinery (parameter-tree materialisation, the formula graph). The Cloud Run
startup path runs a warmup calculate before serving and toggles this flag around
it, so ``/readiness-check`` only reports ready once that cost has been paid.

Defaults to ready: contexts that do not run a startup warmup (App Engine, tests,
local tooling) keep their previous behaviour of reporting ready immediately.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_ready = True


def mark_not_ready() -> None:
    """Report not-ready — call before running the startup warmup."""
    global _ready
    with _lock:
        _ready = False


def mark_ready() -> None:
    """Report ready — call once the startup warmup has completed."""
    global _ready
    with _lock:
        _ready = True


def is_ready() -> bool:
    """Whether the service is warmed up and can serve a real request quickly."""
    with _lock:
        return _ready
