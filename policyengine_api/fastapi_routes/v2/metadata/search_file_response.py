"""HTTP representation of a catalog version's stored parameter search file.

The file is stored gzip-compressed, so a client that accepts gzip receives
the stored bytes unchanged with ``Content-Encoding: gzip``, and any other
client receives the uncompressed JSON. Each representation has its own strong
ETag, made from the SHA-256 of the uncompressed JSON (``"<sha256>"``, or
``"<sha256>-gzip"`` for the gzip one). The metadata route class
(``CacheableMetadataRoute``) then adds the cache lifetime and ``Vary`` and
answers a matching ``If-None-Match`` with 304, as for every metadata route.
"""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING, Any, Final

from starlette.responses import Response

from policyengine_api.fastapi_routes.v2.metadata.common import (
    CACHE_HEADER_DESCRIPTIONS,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.metadata.types import (
        MetadataParameterSearchFile,
    )

_GZIP_ETAG_SUFFIX: Final = "-gzip"
_GZIP_CODINGS: Final = frozenset({"gzip", "x-gzip"})

SEARCH_FILE_RESPONSE_HEADERS: Final[dict[str, dict[str, Any]]] = {
    **CACHE_HEADER_DESCRIPTIONS,
    "ETag": {
        "description": (
            "Strong tag of this representation: the SHA-256 of the uncompressed "
            'JSON, with "-gzip" appended for the gzip-encoded one.'
        ),
        "schema": {"type": "string"},
    },
    "Content-Encoding": {
        "description": "gzip when the request accepts gzip; absent otherwise.",
        "schema": {"type": "string"},
    },
}


def _quality(parameters: str) -> float:
    for parameter in parameters.split(";"):
        name, _, value = parameter.strip().partition("=")
        if name.strip().lower() == "q":
            try:
                return float(value)
            except ValueError:
                return 0.0
    return 1.0


def accepts_gzip(accept_encoding: str | None) -> bool:
    """Return whether an Accept-Encoding value accepts gzip.

    An explicit gzip entry decides; otherwise ``*`` does. A quality of 0
    refuses the coding.
    """
    wildcard_quality: float | None = None
    for entry in (accept_encoding or "").split(","):
        coding, _, parameters = entry.partition(";")
        name = coding.strip().lower()
        if name in _GZIP_CODINGS:
            return _quality(parameters) > 0
        if name == "*":
            wildcard_quality = _quality(parameters)
    return wildcard_quality is not None and wildcard_quality > 0


def parameter_search_file_response(
    search_file: MetadataParameterSearchFile,
    *,
    accept_encoding: str | None,
) -> Response:
    """Return the file in the encoding the request accepts, with its ETag."""
    if accepts_gzip(accept_encoding):
        return Response(
            content=search_file.compressed_content,
            media_type="application/json",
            headers={
                "ETag": f'"{search_file.content_sha256}{_GZIP_ETAG_SUFFIX}"',
                "Content-Encoding": "gzip",
            },
        )
    return Response(
        content=gzip.decompress(search_file.compressed_content),
        media_type="application/json",
        headers={"ETag": f'"{search_file.content_sha256}"'},
    )
