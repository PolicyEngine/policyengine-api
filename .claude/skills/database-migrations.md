# Database Migration Guidelines

## Overview

This project uses Alembic for database migrations. API v1 still uses raw SQL
initializers rather than ORM models, so Alembic target metadata is reflected
from `policyengine_api/data/initialise_local.sql` by default.

## Rules

- Do not manually author Alembic operations for normal schema changes.
- Generate migrations with `uv run alembic revision --autogenerate`.
- Review generated migrations before applying them.
- Keep SQL initializers and generated migrations aligned.
- For pre-existing production databases, stamp the base revision before applying
  new upgrade revisions.

## Commands

```bash
uv run alembic revision --autogenerate -m "Description"
uv run alembic upgrade head
uv run alembic current
uv run alembic history
uv run alembic stamp <revision>
```

## API v1 Notes

- Set `POLICYENGINE_ALEMBIC_DATABASE_URL` to the database SQLAlchemy URL Alembic
  should connect to.
- Set `POLICYENGINE_ALEMBIC_SCHEMA_SQL` when generating against a temporary
  schema SQL file instead of the current initializer.
- The base migration should be stamped in production because the tables already
  exist there.
