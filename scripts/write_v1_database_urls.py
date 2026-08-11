"""Write masked local-proxy database URLs into a GitHub Actions env file."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.v1_database_migration import build_database_url


DATABASE_NAME = "policyengine"
READONLY_USER = "policyengine_schema_reader"
MIGRATION_USER = "policyengine_schema_migrator"
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 3307


def main() -> int:
    output_path = Path(os.environ["GITHUB_ENV"])
    readonly_url = build_database_url(
        username=READONLY_USER,
        password=os.environ["POLICYENGINE_DB_READONLY_PASSWORD"],
        host=PROXY_HOST,
        port=PROXY_PORT,
        database=DATABASE_NAME,
    )
    migration_url = build_database_url(
        username=MIGRATION_USER,
        password=os.environ["POLICYENGINE_DB_MIGRATION_PASSWORD"],
        host=PROXY_HOST,
        port=PROXY_PORT,
        database=DATABASE_NAME,
    )

    # URL-encoded passwords can differ from the exact GitHub secret value, so
    # mask the complete derived URLs before any later command can mention them.
    print(f"::add-mask::{readonly_url}")
    print(f"::add-mask::{migration_url}")
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"STAGE7_EXISTING_DATABASE_URL={readonly_url}\n")
        output.write(f"ALEMBIC_DATABASE_URL={migration_url}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
