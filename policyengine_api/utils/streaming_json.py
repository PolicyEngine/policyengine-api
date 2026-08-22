"""Chunked delivery for JSON bodies too large to send with Content-Length.

Cloud Run rejects HTTP/1 responses above 32 MiB unless they use
``Transfer-Encoding: chunked`` or another streaming mechanism
(https://docs.cloud.google.com/run/quotas). ``/us/metadata`` serializes to
~70 MB, so clients that do not negotiate gzip received an empty 500 from the
Google Frontend. Bodies above the threshold are therefore streamed; smaller
bodies keep their exact current framing, including Content-Length.
"""

from __future__ import annotations

from collections.abc import Iterator

STREAMING_THRESHOLD_BYTES = 20 * 1024 * 1024
STREAMING_CHUNK_BYTES = 1024 * 1024


def should_stream_body(body: bytes) -> bool:
    return len(body) >= STREAMING_THRESHOLD_BYTES


def iter_body_chunks(
    body: bytes, chunk_size: int = STREAMING_CHUNK_BYTES
) -> Iterator[bytes]:
    for start in range(0, len(body), chunk_size):
        yield body[start : start + chunk_size]
