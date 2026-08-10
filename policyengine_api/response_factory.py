"""Factories for consistent Flask response construction."""

import json
from typing import Any

from flask import Response


def _make_error_response(
    message: object,
    status_code: int,
    *,
    include_status: bool = True,
    mimetype: str | None = "application/json",
    **payload_fields: Any,
) -> Response:
    """Build a JSON error response while preserving legacy payload variants."""
    payload = {"message": str(message), **payload_fields}
    if include_status:
        payload = {"status": "error", **payload}

    return Response(
        json.dumps(payload),
        status=status_code,
        mimetype=mimetype,
    )
