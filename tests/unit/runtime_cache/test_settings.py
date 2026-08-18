"""Fail-closed runtime-cache configuration tests."""

import pytest

from policyengine_api.runtime_cache.settings import (
    RUNTIME_CACHE_CA_CERT,
    RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE,
    RUNTIME_CACHE_ENVIRONMENT,
    RUNTIME_CACHE_MODE,
    RUNTIME_CACHE_SERVICE,
    RUNTIME_CACHE_URL,
    RUNTIME_CACHE_URL_SECRET_RESOURCE,
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


def test_app_engine_resolves_separate_secret_resources_without_echoing_them() -> None:
    url_resource = "projects/project/secrets/cache-url/versions/latest"
    ca_resource = "projects/project/secrets/cache-ca/versions/latest"
    observed: list[str] = []

    def load_secret(resource: str) -> str:
        observed.append(resource)
        if resource == url_resource:
            return "rediss://:secret@10.0.0.2:6378/0"
        if resource == ca_resource:
            return TEST_CA_CERT
        raise AssertionError(resource)

    settings = load_runtime_cache_settings(
        {
            RUNTIME_CACHE_MODE: "deployed",
            RUNTIME_CACHE_URL_SECRET_RESOURCE: url_resource,
            RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE: ca_resource,
            RUNTIME_CACHE_ENVIRONMENT: "staging",
            RUNTIME_CACHE_SERVICE: "api",
        },
        secret_loader=load_secret,
    )

    assert observed == [url_resource, ca_resource]
    assert settings.url is not None
    assert settings.ca_cert is not None


def test_runtime_cache_rejects_ambiguous_or_invalid_secret_resources() -> None:
    values = {
        RUNTIME_CACHE_MODE: "deployed",
        RUNTIME_CACHE_URL: "rediss://:secret@10.0.0.2:6378/0",
        RUNTIME_CACHE_URL_SECRET_RESOURCE: (
            "projects/project/secrets/cache-url/versions/latest"
        ),
        RUNTIME_CACHE_CA_CERT: TEST_CA_CERT,
        RUNTIME_CACHE_ENVIRONMENT: "production",
        RUNTIME_CACHE_SERVICE: "api",
    }
    with pytest.raises(RuntimeCacheConfigurationError, match="exactly one"):
        load_runtime_cache_settings(values)

    values.pop(RUNTIME_CACHE_URL)
    values[RUNTIME_CACHE_URL_SECRET_RESOURCE] = "not-a-resource"
    with pytest.raises(RuntimeCacheConfigurationError, match="invalid"):
        load_runtime_cache_settings(values)


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
