# Stage 8 Supabase target handling

This document records how the dedicated Supabase target is selected and
qualified without publishing its concrete identity. Organization IDs, project
names and references, regions, hosts, endpoints, usernames, secret-resource
names, network allowlists, provisioning timestamps, and service-account
identities must remain in the approved operator inventory, deployment
configuration, or secret-management surface—not migration documentation.

## Target identity resolution

| Required field | Approved source |
| --- | --- |
| Supabase organization | Operator platform inventory |
| Project name and reference | Operator inventory and `V2_SUPABASE_PROJECT_REF` |
| Region | Operator platform inventory |
| Environment classification | `V2_SUPABASE_ENVIRONMENT` |
| Database host and pooler endpoint | Validated migration URL and provider console |
| Storage API origin | `V2_SUPABASE_STORAGE_URL` |
| Private bucket | `V2_SUPABASE_STORAGE_BUCKET` |
| Owning team | Internal ownership inventory |

The runtime and migration configuration must fail closed if the supplied values
do not match the approved inventory. This repository records variable names and
validation behavior only.

## Purpose

The project is the dedicated Postgres and Storage destination for the API
v2-alpha migration. Stage 8 establishes and qualifies the platform while Cloud
SQL and the existing API and compute paths remain primary. Later migration
stages may populate and activate the target under their own reviewed cutover
contracts.

## Selection requirements

- Use a newly provisioned project dedicated to the API v2-alpha migration; do
  not adopt an unrelated existing project.
- Resolve the owning organization, unique project identity, environment
  purpose, and supported region before creation.
- Select the reviewed region according to latency and operational requirements
  recorded in the operator inventory.
- Treat a later region change as a new-project migration because the provider's
  project region is fixed at the infrastructure level.
- Keep the project dormant during Stage 8: no production request reads, writes,
  routes, or compute use it.

## Provisioning boundary

Project creation is an explicit operator action. It may establish the project,
database service, ownership, networking, and secret placement, but it must not
create application tables or rows, stamp Alembic, or initialize a Storage
bucket. Application schema and versioned application data remain exclusively
owned by the generated v2 Alembic chain. Storage initialization is a separate,
later idempotent operation.

Store the initial owner credential in the approved secret manager as a
provisioning-only credential. Its value and resource identifier are not
recorded here and must not become routine migration or application-runtime
configuration.

## Connectivity qualification

- Enforce external database TLS at the project level.
- Resolve direct and pooled database endpoints from the provider console and
  validated operator configuration; do not copy them into repository docs.
- Qualify operator connectivity through the reviewed TLS endpoint using the
  provisioning identity only for the bounded setup operation.
- Maintain the reviewed database network allowlist outside the repository. Do
  not infer or invent an address range when the deployed service lacks a
  qualified static egress range.
- Confirm the observed Postgres engine and TLS session meet the migration
  requirements without recording connection strings, hosts, usernames, or
  addresses in logs or documentation.
- Do not introduce an unreviewed networking add-on, custom Postgres override,
  database DDL, Alembic stamp, application row, or Storage bucket during
  connectivity setup.

Supabase's connection-mode guidance is documented at
<https://supabase.com/docs/guides/database/connecting-to-postgres>.

## Credential boundaries

All secret values live in the approved secret-management surface. The
repository records access classes and intended use only:

| Access path | Credential class | Effective boundary |
| --- | --- | --- |
| Initial ownership and emergency administration | Provisioning owner credential | Provisioning only; not application or routine migration configuration |
| Generated v2 Alembic chain | Dedicated migration credential | Database connect and reviewed schema creation; no platform administration |
| Future ordinary v2 persistence | Dedicated runtime credential | Ordinary application data access; no schema migration or platform administration |
| Explicit Storage bootstrap | Dedicated server-side Storage administration key | Independently rotatable and exposed only to the Storage bootstrap operation |

The migration role owns the default privileges for objects it later creates;
ordinary table read/write and sequence use are granted to the runtime role.
Those grants do not create an application object or row.

Supabase server-side secret keys are elevated credentials. Least privilege is
therefore enforced by using a distinct key, storing it separately, and making
it available only to the explicit Storage initializer. Neither the runtime
database identity nor the migration identity receives this key.

Runtime service accounts must not hold project-wide secret-access rights. Give
each identity per-secret access only to the runtime values it needs, and grant
no Stage 8 migration or Storage-administration secret to an application runtime
identity.

## Freshness qualification

Before baseline generation, audit the approved project through a PostgreSQL
`READ ONLY` transaction over the qualified TLS connection. Retain the concrete
audit evidence only in the approved operator record.

The audit must establish all of the following:

- the connected project identity matches the approved target;
- the application schema contains zero application tables;
- no `alembic_version` table or revision history exists;
- no predecessor v2 model table, `runtime_bundles`, or population table exists;
- no application-owned Storage bucket or object has been initialized; and
- observed provider-managed schemas contain only platform-owned state.

Any mismatch or ambiguity fails closed. Do not reset, drop, stamp, reconcile,
or adopt the target automatically. A successful audit permits later v2 baseline
generation only when the migration workflow independently verifies the same
approved target identity.

## Provisioning hygiene

Before declaring the foundation ready, verify:

- no application table, application row, Alembic stamp, or Storage bucket was
  created during provisioning;
- no secret value, secret-bearing URL, target identifier, endpoint, SQL dump,
  scratch SQL, generated payload, or temporary configuration is tracked or
  staged;
- Supabase CLI state and other linked-project metadata remain ignored and are
  removed after the bounded operator action;
- local qualification environments remain ignored development artifacts;
- the repository secret-pattern scan finds no credential or infrastructure
  identity in changed migration documents;
- administrative secrets have purpose labels and no application runtime access;
  and
- the dedicated Storage credential exists only in the approved secret manager
  and explicit bootstrap environment.

The dedicated Supabase foundation is ready for generated v2 schema work only
after these controls pass and the target-identity gate confirms the separately
maintained approved inventory.
