from policyengine_api.utils.streaming_json import (
    STREAMING_CHUNK_BYTES,
    STREAMING_THRESHOLD_BYTES,
    iter_body_chunks,
    should_stream_body,
)


def test_should_stream_body_only_at_threshold():
    assert not should_stream_body(b"x" * (STREAMING_THRESHOLD_BYTES - 1))
    assert should_stream_body(b"x" * STREAMING_THRESHOLD_BYTES)


def test_iter_body_chunks_reassembles_exactly():
    body = bytes(range(256)) * 4 * 1024  # 1 MiB, non-uniform content
    chunks = list(iter_body_chunks(body, 100_000))
    assert b"".join(chunks) == body
    assert all(len(chunk) <= 100_000 for chunk in chunks)


def test_iter_body_chunks_default_chunk_size_covers_body():
    body = b"y" * (STREAMING_CHUNK_BYTES * 2 + 5)
    chunks = list(iter_body_chunks(body))
    assert len(chunks) == 3
    assert b"".join(chunks) == body
