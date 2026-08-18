"""Explicit, secret-safe shared Redis configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
import os
import re
from typing import Callable
from urllib.parse import SplitResult, urlsplit

from pydantic import SecretStr


RUNTIME_CACHE_MODE = "RUNTIME_CACHE_MODE"
RUNTIME_CACHE_URL = "RUNTIME_CACHE_URL"
RUNTIME_CACHE_CA_CERT = "RUNTIME_CACHE_CA_CERT"
RUNTIME_CACHE_URL_SECRET_RESOURCE = "RUNTIME_CACHE_URL_SECRET_RESOURCE"
RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE = "RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE"
RUNTIME_CACHE_ENVIRONMENT = "RUNTIME_CACHE_ENVIRONMENT"
RUNTIME_CACHE_SERVICE = "RUNTIME_CACHE_SERVICE"

CACHE_MODES = frozenset({"disabled", "local", "deployed"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SECRET_RESOURCE_PATTERN = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")
DEFAULT_MAX_CONNECTIONS = 20
DEFAULT_CONNECT_TIMEOUT_SECONDS = 1.0
DEFAULT_OPERATION_TIMEOUT_SECONDS = 2.0


class RuntimeCacheConfigurationError(RuntimeError):
    """Raised without echoing a secret-bearing URL."""


@dataclass(frozen=True)
class RuntimeCacheSettings:
    mode: str
    environment: str
    service: str
    url: SecretStr | None = field(repr=False)
    ca_cert: SecretStr | None = field(repr=False)
    tls: bool
    max_connections: int = DEFAULT_MAX_CONNECTIONS
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    operation_timeout_seconds: float = DEFAULT_OPERATION_TIMEOUT_SECONDS

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"


@lru_cache(maxsize=None)
def _load_secret_from_secret_manager(resource_name: str) -> str:
    """Resolve App Engine cache secrets without placing them in image layers."""

    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise RuntimeCacheConfigurationError(f"{name} is required")
    return value.strip()


def _resolve_secret_source(
    values: Mapping[str, str],
    *,
    value_name: str,
    resource_name: str,
    secret_loader: Callable[[str], str],
) -> str:
    direct_value = values.get(value_name, "")
    resource = values.get(resource_name, "").strip()
    if direct_value and resource:
        raise RuntimeCacheConfigurationError(
            f"set exactly one of {value_name} or {resource_name}"
        )
    if direct_value:
        return direct_value
    if not resource:
        raise RuntimeCacheConfigurationError(
            f"{value_name} or {resource_name} is required"
        )
    if SECRET_RESOURCE_PATTERN.fullmatch(resource) is None:
        raise RuntimeCacheConfigurationError(f"{resource_name} is invalid")
    try:
        value = secret_loader(resource)
    except Exception as error:
        raise RuntimeCacheConfigurationError(
            f"{resource_name} could not be resolved"
        ) from error
    if not value:
        raise RuntimeCacheConfigurationError(f"{resource_name} is empty")
    return value


def _is_deployed(values: Mapping[str, str]) -> bool:
    return bool(values.get("K_SERVICE") or values.get("GAE_ENV"))


def _validate_name(value: str, setting: str) -> str:
    if NAME_PATTERN.fullmatch(value) is None:
        raise RuntimeCacheConfigurationError(f"{setting} is invalid")
    return value


def _parse_url(raw_url: str, *, mode: str) -> SplitResult:
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as error:
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_URL} is invalid"
        ) from error
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_URL} must use redis:// or rediss://"
        )
    if parsed.query or parsed.fragment or parsed.path not in {"", "/0"}:
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_URL} must select database 0 without query or fragment"
        )
    if port is None:
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_URL} must include an explicit port"
        )
    if mode == "deployed":
        if parsed.scheme != "rediss":
            raise RuntimeCacheConfigurationError(
                f"{RUNTIME_CACHE_URL} must require TLS in deployed mode"
            )
        if parsed.hostname.lower() in LOCAL_HOSTS:
            raise RuntimeCacheConfigurationError(
                f"{RUNTIME_CACHE_URL} cannot use localhost in deployed mode"
            )
        if parsed.password is None:
            raise RuntimeCacheConfigurationError(
                f"{RUNTIME_CACHE_URL} requires authentication in deployed mode"
            )
    elif parsed.hostname.lower() not in LOCAL_HOSTS:
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_URL} local mode requires an explicit local endpoint"
        )
    return parsed


def _parse_ca_cert(values: Mapping[str, str], *, tls: bool) -> SecretStr | None:
    raw_ca_cert = values.get(RUNTIME_CACHE_CA_CERT, "")
    if not tls:
        if raw_ca_cert.strip():
            raise RuntimeCacheConfigurationError(
                f"{RUNTIME_CACHE_CA_CERT} requires a TLS cache URL"
            )
        return None
    ca_cert = _required(values, RUNTIME_CACHE_CA_CERT)
    if (
        not ca_cert.startswith("-----BEGIN CERTIFICATE-----")
        or not ca_cert.endswith("-----END CERTIFICATE-----")
        or "\x00" in ca_cert
    ):
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_CA_CERT} must contain a PEM certificate bundle"
        )
    return SecretStr(ca_cert)


def load_runtime_cache_settings(
    environ: Mapping[str, str] | None = None,
    *,
    secret_loader: Callable[[str], str] | None = None,
) -> RuntimeCacheSettings:
    """Load disabled, explicit-local, or fail-closed deployed cache settings."""

    values = os.environ if environ is None else environ
    raw_mode = values.get(RUNTIME_CACHE_MODE, "").strip()
    mode = raw_mode or ("deployed" if _is_deployed(values) else "disabled")
    if mode not in CACHE_MODES:
        raise RuntimeCacheConfigurationError(
            f"{RUNTIME_CACHE_MODE} must be disabled, local, or deployed"
        )
    if mode == "disabled":
        if values.get(RUNTIME_CACHE_URL) or values.get(
            RUNTIME_CACHE_URL_SECRET_RESOURCE
        ):
            raise RuntimeCacheConfigurationError(
                "runtime cache secret configuration requires an explicit "
                "local or deployed mode"
            )
        return RuntimeCacheSettings(
            mode=mode,
            environment="test",
            service="api",
            url=None,
            ca_cert=None,
            tls=False,
        )

    load_secret = secret_loader or _load_secret_from_secret_manager
    raw_url = _resolve_secret_source(
        values,
        value_name=RUNTIME_CACHE_URL,
        resource_name=RUNTIME_CACHE_URL_SECRET_RESOURCE,
        secret_loader=load_secret,
    )
    parsed = _parse_url(raw_url, mode=mode)
    tls = parsed.scheme == "rediss"
    ca_values = dict(values)
    if tls:
        ca_values[RUNTIME_CACHE_CA_CERT] = _resolve_secret_source(
            values,
            value_name=RUNTIME_CACHE_CA_CERT,
            resource_name=RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE,
            secret_loader=load_secret,
        )
    ca_cert = _parse_ca_cert(ca_values, tls=tls)
    environment = _validate_name(
        _required(values, RUNTIME_CACHE_ENVIRONMENT),
        RUNTIME_CACHE_ENVIRONMENT,
    )
    service = _validate_name(
        _required(values, RUNTIME_CACHE_SERVICE),
        RUNTIME_CACHE_SERVICE,
    )
    return RuntimeCacheSettings(
        mode=mode,
        environment=environment,
        service=service,
        url=SecretStr(raw_url),
        ca_cert=ca_cert,
        tls=tls,
    )
