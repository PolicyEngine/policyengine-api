# Stage 9 v2 metadata deployment runbook

This runbook intentionally omits database hosts, database URLs, passwords,
project references, environment names, secret-resource names, service-account
identities, and physical dataset locations. Resolve those values from the
approved environment inventory and secret-management system.

## Scope

Stage 9 populates the dormant v2 US and UK reference catalogs and exposes
read-only preview endpoints from the Cloud Run ASGI application at
`GET /v2/us/metadata` and `GET /v2/uk/metadata`. Their generated OpenAPI
document is available at `GET /v2/openapi.json`. App Engine continues to run
the Flask v1 application and does not expose these routes. Stage 9 does not
change `GET /us/metadata`, `GET /uk/metadata`, their callers, or their v1 data
source. Existing clients must not be redirected to the preview endpoints.

The initializer creates only reusable logical input `Dataset` rows. Each row
has `is_output_dataset=false` and a null `storage_path`. It creates no
package-derived `DatasetVersion` rows or simulation/report output datasets and
does not modify `Simulation`, `Report`, or `ReportRun` rows or their dataset
references.

## Configuration and credential boundaries

Select the target with `V2_SUPABASE_PROJECT_REF` and
`V2_SUPABASE_ENVIRONMENT`. Confirm both values against the approved inventory
before connecting.

Use three separately managed database credentials:

| Operation | Configuration | Required database access |
| --- | --- | --- |
| Alembic schema upgrade | `V2_MIGRATION_DATABASE_URL` | Reviewed v2 schema changes; no application-runtime use |
| Catalog publication | `V2_DATA_WRITE_DATABASE_URL` | Row insertion, update, selection, temporary tables, and transaction-scoped advisory locks; no persistent schema changes |
| Preview GET requests | `V2_RUNTIME_DATABASE_URL` or `V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE` | Catalog selection only during Stage 9; no migration access |

Do not place more than one database URL in the environment of either the
migration or publication process. Cloud Run API processes receive only the
runtime Secret Manager resource identifier. They resolve the URL lazily when a
v2 preview request is made; application startup and unprefixed v1 requests do
not resolve it. App Engine does not receive the v2 runtime database URL or its
Secret Manager resource identifier.

Give the Cloud Run runtime identity access only to its approved runtime URL
secret. Do not give an application runtime identity access to the migration or
catalog-publication credentials.

## Pre-activation sequence

The release workflow calls `.github/workflows/initialize-v2-metadata.yml` for
the selected GitHub Environment before creating an API candidate. Its steps
must execute in this order:

1. Install the locked application dependencies from the same revision that
   will be deployed.
2. Supply only `V2_MIGRATION_DATABASE_URL` and the target identity, then run
   `.github/scripts/migrate_v2_metadata_schema.sh`. This upgrades the v2
   Alembic chain, confirms all heads are current, and detects ungenerated model
   changes.
3. Remove the migration URL from the command environment.
4. Supply only `V2_DATA_WRITE_DATABASE_URL` and the same target identity, then
   run `uv run python scripts/initialize_v2_metadata.py`.
5. Require the command to finish successfully and retain its non-secret JSON
   evidence before creating the candidate revision.
6. Deploy the Cloud Run candidate with the target identity and
   `V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE`. Keep all existing route selectors
   and traffic rules unchanged.

Any schema-upgrade, revision-check, extraction, compatibility, publication, or
post-publication validation failure stops the workflow before candidate
creation. The currently serving revision remains unchanged.

Initialization is an explicit deployment operation, once per target and
deployment artifact. It must never be called by a module import, an individual
web or worker process startup, a readiness check, an HTTP request, or an
ordinary process restart. The release workflow may repeat the explicit command
because publication is serialized and idempotent.

## Source and regional dataset behavior

The command obtains the US and UK models and packaged dependency selections
through PolicyEngine.py. `TaxBenefitModelVersion.version` stores the canonical
PolicyEngine.py version once. Variables, parameter nodes, parameters, logical
datasets, and regions reference that model-version row; parameter values obtain
the version through their parameter. Model descriptions, current-law IDs, and
metadata time-period options are stored on the model-version snapshot.
PolicyEngine Core and country-package versions are derived diagnostic evidence
and are not separately persisted.

Parameter extraction requires the PolicyEngine.py public history contract from
5.0.4 and later: values are ordered from oldest to newest, bounded `end_date`
values are inclusive and fall one day before the following `start_date`, and
the newest value is open-ended. The initializer validates that contract and
does not reorder, deduplicate, or repair package output. A value superseded on
the immediately following day therefore has equal start and end dates and is a
valid one-day interval.

The US national region uses `populace_us_2024`. A US state,
congressional-district, or place region uses its PolicyEngine.py regional
alternative when one is available. Until a later reviewed change removes the
fallback, a subnational region without such an alternative uses
`populace_us_2024`. The command emits one summary warning containing only the
affected region types and counts. UK regions use the
`enhanced_frs_2024_25` default certified by PolicyEngine.py 5.0.4.

Review the fallback summary on every new PolicyEngine.py release. A changed
count may identify an upstream catalog change that needs a reviewed dataset
selection even when publication otherwise succeeds.

## Validation evidence and retry

Successful JSON evidence contains:

- the canonical PolicyEngine.py version;
- the dependency versions derived from its packaged manifest;
- catalog entity counts;
- US fallback counts;
- elapsed publication time; and
- a success outcome.

It must contain no database URL, credential, environment or project identity,
physical dataset location, dataset release identifier, digest, parameter
value, or generated catalog payload.

The initializer validates the complete normalized source before database
mutation. Publication then uses one PostgreSQL transaction, a transaction-level
advisory lock, private temporary staging tables, bounded `COPY` operations, and
set-based reconciliation. Before commit it compares persisted relationships and
counts, confirms input-only region defaults, confirms canonical parameter-value
uniqueness, confirms no package-derived `DatasetVersion` rows were added, and
confirms existing simulation and report record counts are unchanged.

A failed attempt rolls back all catalog changes. Retry the same artifact only
after correcting the external failure. A matching retry preserves identifiers,
content, and row counts. Different normalized content under the same
PolicyEngine.py version fails for operator review; it is never silently
replaced. A later PolicyEngine.py version adds a catalog version without
deleting or modifying earlier versioned rows, including their logical datasets,
regions, model descriptions, current-law IDs, and time-period options.

## Production-scale qualification record

The Stage 9 implementation qualification used the locked PolicyEngine.py
5.0.4 distribution. Its manifest selected PolicyEngine Core 3.30.1,
PolicyEngine US 1.764.6, and PolicyEngine UK 2.90.2. Extraction produced 2
models, 2 model versions, 6,649 variables, 27,826 named parameter nodes, 99,006
parameters, 1,172,130 parameter values, 2 logical input datasets, and 826
regions. Publication took 33.916 seconds and added 7,979,842 bytes of measured
peak publisher memory. The US fallback summary reported 436 congressional
districts, 333 places, and 51 states.

Re-run the production-scale test only against disposable Postgres:

```bash
RUN_V2_CATALOG_PUBLICATION_QUALIFICATION=1 \
V2_ALEMBIC_DISPOSABLE_TEST=1 \
V2_MIGRATION_DATABASE_URL="<disposable-postgres-url>" \
uv run pytest -q tests/integration/test_v2_catalog_publication_qualification.py
```

Do not point this qualification command at a persistent staging or production
target.

## Preview verification

After Cloud Run candidate creation, explicitly request both preview GET
endpoints and validate their typed response envelopes. A request without a
`policyengine_version` query parameter selects the exact PolicyEngine.py version
installed in that candidate artifact. It does not select the newest database
row. Also request a known published version with, for example,
`?policyengine_version=5.0.4`, and confirm that the response contains that
exact version's complete snapshot.

A successful response has HTTP 200, `status: "ok"`, `message: null`, and a
typed `result`. A malformed or noncanonical explicit version returns a typed
HTTP 400 error. A valid explicit version that has not been published for the
country returns a typed HTTP 404 error. An absent or incomplete catalog for the
candidate's installed default version returns a typed HTTP 503 service error.
None of these outcomes reads or repairs v1. Unsupported countries and methods
return typed client errors.

Request `GET /v2/openapi.json` and confirm that the public document contains
the US, UK, and unsupported-country preview paths and explicit component schema
references for every documented response.

Also request the unprefixed US and UK metadata endpoints and confirm their
responses still come from v1. Do not modify route selectors, internal callers,
or traffic rules to use `/v2` during Stage 9.

## Rollback

If Cloud Run candidate verification or activation fails, keep or restore
traffic on the exact preceding Cloud Run revision. The pre-candidate workflow
leaves that revision untouched.

Leave successfully published v2 catalog rows and the v2 schema in place. They
are dormant, additive, and safe for an idempotent retry. Do not delete catalog
rows, reset the database, or downgrade Alembic as part of application rollback.
A schema downgrade is a separate reviewed operator operation against the
reconfirmed v2 target. Because every Cloud Run revision selects its own
installed PolicyEngine.py version, a preceding artifact reads its existing
snapshot without a database-wide current-version setting. If that snapshot is
absent, run that artifact's compatible explicit initializer before making its
candidate eligible for traffic.
