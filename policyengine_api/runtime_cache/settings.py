"""Explicit, secret-safe shared Redis configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit

from pydantic import SecretStr

if TYPE_CHECKING:
    from collections.abc import Mapping

RUNTIME_CACHE_MODE = "RUNTIME_CACHE_MODE"
RUNTIME_CACHE_URL = "RUNTIME_CACHE_URL"
RUNTIME_CACHE_CA_CERT = "RUNTIME_CACHE_CA_CERT"
RUNTIME_CACHE_ENVIRONMENT = "RUNTIME_CACHE_ENVIRONMENT"
RUNTIME_CACHE_SERVICE = "RUNTIME_CACHE_SERVICE"

CACHE_MODES = frozenset({"disabled", "local", "deployed"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
DEFAULT_MAX_CONNECTIONS = 20
DEFAULT_CONNECT_TIMEOUT_SECONDS = 1.0
DEFAULT_OPERATION_TIMEOUT_SECONDS = 2.0


class RuntimeCacheConfigurationError(RuntimeError):
    """Raised without echoing a secret-bearing URL."""


@dataclass(frozen=True)
class RuntimeCacheSettings:
    """Validated cache configuration; the URL and CA bundle stay secret in reprs."""

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
        """Whether a real Redis backend is configured (local or deployed mode)."""
        return self.mode != "disabled"


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        msg = f"{name} is required"
        raise RuntimeCacheConfigurationError(msg)
    return value.strip()


def _is_deployed(values: Mapping[str, str]) -> bool:
    return bool(values.get("K_SERVICE"))


def _validate_name(value: str, setting: str) -> str:
    if NAME_PATTERN.fullmatch(value) is None:
        msg = f"{setting} is invalid"
        raise RuntimeCacheConfigurationError(msg)
    return value


def _parse_url(raw_url: str, *, mode: str) -> SplitResult:
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as error:
        msg = f"{RUNTIME_CACHE_URL} is invalid"
        raise RuntimeCacheConfigurationError(msg) from error
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        msg = f"{RUNTIME_CACHE_URL} must use redis:// or rediss://"
        raise RuntimeCacheConfigurationError(msg)
    if parsed.query or parsed.fragment or parsed.path not in {"", "/0"}:
        msg = f"{RUNTIME_CACHE_URL} must select database 0 without query or fragment"
        raise RuntimeCacheConfigurationError(msg)
    if port is None:
        msg = f"{RUNTIME_CACHE_URL} must include an explicit port"
        raise RuntimeCacheConfigurationError(msg)
    if mode == "deployed":
        if parsed.scheme != "rediss":
            msg = f"{RUNTIME_CACHE_URL} must require TLS in deployed mode"
            raise RuntimeCacheConfigurationError(msg)
        if parsed.hostname.lower() in LOCAL_HOSTS:
            msg = f"{RUNTIME_CACHE_URL} cannot use localhost in deployed mode"
            raise RuntimeCacheConfigurationError(msg)
        if parsed.password is None:
            msg = f"{RUNTIME_CACHE_URL} requires authentication in deployed mode"
            raise RuntimeCacheConfigurationError(msg)
    elif parsed.hostname.lower() not in LOCAL_HOSTS:
        msg = f"{RUNTIME_CACHE_URL} local mode requires an explicit local endpoint"
        raise RuntimeCacheConfigurationError(msg)
    return parsed


def _parse_ca_cert(values: Mapping[str, str], *, tls: bool) -> SecretStr | None:
    raw_ca_cert = values.get(RUNTIME_CACHE_CA_CERT, "")
    if not tls:
        if raw_ca_cert.strip():
            msg = f"{RUNTIME_CACHE_CA_CERT} requires a TLS cache URL"
            raise RuntimeCacheConfigurationError(msg)
        return None
    ca_cert = _required(values, RUNTIME_CACHE_CA_CERT)
    if (
        not ca_cert.startswith("-----BEGIN CERTIFICATE-----")
        or not ca_cert.endswith("-----END CERTIFICATE-----")
        or "\x00" in ca_cert
    ):
        msg = f"{RUNTIME_CACHE_CA_CERT} must contain a PEM certificate bundle"
        raise RuntimeCacheConfigurationError(msg)
    return SecretStr(ca_cert)


def load_runtime_cache_settings(
    environ: Mapping[str, str] | None = None,
) -> RuntimeCacheSettings:
    """Load disabled, explicit-local, or fail-closed deployed cache settings."""
    values = os.environ if environ is None else environ
    raw_mode = values.get(RUNTIME_CACHE_MODE, "").strip()
    deployed_runtime = _is_deployed(values)
    mode = raw_mode or ("deployed" if deployed_runtime else "disabled")
    if mode not in CACHE_MODES:
        msg = f"{RUNTIME_CACHE_MODE} must be disabled, local, or deployed"
        raise RuntimeCacheConfigurationError(msg)
    if deployed_runtime and mode != "deployed":
        msg = (
            f"{RUNTIME_CACHE_MODE} must be deployed when K_SERVICE identifies "
            "a deployed runtime"
        )
        raise RuntimeCacheConfigurationError(msg)
    if mode == "disabled":
        if values.get(RUNTIME_CACHE_URL) or values.get(RUNTIME_CACHE_CA_CERT):
            msg = (
                "runtime cache secret configuration requires an explicit "
                "local or deployed mode"
            )
            raise RuntimeCacheConfigurationError(msg)
        return RuntimeCacheSettings(
            mode=mode,
            environment="test",
            service="api",
            url=None,
            ca_cert=None,
            tls=False,
        )

    raw_url = _required(values, RUNTIME_CACHE_URL)
    parsed = _parse_url(raw_url, mode=mode)
    tls = parsed.scheme == "rediss"
    ca_cert = _parse_ca_cert(values, tls=tls)
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
