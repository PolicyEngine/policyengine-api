"""Whether the API has finished warming up and can serve real requests.

Defaults to ready, so contexts that do not run a startup warmup (App Engine,
tests, tooling) report ready immediately. The Cloud Run startup path toggles it
around the warmup (policyengine_api.warmup).
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
