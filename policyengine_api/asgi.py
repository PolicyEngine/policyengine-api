"""ASGI entrypoint for the Stage 2 FastAPI compatibility shell."""

from __future__ import annotations

import os

from policyengine_api.api import app as flask_app
from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.readiness import mark_not_ready, mark_ready
from policyengine_api.warmup import run_startup_warmup

app = application = create_asgi_app(flask_app)

# Warm the simulation machinery before serving (see policyengine_api.warmup).
# POLICYENGINE_API_STARTUP_WARMUP=0 skips it.
if os.environ.get("POLICYENGINE_API_STARTUP_WARMUP", "1") != "0":
    mark_not_ready()
    try:
        run_startup_warmup()
    finally:
        mark_ready()
