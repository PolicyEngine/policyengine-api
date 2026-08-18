# Stage 8 v2 platform runbook

## Scope and authority

Stage 8 keeps Cloud SQL, existing routes, Simulation Entrypoint selection, and
existing compute primary. The Supabase Postgres schema is dormant. Redis holds
only recoverable completed results and expiring coordination state; it is never
a durable domain store.

The recorded Supabase target is project `kvrifaviwhzjztcbrfpy`, organization
`PolicyEngine`, region `us-east-2`, environment `production-foundation`. Stop
if a supplied connection cannot be proven to resolve to that target.

## Persistent Supabase qualification and initialization

1. Confirm the target record in `stage-8-supabase-target.md` and its successful
   fresh-state audit. A target with application tables, Alembic history, a
   mismatched project reference, or ambiguous identity is not reset, adopted,
   dropped, or stamped.
2. Retrieve only the migration database credential from Secret Manager and
   supply `V2_MIGRATION_DATABASE_URL`, `V2_SUPABASE_PROJECT_REF`, and
   `V2_SUPABASE_ENVIRONMENT` to the explicit operator process.
3. Run `uv run alembic -c alembic-v2.ini upgrade head` and then
   `uv run alembic -c alembic-v2.ini check`. Do not run either operation during
   application startup.
4. Only after migration succeeds, retrieve the separate Storage administration
   credential and run
   `uv run python3 scripts/bootstrap_v2_supabase_storage.py`.
   A second identical run must be a no-op; incompatible existing configuration
   is an error, not permission to replace the bucket.
5. Confirm no migration URL, password, Storage key, scratch SQL, generated
   payload, dump, or one-off scaffolding file entered the repository or logs.

Application runtime receives the non-secret dormant project identity only. It
does not receive the migration password or Storage administration key.

## Managed-cache rollout

Staging uses `policyengine-api-cache-staging` (Basic, 1 GiB) and production uses
`policyengine-api-cache-prod` (Standard HA, 5 GiB). Both are Redis 7.2,
AUTH-enabled, TLS-only on port 6378, and private through the `default` VPC and
`policyengine-api-memorystore-psa` allocation.

Before sending traffic to a candidate:

1. Verify the instance is `READY`, its AUTH and TLS modes are enabled, and all
   current server CAs are present in the environment's CA secret.
2. Verify the candidate has `RUNTIME_CACHE_MODE=deployed`, the correct
   environment namespace, both Secret Manager bindings, and Direct VPC egress
   through `default/default` with `private-ranges-only` routing.
3. Verify Cloud Run uses the dedicated runtime service account and App Engine
   uses only non-secret Secret Manager resource names. Confirm the App Engine
   staging and production service accounts have repository-scoped Artifact
   Registry Reader access so each can pull the reviewed candidate image, and
   those identities have `secretAccessor` only on the required database
   password, GitHub microdata, Anthropic, OpenAI, Hugging Face, gateway-auth,
   and environment-specific cache secrets. Neither runtime identity receives
   v2 migration or Storage administration access.
4. Send test traffic to at least two Cloud Run instances and verify one
   connection's value is visible to another. Confirm the container has no
   `redis-server` child and startup creates no SQLite database or lock file.
5. Delete only test cache keys, then verify completed-result reads recompute as
   misses. Do not use a coordination failure as a miss: claims must fail closed.

Expect a cold cache during first rollout. Monitor cache-family hits, misses,
recomputations, write failures, coordination failures, connection latency,
timeouts, evictions, memory pressure, Cloud SQL behavior, and API errors.
Completed-result writes use subtract-only TTL jitter of up to ten percent to
spread normal expirations; coordination and claim TTLs remain exact. Jitter
does not spread misses after a full flush, so bounded recomputation and atomic
claims remain the controls for complete cache loss.
Runtime cache operations emit the stable `runtime_cache_operations` structured
metric with `metric_value=1`, `cache_family`, `cache_event`, optional
`cache_operation`, and `latency_ms`. Use the value as a counter grouped by the
family and event fields and the latency field as the distribution source.
Logs must include no keys, values, URLs, AUTH strings, or CA payloads.

## Rollback

Move traffic to the exact preceding application revision with its own
revision-specific cache configuration. Do not recover, copy, or downgrade Redis
contents; cache loss is handled as a miss. The prior revision must not be
retrofitted with the new secret or VPC configuration during rollback.

Leave the dormant v2 Supabase schema at its current revision during an
application rollback. Run a v2 Alembic downgrade only as a separate reviewed
operator action against the re-qualified v2 target. Never point the v1 chain at
Supabase, automatically downgrade Postgres, or delete Storage as part of an
application traffic rollback.
