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

from policyengine_api.content_encoding import accepts_gzip
from policyengine_api.fastapi_routes.v2.metadata.common import (
    CACHE_HEADER_DESCRIPTIONS,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.metadata.types import (
        MetadataParameterSearchFile,
    )

_GZIP_ETAG_SUFFIX: Final = "-gzip"

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


def search_file_entity_tag(content_sha256: str, *, accept_encoding: str | None) -> str:
    """Return the ETag of the representation the request accepts."""
    if accepts_gzip(accept_encoding):
        return f'"{content_sha256}{_GZIP_ETAG_SUFFIX}"'
    return f'"{content_sha256}"'


def parameter_search_file_response(
    search_file: MetadataParameterSearchFile,
    *,
    accept_encoding: str | None,
) -> Response:
    """Return the file in the encoding the request accepts, with its ETag.

    It decides with the application's gzip middleware's rule, and the gzip
    form names its Content-Encoding, so the middleware never re-encodes it.
    """
    entity_tag = search_file_entity_tag(
        search_file.content_sha256, accept_encoding=accept_encoding
    )
    if accepts_gzip(accept_encoding):
        return Response(
            content=search_file.compressed_content,
            media_type="application/json",
            headers={"ETag": entity_tag, "Content-Encoding": "gzip"},
        )
    return Response(
        content=gzip.decompress(search_file.compressed_content),
        media_type="application/json",
        headers={"ETag": entity_tag},
    )
