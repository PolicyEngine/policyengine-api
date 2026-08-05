"""Response primitives that preserve API v1 serialization behavior."""

from __future__ import annotations

import json

from policyengine_api.json_types import JSONValue
from starlette.responses import Response


class LegacyJSONResponse(Response):
    """Serialize once with the same JSON encoder used by legacy metadata."""

    media_type = "application/json"

    def render(self, content: JSONValue) -> bytes:
        return json.dumps(content).encode("utf-8")
