"""Fail-closed runtime-cache configuration tests."""

import pytest

from policyengine_api.runtime_cache.settings import (
    RUNTIME_CACHE_CA_CERT,
    RUNTIME_CACHE_ENVIRONMENT,
    RUNTIME_CACHE_MODE,
    RUNTIME_CACHE_SERVICE,
    RUNTIME_CACHE_URL,
    RuntimeCacheConfigurationError,
    load_runtime_cache_settings,
)


TEST_CA_CERT = """-----BEGIN CERTIFICATE-----
stage-8-test-ca
-----END CERTIFICATE-----"""


def test_unselected_local_or_test_environment_is_disabled_without_fallback() -> None:
    settings = load_runtime_cache_settings({})
    assert settings.enabled is False
    assert settings.url is None


def test_platform_marker_selects_deployed_mode_and_requires_configuration() -> None:
    with pytest.raises(RuntimeCacheConfigurationError, match=RUNTIME_CACHE_URL):
        load_runtime_cache_settings({"K_SERVICE": "policyengine-api"})


@pytest.mark.parametrize("mode", ["disabled", "local"])
def test_deployed_platform_marker_rejects_non_deployed_cache_mode(
    mode: str,
) -> None:
    with pytest.raises(RuntimeCacheConfigurationError, match="must be deployed"):
        load_runtime_cache_settings(
            {
                "K_SERVICE": "policyengine-api",
                RUNTIME_CACHE_MODE: mode,
            }
        )


def test_unknown_development_cache_mode_is_rejected() -> None:
    with pytest.raises(
        RuntimeCacheConfigurationError, match="disabled, local, or deployed"
    ):
        load_runtime_cache_settings({RUNTIME_CACHE_MODE: "dev"})


@pytest.mark.parametrize(
    "url",
    [
        "redis://:password@10.0.0.2:6379/0",
        "rediss://:password@127.0.0.1:6379/0",
        "rediss://10.0.0.2:6379/0",
        "rediss://:password@10.0.0.2/0",
        "rediss://:password@10.0.0.2:6379/1",
    ],
)
def test_deployed_mode_requires_tls_auth_nonlocal_host_port_and_database_zero(
    url: str,
) -> None:
    with pytest.raises(RuntimeCacheConfigurationError):
        load_runtime_cache_settings(
            {
                RUNTIME_CACHE_MODE: "deployed",
                RUNTIME_CACHE_URL: url,
                RUNTIME_CACHE_ENVIRONMENT: "production",
                RUNTIME_CACHE_SERVICE: "api",
            }
        )


def test_valid_deployed_configuration_is_secret_safe() -> None:
    secret = "do-not-print-cache-password"
    ca_secret = "do-not-print-cache-ca"
    settings = load_runtime_cache_settings(
        {
            RUNTIME_CACHE_MODE: "deployed",
            RUNTIME_CACHE_URL: f"rediss://:{secret}@10.0.0.2:6378/0",
            RUNTIME_CACHE_CA_CERT: TEST_CA_CERT.replace("stage-8-test-ca", ca_secret),
            RUNTIME_CACHE_ENVIRONMENT: "production",
            RUNTIME_CACHE_SERVICE: "api",
        }
    )
    assert settings.enabled is True
    assert settings.tls is True
    assert secret not in repr(settings)
    assert ca_secret not in repr(settings)


def test_deployed_tls_configuration_requires_a_valid_ca_bundle() -> None:
    values = {
        RUNTIME_CACHE_MODE: "deployed",
        RUNTIME_CACHE_URL: "rediss://:password@10.0.0.2:6378/0",
        RUNTIME_CACHE_ENVIRONMENT: "production",
        RUNTIME_CACHE_SERVICE: "api",
    }
    with pytest.raises(RuntimeCacheConfigurationError, match=RUNTIME_CACHE_CA_CERT):
        load_runtime_cache_settings(values)

    with pytest.raises(RuntimeCacheConfigurationError, match="PEM"):
        load_runtime_cache_settings(
            {**values, RUNTIME_CACHE_CA_CERT: "not-a-certificate"}
        )


def test_local_mode_requires_explicit_local_url_and_namespace() -> None:
    settings = load_runtime_cache_settings(
        {
            RUNTIME_CACHE_MODE: "local",
            RUNTIME_CACHE_URL: "redis://127.0.0.1:6379/0",
            RUNTIME_CACHE_ENVIRONMENT: "local-dev",
            RUNTIME_CACHE_SERVICE: "api",
        }
    )
    assert settings.enabled is True
    assert settings.tls is False

    with pytest.raises(RuntimeCacheConfigurationError, match="local endpoint"):
        load_runtime_cache_settings(
            {
                RUNTIME_CACHE_MODE: "local",
                RUNTIME_CACHE_URL: "redis://cache.example.com:6379/0",
                RUNTIME_CACHE_ENVIRONMENT: "local-dev",
                RUNTIME_CACHE_SERVICE: "api",
            }
        )
