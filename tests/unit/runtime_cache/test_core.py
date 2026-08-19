"""Versioned envelope, key, fake, and claim behavior."""

from unittest.mock import MagicMock

import pytest

from policyengine_api.runtime_cache.claims import ExpiringClaimStore
from policyengine_api.runtime_cache.core import (
    CacheCoordinationError,
    CacheNamespace,
    RecoverableJSONCache,
    decode_envelope,
    encode_envelope,
    jittered_ttl,
)
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend


def test_keys_include_namespace_family_schema_and_every_input() -> None:
    namespace = CacheNamespace("staging", "api")
    first = namespace.key("computed", 1, {"country": "us", "policy": 1})
    reordered = namespace.key("computed", 1, {"policy": 1, "country": "us"})
    changed_input = namespace.key("computed", 1, {"country": "us", "policy": 2})
    changed_schema = namespace.key("computed", 2, {"country": "us", "policy": 1})

    assert first == reordered
    assert first.startswith("policyengine:staging:api:computed:v1:")
    assert len({first, changed_input, changed_schema}) == 3


def test_envelopes_fail_closed_on_family_schema_or_encoding_mismatch() -> None:
    encoded = encode_envelope("computed", 1, {"ok": True})
    assert decode_envelope(encoded, family="computed", schema_version=1) == {"ok": True}
    assert decode_envelope(encoded, family="other", schema_version=1) is None
    assert decode_envelope(encoded, family="computed", schema_version=2) is None
    assert decode_envelope("{broken", family="computed", schema_version=1) is None


def test_completed_result_ttl_jitter_is_bounded_and_subtract_only() -> None:
    def choose_minimum(lower: int, _upper: int) -> int:
        return lower

    def choose_maximum(_lower: int, upper: int) -> int:
        return upper

    assert jittered_ttl(100, choose_reduction=choose_minimum) == 100
    assert jittered_ttl(100, choose_reduction=choose_maximum) == 90
    assert jittered_ttl(9, choose_reduction=choose_maximum) == 9

    with pytest.raises(ValueError, match="positive"):
        jittered_ttl(0)
    with pytest.raises(ValueError, match="fraction"):
        jittered_ttl(100, jitter_fraction=1)


def test_recoverable_cache_applies_jitter_to_completed_result_writes(
    monkeypatch,
) -> None:
    import policyengine_api.runtime_cache.core as module

    monkeypatch.setattr(module, "jittered_ttl", lambda _ttl: 91)
    backend = InMemoryCacheBackend()
    cache = RecoverableJSONCache(
        backend,
        CacheNamespace("test", "api"),
        family="result",
        schema_version=1,
        ttl_seconds=100,
    )
    inputs = {"input": 1}

    assert cache.set(inputs, {"answer": 42})
    assert backend._expires[cache.key(inputs)] == 91


def test_deterministic_fake_expires_values_and_recoverable_cache_misses() -> None:
    backend = InMemoryCacheBackend()
    cache = RecoverableJSONCache(
        backend,
        CacheNamespace("test", "api"),
        family="result",
        schema_version=1,
        ttl_seconds=10,
    )
    inputs = {"version": "1", "payload": {"x": 1}}
    assert cache.get(inputs) is None
    assert cache.set(inputs, {"answer": 42}) is True
    assert cache.get(inputs) == {"answer": 42}
    backend.advance(10)
    assert cache.get(inputs) is None


def test_cache_events_are_metric_ready_and_cannot_include_keys_or_values(
    monkeypatch,
) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)
    backend = InMemoryCacheBackend()
    cache = RecoverableJSONCache(
        backend,
        CacheNamespace("test", "api"),
        family="result",
        schema_version=1,
        ttl_seconds=10,
    )
    inputs = {"token": "sensitive-input"}
    payload = {"answer": "sensitive-output"}

    assert cache.get(inputs) is None
    assert cache.set(inputs, payload)
    assert cache.get(inputs) == payload

    records = [call.args[0] for call in mock_logger.log_struct.call_args_list]
    assert [record["cache_event"] for record in records] == [
        "miss",
        "write",
        "hit",
    ]
    for record in records:
        assert record["metric_name"] == "runtime_cache_operations"
        assert record["metric_value"] == 1
        assert record["cache_family"] == "result"
        assert record["latency_ms"] >= 0
        assert "sensitive-input" not in repr(record)
        assert "sensitive-output" not in repr(record)


def test_cache_connection_and_write_failures_emit_metric_events(monkeypatch) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)

    class Broken:
        def get(self, _key):
            raise OSError("unavailable")

        def set(self, _key, _value, **_kwargs):
            raise OSError("unavailable")

    cache = RecoverableJSONCache(
        Broken(),
        CacheNamespace("test", "api"),
        family="result",
        schema_version=1,
        ttl_seconds=10,
    )

    assert cache.get({"input": 1}) is None
    assert not cache.set({"input": 1}, {"output": 2})

    records = [call.args[0] for call in mock_logger.log_struct.call_args_list]
    assert [record["cache_event"] for record in records] == [
        "connection-failed",
        "write-failed",
    ]
    assert all(record["metric_value"] == 1 for record in records)
    assert all(
        call.kwargs["severity"] == "WARNING"
        for call in mock_logger.log_struct.call_args_list
    )


def test_claims_are_exclusive_expiring_and_token_safe() -> None:
    backend = InMemoryCacheBackend()
    claims = ExpiringClaimStore(backend)
    assert claims.acquire("claim", "owner-a", ttl_seconds=5) is True
    assert claims.acquire("claim", "owner-b", ttl_seconds=5) is False
    assert claims.release("claim", "owner-b") is False
    assert backend.get("claim") == "owner-a"
    backend.advance(5)
    assert claims.acquire("claim", "owner-b", ttl_seconds=5) is True
    assert claims.release("claim", "owner-b") is True


def test_claim_failures_are_coordination_errors_not_cache_misses(monkeypatch) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("policyengine_api.runtime_cache.core.logger", mock_logger)

    class Broken:
        def set(self, *_args, **_kwargs):
            raise OSError("unavailable")

        def eval(self, *_args, **_kwargs):
            raise OSError("unavailable")

    claims = ExpiringClaimStore(Broken())
    with pytest.raises(CacheCoordinationError):
        claims.acquire("secret-key-123", "secret-token-456", ttl_seconds=5)
    with pytest.raises(CacheCoordinationError):
        claims.release("secret-key-123", "secret-token-456")

    records = [call.args[0] for call in mock_logger.log_struct.call_args_list]
    assert [record["cache_event"] for record in records] == [
        "coordination-failed",
        "coordination-failed",
    ]
    assert {record["cache_operation"] for record in records} == {
        "claim-acquire",
        "claim-release",
    }
    assert all(record["metric_value"] == 1 for record in records)
    assert "secret-key-123" not in repr(records)
    assert "secret-token-456" not in repr(records)
