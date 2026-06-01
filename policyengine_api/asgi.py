"""ASGI entrypoint for the Stage 2 FastAPI compatibility shell."""

from __future__ import annotations

from policyengine_api.api import app as flask_app
from policyengine_api.asgi_factory import create_asgi_app


app = application = create_asgi_app(flask_app)
