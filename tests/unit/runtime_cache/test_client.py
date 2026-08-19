"""Lazy shared Redis client construction tests."""

import redis

from policyengine_api.runtime_cache.client import build_runtime_cache_client
from policyengine_api.runtime_cache.settings import load_runtime_cache_settings

from .test_settings import TEST_CA_CERT


def test_tls_client_receives_memorystore_ca_in_memory(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_from_url(url: str, **kwargs):
        captured.update(url=url, **kwargs)
        return sentinel

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    settings = load_runtime_cache_settings(
        {
            "RUNTIME_CACHE_MODE": "deployed",
            "RUNTIME_CACHE_URL": "rediss://:secret@10.0.0.2:6378/0",
            "RUNTIME_CACHE_CA_CERT": TEST_CA_CERT,
            "RUNTIME_CACHE_ENVIRONMENT": "production",
            "RUNTIME_CACHE_SERVICE": "api",
        }
    )

    assert build_runtime_cache_client(settings) is sentinel
    assert captured["ssl_cert_reqs"] == "required"
    assert captured["ssl_ca_data"] == TEST_CA_CERT
    assert captured["max_connections"] == 20
    assert captured["socket_connect_timeout"] == 1.0
    assert captured["socket_timeout"] == 2.0
