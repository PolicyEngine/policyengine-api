"""Explicit, lazy configuration for dormant API v2-alpha persistence.

Loading these settings is an operator or selected-runtime action. Importing
this module reads no environment variables, opens no connection, and creates
no local fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit

from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


V2_RUNTIME_DATABASE_URL = "V2_RUNTIME_DATABASE_URL"
V2_MIGRATION_DATABASE_URL = "V2_MIGRATION_DATABASE_URL"
V2_SUPABASE_PROJECT_REF = "V2_SUPABASE_PROJECT_REF"
V2_SUPABASE_ENVIRONMENT = "V2_SUPABASE_ENVIRONMENT"
V2_SUPABASE_STORAGE_URL = "V2_SUPABASE_STORAGE_URL"
V2_SUPABASE_STORAGE_ADMIN_KEY = "V2_SUPABASE_STORAGE_ADMIN_KEY"
V2_SUPABASE_STORAGE_BUCKET = "V2_SUPABASE_STORAGE_BUCKET"

POSTGRES_DRIVER = "postgresql+psycopg"
PERSISTENT_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
PROJECT_REF_PATTERN = re.compile(r"^[a-z0-9]{20}$")
ENVIRONMENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")


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


@dataclass(frozen=True)
class SupabaseStorageSettings:
    """Storage-only administration settings, separate from database access."""

    project_ref: str
    environment: str
    api_url: str
    bucket: str
    admin_key: SecretStr = field(repr=False)


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise V2ConfigurationError(f"{name} is required")
    return value.strip()


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


def load_v2_runtime_database_settings(
    environ: Mapping[str, str] | None = None,
) -> V2DatabaseSettings:
    """Load the future ordinary-runtime Postgres identity explicitly."""

    values = _environment(environ)
    connection = parse_persistent_postgres_url(
        _required(values, V2_RUNTIME_DATABASE_URL),
        setting_name=V2_RUNTIME_DATABASE_URL,
    )
    return V2DatabaseSettings(
        connection=connection,
        target=load_supabase_target_settings(values),
    )


def load_v2_migration_database_settings(
    environ: Mapping[str, str] | None = None,
) -> V2DatabaseSettings:
    """Load the schema-migration Postgres identity explicitly."""

    values = _environment(environ)
    connection = parse_persistent_postgres_url(
        _required(values, V2_MIGRATION_DATABASE_URL),
        setting_name=V2_MIGRATION_DATABASE_URL,
    )
    return V2DatabaseSettings(
        connection=connection,
        target=load_supabase_target_settings(values),
    )


def load_supabase_storage_settings(
    environ: Mapping[str, str] | None = None,
) -> SupabaseStorageSettings:
    """Load the separately authorized Supabase Storage administration surface."""

    values = _environment(environ)
    target = load_supabase_target_settings(values)
    api_url = _required(values, V2_SUPABASE_STORAGE_URL)
    bucket = _required(values, V2_SUPABASE_STORAGE_BUCKET)
    admin_key = _required(values, V2_SUPABASE_STORAGE_ADMIN_KEY)

    parsed_url = urlsplit(api_url)
    expected_host = f"{target.project_ref}.supabase.co"
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != expected_host
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.port is not None
        or parsed_url.path.rstrip("/")
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise V2ConfigurationError(
            f"{V2_SUPABASE_STORAGE_URL} must be the HTTPS API origin for the "
            "recorded project reference"
        )
    if BUCKET_PATTERN.fullmatch(bucket) is None:
        raise V2ConfigurationError(
            f"{V2_SUPABASE_STORAGE_BUCKET} is not a valid bucket name"
        )

    return SupabaseStorageSettings(
        project_ref=target.project_ref,
        environment=target.environment,
        api_url=api_url.rstrip("/"),
        bucket=bucket,
        admin_key=SecretStr(admin_key),
    )
