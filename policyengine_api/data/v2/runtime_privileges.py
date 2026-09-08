"""Least-privilege database access for API v2 household persistence."""

from __future__ import annotations

from collections.abc import Mapping
import os

from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.migration_target import (
    V2MigrationTargetError,
    load_v2_alembic_settings,
    qualify_v2_connection,
)


V2_RUNTIME_ROLE = "policyengine_v2_runtime"
HOUSEHOLD_RUNTIME_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "households": ("SELECT", "INSERT"),
    "user_household_associations": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "legacy_household_mappings": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}
POSTGRES_TABLE_PRIVILEGES = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}
)


def grant_household_runtime_privileges(connection: Connection) -> None:
    """Grant only the table operations required by Stage 11 runtime paths."""

    role_exists = connection.scalar(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": V2_RUNTIME_ROLE},
    )
    if role_exists is not True:
        raise V2MigrationTargetError("the configured v2 runtime identity is missing")

    public_tables = set(inspect(connection).get_table_names(schema="public"))
    missing_tables = set(HOUSEHOLD_RUNTIME_PRIVILEGES) - public_tables
    if missing_tables:
        raise V2MigrationTargetError(
            "the v2 household runtime privilege target is incomplete: "
            f"missing={sorted(missing_tables)}"
        )

    quote = connection.dialect.identifier_preparer.quote
    quoted_role = quote(V2_RUNTIME_ROLE)
    for table_name, privileges in HOUSEHOLD_RUNTIME_PRIVILEGES.items():
        connection.exec_driver_sql(
            f"REVOKE ALL PRIVILEGES ON TABLE public.{quote(table_name)} "
            f"FROM {quoted_role}"
        )
        connection.exec_driver_sql(
            f"GRANT {', '.join(privileges)} ON TABLE "
            f"public.{quote(table_name)} TO {quoted_role}"
        )

    required_checks = {
        table_name: ",".join(privileges)
        for table_name, privileges in HOUSEHOLD_RUNTIME_PRIVILEGES.items()
    }
    for table_name, required_privileges in required_checks.items():
        has_privileges = connection.scalar(
            text("SELECT has_table_privilege(:role, :table, :privileges)"),
            {
                "role": V2_RUNTIME_ROLE,
                "table": f"public.{table_name}",
                "privileges": required_privileges,
            },
        )
        if has_privileges is not True:
            raise V2MigrationTargetError(
                "the v2 runtime identity lacks required household table privileges"
            )

    for table_name, allowed_privileges in HOUSEHOLD_RUNTIME_PRIVILEGES.items():
        for forbidden_privilege in POSTGRES_TABLE_PRIVILEGES - set(allowed_privileges):
            unexpected_privilege = connection.scalar(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {
                    "role": V2_RUNTIME_ROLE,
                    "table": f"public.{table_name}",
                    "privilege": forbidden_privilege,
                },
            )
            if unexpected_privilege is True:
                raise V2MigrationTargetError(
                    "the v2 runtime identity has an unexpected household table "
                    "privilege"
                )


def main(environ: Mapping[str, str] | None = None) -> int:
    """Apply and verify Stage 11 runtime privileges on one qualified target."""

    settings = load_v2_alembic_settings(os.environ if environ is None else environ)
    engine = create_engine(settings.url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            qualify_v2_connection(connection, settings)
            grant_household_runtime_privileges(connection)
    finally:
        engine.dispose()
    print("V2 household runtime privileges applied and verified.")
    return 0
