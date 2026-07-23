"""ASGI entrypoint for the Stage 2 FastAPI compatibility shell."""

from __future__ import annotations

import os

from policyengine_api.api import app as flask_app
from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.readiness import mark_not_ready, mark_ready
from policyengine_api.warmup import run_startup_warmup

app = application = create_asgi_app(flask_app)

# Warm the simulation machinery before this worker serves traffic. Building the
# tax-benefit systems at import does not compile the per-simulation machinery, so
# the first real calculate on a fresh worker would otherwise take ~2 minutes.
# Running a throwaway calculate here moves that cost off the first request and
# lets /readiness-check report readiness honestly. Synchronous by design: the
# worker does not serve until it is warm (liveness is unaffected). Set
# POLICYENGINE_API_STARTUP_WARMUP=0 to skip it (e.g. for a fast local boot).
if os.environ.get("POLICYENGINE_API_STARTUP_WARMUP", "1") != "0":
    mark_not_ready()
    try:
        run_startup_warmup()
    finally:
        mark_ready()
