# Stage 8 Supabase Target

This document is the durable, non-secret identity record for the Supabase
project introduced by Stage 8 of the unified API v2-alpha migration. It does
not contain credentials, connection URLs, API keys, or one-off provisioning
output.

## Target identity

| Field | Value |
| --- | --- |
| Supabase organization | `PolicyEngine` |
| Organization ID | `jygirqnhxzbevhozzrzi` |
| Project name | `policyengine-api-v2-alpha` |
| Project reference | `kvrifaviwhzjztcbrfpy` |
| Region | `us-east-2` |
| Environment classification | Production foundation; dormant during Stage 8 |
| Owning team | PolicyEngine engineering |
| Stage 8 authority | No production request reads, writes, routes, or compute |
| Database host identity | `db.kvrifaviwhzjztcbrfpy.supabase.co` |
| Postgres engine | PostgreSQL 17, Supabase GA channel |
| Provisioned | 2026-08-13; observed `ACTIVE_HEALTHY` |

## Purpose

The project is the dedicated Postgres and Storage destination for the API
v2-alpha migration. Stage 8 establishes and qualifies the platform while Cloud
SQL and the existing API and compute paths remain primary. Later migration
stages may populate and activate the target under their own reviewed cutover
contracts.

## Selection record

- The authenticated Supabase account exposes one organization, `PolicyEngine`,
  with organization ID `jygirqnhxzbevhozzrzi`.
- No existing project is named `policyengine-api-v2-alpha`. In particular, the
  unrelated project named `database` is not reused.
- The deployed API and Cloud SQL defaults are in GCP `us-central1`. Supabase
  currently offers `us-east-2`; it is selected as the nearby supported region
  for this AWS-hosted project.
- A Supabase project's region is fixed at the infrastructure level, so a later
  region change would require a new project and a reviewed migration.

## Provisioning boundary

Project creation is an explicit operator action. It may establish the project,
database service, ownership, networking, and secret placement, but it must not
create application tables or rows, stamp Alembic, or initialize a Storage
bucket. Application schema and versioned application data remain exclusively
owned by the generated v2 Alembic chain. Storage initialization is a separate,
later idempotent operation.

The owner credential created with the project is stored in GCP Secret Manager
as `policyengine-api-v2-alpha-prod-db-owner-password`. It is a provisioning
credential, not the later migration or application-runtime identity, and its
value is never stored in this repository.

Tasks 1.3 through 1.6 qualify connectivity, credential separation, database
freshness, and repository hygiene before any v2 baseline is generated.

## Connectivity qualification

- External database SSL enforcement is enabled at the Supabase project level.
- The direct database identity remains
  `db.kvrifaviwhzjztcbrfpy.supabase.co:5432`. Supabase direct endpoints require
  IPv6 unless the IPv4 add-on is enabled, so it is not the qualified
  `us-central1` Cloud Run path at this stage.
- Authenticated operator connectivity is qualified over the IPv4 Supavisor
  session endpoint `aws-0-us-east-2.pooler.supabase.com:5432`, using database
  `postgres` and the project-qualified owner username. A read-only connection
  reported PostgreSQL 17.6 and confirmed TLS in `pg_stat_ssl`.
- Database network restrictions currently allow `0.0.0.0/0` and `::/0` because
  the existing Cloud Run service has no reviewed static egress CIDR. Narrowing
  the allowlist to an invented address would make connectivity unreliable.
  Mandatory TLS and credential isolation are the active boundary; a later
  network restriction requires a provisioned, tested egress range.
- No IPv4 add-on, custom Postgres override, database DDL, Alembic stamp,
  application row, or Storage bucket was introduced during connectivity setup.

Supabase's connection-mode guidance is documented at
<https://supabase.com/docs/guides/database/connecting-to-postgres>.

## Credential boundaries

All secret values live in GCP Secret Manager in project `policyengine-api`.
The repository records names and intended use only.

| Access path | Identity or key | Secret Manager secret | Effective boundary |
| --- | --- | --- | --- |
| Initial project ownership and emergency administration | Supabase `postgres` owner | `policyengine-api-v2-alpha-prod-db-owner-password` | Provisioning only; not application or routine migration configuration |
| Generated v2 Alembic chain | `policyengine_v2_migrator` | `policyengine-api-v2-alpha-prod-db-migration-password` | Login, database connect, and `USAGE`/`CREATE` on `public`; no superuser, role creation, database creation, replication, or RLS bypass |
| Future ordinary v2 persistence | `policyengine_v2_runtime` | `policyengine-api-v2-alpha-prod-db-runtime-password` | Login, database connect, and `USAGE` on `public`; no schema creation, superuser, role creation, database creation, replication, or RLS bypass |
| Explicit Storage bootstrap | Supabase secret key `stage_8_storage_bootstrap` | `policyengine-api-v2-alpha-prod-storage-admin-key` | Dedicated, independently rotatable server-side credential exposed only to the Storage bootstrap operation |

The migration role owns the default privileges for objects it later creates:
ordinary table read/write and sequence use are granted to the runtime role.
Those grants do not create an application object or row.

Supabase secret keys are elevated server-side credentials that bypass RLS; the
platform does not represent them as Storage-only keys. Least privilege is
therefore enforced by using a distinct named key, storing it separately, and
making it available only to the explicit Storage initializer. Neither the
runtime database identity nor the migration identity receives this key.

The Cloud Run runtime service account previously held project-wide Secret
Manager accessor rights. Before completing this credential split, that broad
binding was replaced with per-secret access to its six existing production
runtime secrets: the gateway client secret plus the database, microdata,
Anthropic, OpenAI, and Hugging Face secrets. It has no project-wide Secret
Manager role and no binding on any Stage 8 administrative secret.

## Freshness qualification

On 2026-08-13, the recorded project was audited through a PostgreSQL
`READ ONLY` transaction over the qualified TLS connection.

- Connected project reference: `kvrifaviwhzjztcbrfpy`.
- Database and role: `postgres` as the provisioning owner.
- Application schema: `public` contains zero tables.
- Alembic history: no `alembic_version` table exists in any schema.
- Predecessor application state: no table matching the reviewed v2 model
  groups, `runtime_bundles`, or a population table exists in `public`.
- Storage initialization: `storage.buckets` contains zero rows.
- Service-managed schemas observed: `auth`, `extensions`, `graphql`,
  `graphql_public`, `pgbouncer`, `realtime`, `storage`, and `vault`. Their
  platform-owned tables do not count as application state.

The audit result is fresh. No reset, drop, stamp, reconciliation, or adoption
was required or performed. This qualification permits later v2 baseline
generation only when the migration workflow independently verifies the same
recorded target identity.

## Provisioning hygiene

The provisioning review completed on 2026-08-14 with these results:

- No application table, application row, Alembic stamp, or Storage bucket was
  created.
- No secret value, secret-bearing URL, SQL dump, scratch SQL, generated
  payload, or temporary configuration is tracked or staged.
- `supabase/.temp/` is ignored because the Supabase CLI writes ephemeral linked
  project metadata there even for management operations. Its generated file
  was removed after the project reference was recorded above.
- The local `.venv` used for read-only Postgres qualification is already an
  ignored development artifact and is not part of the change.
- The repository secret-pattern scan found no credential value in the changed
  files.
- The four Stage 8 GCP secrets have automatic replication and purpose labels;
  none grants access to the Cloud Run runtime service account.
- The dedicated Supabase Storage key exists as
  `stage_8_storage_bootstrap`; only its non-secret identifier and prefix are
  recorded, while the complete value exists only in GCP Secret Manager.

The dedicated Supabase foundation is therefore ready for the generated v2
schema work, subject to the target-identity gate implemented later in this
change.
