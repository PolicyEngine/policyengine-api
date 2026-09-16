"""Provision the restricted PostgreSQL identity for Stage 12 comparison runs.

This operator command uses the existing v2 provisioning-owner credential only
to create or update one login role.  It uses the v2 migration identity to grant
data access to the two temporary Stage 12 tables, verifies the resulting
runtime permissions, and stores only the restricted connection URL in Secret
Manager.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import secrets
import subprocess
from typing import Sequence

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from policyengine_api.data.v2.settings import (
    SupabaseTargetSettings,
    parse_persistent_postgres_url,
    validate_supabase_database_identity,
)

ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
GCP_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
SECRET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
SERVICE_ACCOUNT_PATTERN = re.compile(
    r"^[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com$"
)
SUPPORTED_ENVIRONMENTS = frozenset({"staging", "production"})
BASE_RUNTIME_ROLE = "policyengine_v2_runtime"
MIGRATION_ROLE = "policyengine_v2_migrator"
OWNER_ROLE = "postgres"
DATABASE_NAME = "postgres"
STAGE12_TABLES = (
    "stage12_evaluation_reports",
    "stage12_evaluation_simulations",
)


class Stage12DatabaseProvisioningError(RuntimeError):
    """Raised before an unbounded or unsafe provisioning operation."""


@dataclass(frozen=True)
class ProvisioningConfig:
    environment: str
    project_ref: str
    source_secret_project: str
    base_runtime_url_secret: str
    migration_password_secret: str
    owner_password_secret: str
    runtime_role: str
    runtime_secret_project: str
    runtime_secret_name: str
    secret_accessors: tuple[str, ...]

    def validate(self) -> None:
        if self.environment not in SUPPORTED_ENVIRONMENTS:
            raise Stage12DatabaseProvisioningError(
                "environment must be staging or production"
            )
        if ROLE_PATTERN.fullmatch(self.runtime_role) is None:
            raise Stage12DatabaseProvisioningError("invalid PostgreSQL runtime role")
        if self.environment not in self.runtime_role:
            raise Stage12DatabaseProvisioningError(
                "PostgreSQL runtime role must identify the selected environment"
            )
        for project in (self.source_secret_project, self.runtime_secret_project):
            if GCP_NAME_PATTERN.fullmatch(project) is None:
                raise Stage12DatabaseProvisioningError("invalid GCP project name")
        for name in (
            self.base_runtime_url_secret,
            self.migration_password_secret,
            self.owner_password_secret,
            self.runtime_secret_name,
        ):
            if SECRET_NAME_PATTERN.fullmatch(name) is None:
                raise Stage12DatabaseProvisioningError(
                    "invalid Secret Manager secret name"
                )
        if not self.secret_accessors:
            raise Stage12DatabaseProvisioningError(
                "at least one runtime secret accessor is required"
            )
        for account in self.secret_accessors:
            if SERVICE_ACCOUNT_PATTERN.fullmatch(account) is None:
                raise Stage12DatabaseProvisioningError(
                    "invalid runtime secret-accessor service account"
                )


@dataclass(frozen=True)
class DatabaseUrls:
    owner: URL
    migration: URL
    runtime: URL


def _run_gcloud(
    arguments: Sequence[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gcloud", *arguments],
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def _read_secret(*, project: str, name: str) -> str:
    value = _run_gcloud(
        (
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            name,
            "--project",
            project,
        )
    ).stdout.strip()
    if not value:
        raise Stage12DatabaseProvisioningError(
            f"Secret Manager secret {name!r} is empty"
        )
    return value


def _secret_exists(*, project: str, name: str) -> bool:
    result = _run_gcloud(
        (
            "secrets",
            "describe",
            name,
            "--project",
            project,
        ),
        check=False,
    )
    if result.returncode == 0:
        return True
    if "NOT_FOUND" in result.stderr:
        return False
    raise Stage12DatabaseProvisioningError(
        f"could not inspect Secret Manager secret {name!r}"
    )


def _username_for_role(base_username: str, role: str, project_ref: str) -> str:
    if base_username == BASE_RUNTIME_ROLE:
        return role
    expected = f"{BASE_RUNTIME_ROLE}.{project_ref}"
    if base_username == expected:
        return f"{role}.{project_ref}"
    raise Stage12DatabaseProvisioningError(
        "base runtime URL uses an unexpected PostgreSQL identity"
    )


def build_database_urls(
    *,
    base_runtime_url: str,
    migration_password: str,
    owner_password: str,
    runtime_role: str,
    runtime_password: str,
    project_ref: str,
    environment: str,
) -> DatabaseUrls:
    parsed = parse_persistent_postgres_url(
        base_runtime_url,
        setting_name="base runtime database URL",
    )
    validate_supabase_database_identity(
        parsed,
        SupabaseTargetSettings(
            project_ref=project_ref,
            environment=environment,
        ),
        setting_name="base runtime database URL",
    )
    base = parsed.url
    if base.database != DATABASE_NAME or base.username is None:
        raise Stage12DatabaseProvisioningError(
            "base runtime URL identifies an unexpected database"
        )
    runtime_username = _username_for_role(
        base.username,
        runtime_role,
        project_ref,
    )
    suffix = runtime_username.removeprefix(runtime_role)
    common = {
        "drivername": "postgresql",
        "host": base.host,
        "port": base.port,
        "database": base.database,
        "query": base.query,
    }
    return DatabaseUrls(
        owner=URL.create(
            **common,
            username=f"{OWNER_ROLE}{suffix}",
            password=owner_password,
        ),
        migration=URL.create(
            **common,
            username=f"{MIGRATION_ROLE}{suffix}",
            password=migration_password,
        ),
        runtime=URL.create(
            **common,
            username=runtime_username,
            password=runtime_password,
        ),
    )


def _dsn(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _role_attributes(connection: psycopg.Connection, role: str) -> tuple | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rolsuper, rolcreaterole, rolcreatedb, rolinherit,
                   rolreplication, rolbypassrls, rolcanlogin
            FROM pg_roles
            WHERE rolname = %s
            """,
            (role,),
        )
        return cursor.fetchone()


def _execute_privilege_change(
    cursor: psycopg.Cursor,
    statement: sql.Composable,
    *,
    operation: str,
) -> None:
    try:
        cursor.execute(statement)
    except psycopg.errors.InsufficientPrivilege as error:
        reason = error.diag.message_primary or "insufficient privilege"
        raise Stage12DatabaseProvisioningError(
            f"database identity lacks authority for {operation}: {reason}"
        ) from None


def configure_runtime_role(urls: DatabaseUrls, runtime_role: str) -> None:
    with psycopg.connect(_dsn(urls.owner), autocommit=True) as connection:
        with connection.cursor() as cursor:
            current_user = cursor.execute("SELECT current_user").fetchone()
            if current_user is None or current_user[0] != OWNER_ROLE:
                raise Stage12DatabaseProvisioningError(
                    "provisioning owner authenticated as an unexpected role"
                )
            attributes = _role_attributes(connection, runtime_role)
            if attributes is not None and attributes != (
                False,
                False,
                False,
                False,
                False,
                False,
                True,
            ):
                raise Stage12DatabaseProvisioningError(
                    "existing Stage 12 role has unexpected role attributes"
                )
            password = urls.runtime.password
            if password is None:
                raise Stage12DatabaseProvisioningError(
                    "runtime database password is missing"
                )
            if attributes is None:
                _execute_privilege_change(
                    cursor,
                    sql.SQL(
                        "CREATE ROLE {} WITH LOGIN NOINHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(runtime_role), sql.Literal(password)),
                    operation="creating the restricted runtime role",
                )
            else:
                _execute_privilege_change(
                    cursor,
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(runtime_role), sql.Literal(password)
                    ),
                    operation="updating the restricted runtime role password",
                )
            _execute_privilege_change(
                cursor,
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(DATABASE_NAME),
                    sql.Identifier(runtime_role),
                ),
                operation="granting database connection access",
            )
            _execute_privilege_change(
                cursor,
                sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(
                    sql.Identifier(runtime_role)
                ),
                operation="removing public-schema creation access",
            )
            _execute_privilege_change(
                cursor,
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(runtime_role)
                ),
                operation="granting public-schema usage",
            )

    with psycopg.connect(_dsn(urls.migration), autocommit=True) as connection:
        with connection.cursor() as cursor:
            current_user = cursor.execute("SELECT current_user").fetchone()
            if current_user is None or current_user[0] != MIGRATION_ROLE:
                raise Stage12DatabaseProvisioningError(
                    "migration credential authenticated as an unexpected role"
                )
            existing_tables = {
                row[0]
                for row in cursor.execute(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public' AND tablename = ANY(%s)
                    """,
                    (list(STAGE12_TABLES),),
                ).fetchall()
            }
            if existing_tables != set(STAGE12_TABLES):
                raise Stage12DatabaseProvisioningError(
                    "Stage 12 schema must be applied before runtime provisioning"
                )
            for table in STAGE12_TABLES:
                _execute_privilege_change(
                    cursor,
                    sql.SQL("REVOKE ALL PRIVILEGES ON TABLE public.{} FROM {}").format(
                        sql.Identifier(table),
                        sql.Identifier(runtime_role),
                    ),
                    operation=f"resetting access on {table}",
                )
                _execute_privilege_change(
                    cursor,
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{} TO {}"
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(runtime_role),
                    ),
                    operation=f"granting row access on {table}",
                )


def verify_runtime_role(urls: DatabaseUrls, runtime_role: str) -> None:
    with psycopg.connect(_dsn(urls.runtime)) as connection:
        with connection.cursor() as cursor:
            current_user = cursor.execute("SELECT current_user").fetchone()
            if current_user is None or current_user[0] != runtime_role:
                raise Stage12DatabaseProvisioningError(
                    "runtime credential authenticated as an unexpected role"
                )
            if _role_attributes(connection, runtime_role) != (
                False,
                False,
                False,
                False,
                False,
                False,
                True,
            ):
                raise Stage12DatabaseProvisioningError(
                    "Stage 12 runtime role has unsafe role attributes"
                )
            cursor.execute(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
            )
            if cursor.fetchone() != (False,):
                raise Stage12DatabaseProvisioningError(
                    "Stage 12 runtime role can create schema objects"
                )
            for table in STAGE12_TABLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    cursor.execute(
                        "SELECT has_table_privilege(current_user, %s, %s)",
                        (f"public.{table}", privilege),
                    )
                    if cursor.fetchone() != (True,):
                        raise Stage12DatabaseProvisioningError(
                            f"Stage 12 runtime role lacks {privilege} on {table}"
                        )
            cursor.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename <> ALL(%s)
                  AND (
                    has_table_privilege(current_user, schemaname || '.' || tablename, 'SELECT')
                    OR has_table_privilege(current_user, schemaname || '.' || tablename, 'INSERT')
                    OR has_table_privilege(current_user, schemaname || '.' || tablename, 'UPDATE')
                    OR has_table_privilege(current_user, schemaname || '.' || tablename, 'DELETE')
                  )
                ORDER BY tablename
                """,
                (list(STAGE12_TABLES),),
            )
            unexpected = [row[0] for row in cursor.fetchall()]
            if unexpected:
                raise Stage12DatabaseProvisioningError(
                    "Stage 12 runtime role has data access outside its temporary tables"
                )


def _publish_runtime_secret(
    *,
    project: str,
    name: str,
    value: str,
    existing_value: str | None,
    accessors: Sequence[str],
) -> None:
    if existing_value is None:
        _run_gcloud(
            (
                "secrets",
                "create",
                name,
                "--project",
                project,
                "--replication-policy",
                "automatic",
                "--quiet",
            )
        )
    if existing_value != value:
        _run_gcloud(
            (
                "secrets",
                "versions",
                "add",
                name,
                "--project",
                project,
                "--data-file=-",
                "--quiet",
            ),
            input_text=value,
        )
    for account in accessors:
        _run_gcloud(
            (
                "secrets",
                "add-iam-policy-binding",
                name,
                "--project",
                project,
                "--member",
                f"serviceAccount:{account}",
                "--role",
                "roles/secretmanager.secretAccessor",
                "--quiet",
            )
        )


def provision(config: ProvisioningConfig) -> None:
    config.validate()
    base_runtime_url = _read_secret(
        project=config.source_secret_project,
        name=config.base_runtime_url_secret,
    )
    migration_password = _read_secret(
        project=config.source_secret_project,
        name=config.migration_password_secret,
    )
    owner_password = _read_secret(
        project=config.source_secret_project,
        name=config.owner_password_secret,
    )
    secret_exists = _secret_exists(
        project=config.runtime_secret_project,
        name=config.runtime_secret_name,
    )
    existing_url = (
        _read_secret(
            project=config.runtime_secret_project,
            name=config.runtime_secret_name,
        )
        if secret_exists
        else None
    )
    runtime_password = secrets.token_urlsafe(48)
    if existing_url is not None:
        existing = make_url(existing_url)
        if existing.password is None:
            raise Stage12DatabaseProvisioningError(
                "existing Stage 12 runtime secret has no password"
            )
        runtime_password = existing.password
    urls = build_database_urls(
        base_runtime_url=base_runtime_url,
        migration_password=migration_password,
        owner_password=owner_password,
        runtime_role=config.runtime_role,
        runtime_password=runtime_password,
        project_ref=config.project_ref,
        environment=config.environment,
    )
    expected_runtime_url = _dsn(urls.runtime)
    if existing_url is not None and make_url(existing_url) != urls.runtime:
        raise Stage12DatabaseProvisioningError(
            "existing Stage 12 runtime secret identifies an unexpected target"
        )
    configure_runtime_role(urls, config.runtime_role)
    verify_runtime_role(urls, config.runtime_role)
    _publish_runtime_secret(
        project=config.runtime_secret_project,
        name=config.runtime_secret_name,
        value=expected_runtime_url,
        existing_value=existing_url,
        accessors=config.secret_accessors,
    )
    print(
        "Stage 12 database runtime is configured: "
        f"environment={config.environment}, role={config.runtime_role}, "
        f"secret={config.runtime_secret_project}/{config.runtime_secret_name}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--source-secret-project", required=True)
    parser.add_argument("--base-runtime-url-secret", required=True)
    parser.add_argument("--migration-password-secret", required=True)
    parser.add_argument("--owner-password-secret", required=True)
    parser.add_argument("--runtime-role", required=True)
    parser.add_argument("--runtime-secret-project", required=True)
    parser.add_argument("--runtime-secret-name", required=True)
    parser.add_argument(
        "--secret-accessor",
        action="append",
        dest="secret_accessors",
        required=True,
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        provision(
            ProvisioningConfig(
                environment=args.environment,
                project_ref=args.project_ref,
                source_secret_project=args.source_secret_project,
                base_runtime_url_secret=args.base_runtime_url_secret,
                migration_password_secret=args.migration_password_secret,
                owner_password_secret=args.owner_password_secret,
                runtime_role=args.runtime_role,
                runtime_secret_project=args.runtime_secret_project,
                runtime_secret_name=args.runtime_secret_name,
                secret_accessors=tuple(args.secret_accessors),
            )
        )
    except Stage12DatabaseProvisioningError as error:
        raise SystemExit(str(error)) from None
    except psycopg.Error as error:
        raise SystemExit(
            "Stage 12 database provisioning failed without displaying "
            f"connection credentials ({type(error).__name__})"
        ) from None
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "Stage 12 database provisioning could not complete a GCP operation "
            f"(exit status {error.returncode})"
        ) from None


if __name__ == "__main__":
    main()
