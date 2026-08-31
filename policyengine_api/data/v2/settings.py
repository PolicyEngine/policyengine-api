"""Explicit, lazy configuration for dormant API v2-alpha persistence.

Loading these settings is an operator or selected-runtime action. Importing
this module reads no environment variables, opens no connection, and creates
no local fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
import os
import re
from typing import Callable

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


V2_RUNTIME_DATABASE_URL = "V2_RUNTIME_DATABASE_URL"
V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE = "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE"
V2_MIGRATION_DATABASE_URL = "V2_MIGRATION_DATABASE_URL"
V2_DATA_WRITE_DATABASE_URL = "V2_DATA_WRITE_DATABASE_URL"
V2_SUPABASE_PROJECT_REF = "V2_SUPABASE_PROJECT_REF"
V2_SUPABASE_ENVIRONMENT = "V2_SUPABASE_ENVIRONMENT"

POSTGRES_DRIVER = "postgresql+psycopg"
PERSISTENT_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
PROJECT_REF_PATTERN = re.compile(r"^[a-z0-9]{20}$")
ENVIRONMENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SECRET_RESOURCE_PATTERN = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")
SUPABASE_DATABASE_NAME = "postgres"


class V2ConfigurationError(RuntimeError):
    """Raised when explicitly selected v2 configuration is absent or unsafe."""


@dataclass(frozen=True)
class PostgresConnectionSettings:
    """A validated Psycopg URL whose representation never contains secrets."""

    _url: URL = field(repr=False)

    @property
    def url(self) -> URL:
        """Return SQLAlchemy's immutable URL for engine construction."""

        return self._url

    @property
    def redacted_url(self) -> str:
        """Return a log-safe URL with the password hidden."""

        return self._url.render_as_string(hide_password=True)

    def __str__(self) -> str:
        return self.redacted_url


@dataclass(frozen=True)
class SupabaseTargetSettings:
    """Non-secret identity for one persistent Supabase target."""

    project_ref: str
    environment: str


@dataclass(frozen=True)
class V2DatabaseSettings:
    """Selected runtime or migration database and its persistent identity."""

    connection: PostgresConnectionSettings
    target: SupabaseTargetSettings


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise V2ConfigurationError(f"{name} is required")
    return value.strip()


@lru_cache(maxsize=None)
def _load_secret_from_secret_manager(resource_name: str) -> str:
    """Resolve a v2 runtime URL only when a preview request selects it."""

    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


def _resolve_runtime_database_url(
    environ: Mapping[str, str],
    *,
    secret_loader: Callable[[str], str],
) -> str:
    direct_value = environ.get(V2_RUNTIME_DATABASE_URL, "").strip()
    resource = environ.get(V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE, "").strip()
    if direct_value and resource:
        raise V2ConfigurationError(
            f"set exactly one of {V2_RUNTIME_DATABASE_URL} or "
            f"{V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE}"
        )
    if direct_value:
        return direct_value
    if not resource:
        raise V2ConfigurationError(
            f"{V2_RUNTIME_DATABASE_URL} or "
            f"{V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE} is required"
        )
    if SECRET_RESOURCE_PATTERN.fullmatch(resource) is None:
        raise V2ConfigurationError(
            f"{V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE} is invalid"
        )
    try:
        resolved_value = secret_loader(resource).strip()
    except Exception as error:
        raise V2ConfigurationError(
            f"{V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE} could not be resolved"
        ) from error
    if not resolved_value:
        raise V2ConfigurationError(
            f"{V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE} is empty"
        )
    return resolved_value


def load_supabase_target_settings(
    environ: Mapping[str, str] | None = None,
) -> SupabaseTargetSettings:
    """Load the externally configured non-secret Supabase target identity."""

    values = _environment(environ)
    project_ref = _required(values, V2_SUPABASE_PROJECT_REF)
    environment = _required(values, V2_SUPABASE_ENVIRONMENT)

    if PROJECT_REF_PATTERN.fullmatch(project_ref) is None:
        raise V2ConfigurationError(
            f"{V2_SUPABASE_PROJECT_REF} is not a valid project reference"
        )
    if ENVIRONMENT_PATTERN.fullmatch(environment) is None:
        raise V2ConfigurationError(
            f"{V2_SUPABASE_ENVIRONMENT} is not a valid environment name"
        )
    return SupabaseTargetSettings(
        project_ref=project_ref,
        environment=environment,
    )


def parse_persistent_postgres_url(
    raw_url: str,
    *,
    setting_name: str,
) -> PostgresConnectionSettings:
    """Validate an explicit persistent Postgres URL without echoing it."""

    try:
        url = make_url(raw_url)
    except ArgumentError as error:
        raise V2ConfigurationError(f"{setting_name} is not a valid URL") from error

    if url.drivername != POSTGRES_DRIVER:
        raise V2ConfigurationError(
            f"{setting_name} must use the {POSTGRES_DRIVER} driver"
        )
    if not url.host or url.host.lower() in LOCAL_HOSTS:
        raise V2ConfigurationError(
            f"{setting_name} must name a non-local Postgres host"
        )
    if not url.database or not url.username or url.password is None:
        raise V2ConfigurationError(
            f"{setting_name} must include an explicit database and credentials"
        )

    sslmode = url.query.get("sslmode")
    if not isinstance(sslmode, str) or sslmode not in PERSISTENT_SSL_MODES:
        raise V2ConfigurationError(
            f"{setting_name} must require TLS with sslmode="
            "require, verify-ca, or verify-full"
        )
    return PostgresConnectionSettings(url)


def validate_supabase_database_identity(
    connection: PostgresConnectionSettings,
    target: SupabaseTargetSettings,
    *,
    setting_name: str,
) -> None:
    """Require a persistent URL to identify the configured Supabase project."""

    url = connection.url
    direct_host = f"db.{target.project_ref}.supabase.co"
    is_direct = url.host == direct_host
    is_pooler = bool(
        url.host
        and url.host.endswith(".pooler.supabase.com")
        and url.username
        and url.username.endswith(f".{target.project_ref}")
    )
    if not (is_direct or is_pooler):
        raise V2ConfigurationError(
            f"{setting_name} does not identify the configured Supabase project"
        )
    if url.database != SUPABASE_DATABASE_NAME:
        raise V2ConfigurationError(
            f"{setting_name} does not identify the configured Supabase database"
        )


def _database_settings(
    raw_url: str,
    environ: Mapping[str, str],
    *,
    setting_name: str,
) -> V2DatabaseSettings:
    connection = parse_persistent_postgres_url(
        raw_url,
        setting_name=setting_name,
    )
    target = load_supabase_target_settings(environ)
    validate_supabase_database_identity(
        connection,
        target,
        setting_name=setting_name,
    )
    return V2DatabaseSettings(connection=connection, target=target)


def load_v2_runtime_database_settings(
    environ: Mapping[str, str] | None = None,
    *,
    secret_loader: Callable[[str], str] | None = None,
) -> V2DatabaseSettings:
    """Load the future ordinary-runtime Postgres identity explicitly."""

    values = _environment(environ)
    raw_url = _resolve_runtime_database_url(
        values,
        secret_loader=secret_loader or _load_secret_from_secret_manager,
    )
    return _database_settings(
        raw_url,
        setting_name=V2_RUNTIME_DATABASE_URL,
        environ=values,
    )


def load_v2_migration_database_settings(
    environ: Mapping[str, str] | None = None,
) -> V2DatabaseSettings:
    """Load the schema-migration Postgres identity explicitly."""

    values = _environment(environ)
    return _database_settings(
        _required(values, V2_MIGRATION_DATABASE_URL),
        setting_name=V2_MIGRATION_DATABASE_URL,
        environ=values,
    )


def load_v2_data_write_database_settings(
    environ: Mapping[str, str] | None = None,
) -> V2DatabaseSettings:
    """Load the one-time catalog row-write Postgres identity explicitly."""

    values = _environment(environ)
    return _database_settings(
        _required(values, V2_DATA_WRITE_DATABASE_URL),
        setting_name=V2_DATA_WRITE_DATABASE_URL,
        environ=values,
    )
