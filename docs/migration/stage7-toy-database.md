# Stage 7 Toy Database

The Stage 7 toy database is a disposable MySQL 8 instance used to prove the
SQLAlchemy and Alembic boundary on the same database dialect as the current
Cloud SQL service. It contains synthetic qualification records only.

## Local qualification

Docker with the Compose plugin is required. Run:

```bash
make stage7-toy-test
make stage7-toy-down
```

`stage7-toy-test` starts the service, waits for MySQL's health check, and runs
the integration suite. `stage7-toy-down` removes the container and its volumes.
The database data directory is also mounted as `tmpfs`, so data does not
survive the container.

Port `3307` is used by default to avoid a typical local MySQL server. Override
it consistently when needed:

```bash
STAGE7_TOY_MYSQL_PORT=13307 \
STAGE7_TOY_DATABASE_URL=mysql+pymysql://policyengine:policyengine@127.0.0.1:13307/policyengine_stage7_toy \
make stage7-toy-test
```

The test teardown runs `alembic downgrade base`, which is destructive. A hard
safety guard permits that operation only for MySQL on `localhost` or
`127.0.0.1` and only when the database name ends in `_toy`.

## Qualification targets

The suite must prove all of the following before Stage 7 proceeds:

1. A fresh MySQL database upgrades to Alembic `head`.
2. Every migrated DAO domain can write and read synthetic data.
3. The upgraded schema has no drift from the reviewed SQLAlchemy metadata.
4. The baseline downgrades to `base` and upgrades to `head` again.
5. The independently defined pre-Alembic schema compares without drift and can
   be stamped without losing an existing sentinel row.
6. Typed DAO results preserve the legacy service-level mapping shapes.
7. Policy, household, and user routes operate against MySQL.
8. The Cloud SQL connector/pool seam drives typed DAOs.
9. Importing and starting the Flask application emits no MySQL DDL.

Pull requests run the same suite against a fresh MySQL 8 service container.

## Canonical SQLAlchemy boundary

The Stage 7 runtime follows SQLAlchemy's documented ownership model:

- one `Engine` and its `QueuePool` are created per worker process;
- the Cloud SQL `creator` returns one fresh DBAPI connection whenever the pool
  requests one, while SQLAlchemy owns checkout, return, pre-ping, recycling,
  overflow, and timeout behavior;
- a `sessionmaker` creates a short-lived `Session` for each service operation;
- service-level units of work use `sessionmaker.begin()` so success commits and
  exceptions roll back and close the session automatically;
- typed repositories receive the operation's `Session` and never create,
  commit, roll back, retry, or retain sessions themselves;
- application startup performs no DDL; Alembic alone owns schema changes; and
- ASGI lifespan and process-exit cleanup dispose the engine and close the Cloud
  SQL connector. Gunicorn application preloading remains disabled so workers do
  not inherit pooled connections across a fork.

These constraints reflect SQLAlchemy's guidance for
[contextual session/transaction management](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#framing-out-a-begin-commit-rollback-block),
[engine disposal](https://docs.sqlalchemy.org/en/20/core/connections.html#engine-disposal),
and [pooling with multiprocessing](https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork).

## Existing Cloud SQL comparison

The production check is intentionally read-only and skipped unless an explicit
URL is supplied. Use credentials whose database user has read-only access:

```bash
STAGE7_EXISTING_DATABASE_URL='<read-only SQLAlchemy URL>' \
uv run pytest \
  tests/integration/test_stage7_existing_schema.py::test_live_existing_schema_matches_metadata_without_mutation \
  -v
```

Do not stamp an existing database from this command. Stamping is qualified only
against the disposable pre-Alembic fixture; a real database may be stamped only
after its read-only comparison is empty, its backup is confirmed, and a human
approves the target.
