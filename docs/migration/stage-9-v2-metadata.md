# Stage 9 v2 metadata deployment runbook

This runbook intentionally omits database hosts, database URLs, passwords,
project references, environment names, secret-resource names, service-account
identities, and physical dataset locations. Resolve those values from the
approved environment inventory and secret-management system.

## Scope

Stage 9 populates the dormant v2 US and UK reference catalogs and exposes
read-only, resource-specific routes from the Cloud Run ASGI application under
`/v2`. The routes separately serve tax-benefit models, model versions,
variables, parameters, direct parameter-tree children, canonical parameter
values, logical input datasets, regions, and compact economy-selection
options. Collection routes require `country_id`, use bounded `offset` and
`limit` pagination, and never assemble the complete catalog into one response.
The generated OpenAPI document is available at `GET /v2/openapi.json`.

The unprefixed Flask/API v1 routes remain mounted within the Cloud Run ASGI
application and do not expose these resources. Stage 9 does not change
`GET /us/metadata`, `GET /uk/metadata`, their callers, or their v1 data source.
Existing clients must not be redirected to the v2 resource routes.

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
not resolve it.

Give the Cloud Run runtime identity access only to its approved runtime URL
secret. Do not give an application runtime identity access to the migration or
catalog-publication credentials.

## Pre-activation sequence

The release workflow calls `.github/workflows/seed-v2-database.yml` for
the selected GitHub Environment before creating an API candidate. Its steps
must execute in this order:

1. Install the locked application dependencies from the same revision that
   will be deployed.
2. Supply only `V2_MIGRATION_DATABASE_URL` and the target identity, then run
   `.github/scripts/migrate_v2_metadata_schema.sh`. This upgrades the v2
   Alembic chain, confirms all heads are current, and detects ungenerated model
   changes.
3. Remove the migration URL from the command environment.
4. Supply only `V2_DATA_WRITE_DATABASE_URL`, the same target identity and
   `HUGGING_FACE_TOKEN` (from the organization secret
   `PE_UK_PRIVATE_HF_READ_TOKEN`), then run
   `uv run python scripts/publish_v2_metadata_catalog.py`. Before publishing a
   catalog version that is not stored yet, the command reads the certified data
   artifacts its regions' filters use and stops if one cannot select a region.
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

Regions come from the Public API's checked-in reference files, one per country
(`policyengine_api/data/v2/catalog/region_reference_files/`), not from
PolicyEngine.py's region registry. Each row lists a region's code, label, type,
parent, US state, the value that selects its households, and the v1 identifier
it replaces. A scoping rule per country and region type gives each region its
dataset from the certified data release and its filter:

| Regions | Dataset | Filter |
| --- | --- | --- |
| US national | the release's national dataset (`populace_us_2024`) | none |
| US states and congressional districts | the release's state and district dataset | `row_filter` on `state_fips` or `congressional_district_geoid` |
| UK national | `enhanced_frs_2024_25` | none |
| UK nations | `enhanced_frs_2024_25` | `row_filter` on `region` |
| UK constituencies and local authorities | `enhanced_frs_2024_25` | `weight_replacement`: field `parliamentary_constituency_weights` or `local_authority_weights`, value the ONS code |

A weight matrix must come from the same release as the dataset it reweights.
If the release names no dataset for a sub-national type, its regions use the
default dataset and the command emits one summary warning with the affected
region types and counts. Region types without a rule, such as US places until
the data can select them, are left out and counted in the evidence's
`omitted_region_summaries`.

Before a new catalog version is published, the command reads the HDF5 metadata
of each artifact the filters use, with ranged requests at the pinned revision:
publication stops if a row filter's column is missing from its dataset's
household columns, or if a weight matrix's row count differs from its row
lookup (`constituencies_2024.csv`, `local_authorities_2021.csv`) or the lookup
lacks a region's code.

Review the fallback and omitted-region summaries on every new PolicyEngine.py
release. A changed count may identify an upstream catalog change that needs a
reviewed dataset selection even when publication otherwise succeeds.

A catalog version is identified by its country and PolicyEngine.py version and
never changes once published. When the command republishes a stored version
whose staged regions differ from the stored ones, it keeps the stored regions
unchanged, prints a warning with the country, the version and the counts of
staged region rows the stored version lacks and of stored rows not staged, and
continues. Every other table must still match exactly.
Region reference changes therefore take effect in the next catalog version
that is published.

## Validation evidence and retry

Successful JSON evidence contains:

- the canonical PolicyEngine.py version;
- the dependency versions derived from its packaged manifest;
- catalog entity counts;
- fallback counts and omitted-region counts by country and region type;
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
PolicyEngine.py version fails for operator review, with an error naming the
first table that differs; it is never silently replaced. Regions are the exception: they come from the Public API's reference
files, so a stored version keeps the regions it was published with (see
"Source and regional dataset behavior"). A later PolicyEngine.py version adds a catalog version without
deleting or modifying earlier versioned rows, including their logical datasets,
regions, model descriptions, current-law IDs, and time-period options.

## Production-scale qualification record

The Stage 9 implementation qualification used the locked PolicyEngine.py
5.2.0 distribution. Its manifest selected PolicyEngine Core 3.30.1,
PolicyEngine US 1.764.6, and PolicyEngine UK 2.90.2. Extraction produced 2
models, 2 model versions, 6,649 variables, 27,813 named parameter nodes, 99,006
parameters, 1,172,130 parameter values, 2 logical input datasets, and 826
regions. Publication took 24.120 seconds and added 7,968,103 bytes of measured
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

Before either Cloud Run candidate is promoted, the release workflow runs
`tests/integration/test_live_v2_metadata.py` against its tagged URL. The test
forces runtime Secret Manager resolution and requests US and UK collections
for variables, parameters, parameter values, datasets, and regions, followed
by model resources and `GET /v2/economy-options`. It confirms that
parameter collection responses do not contain parameter values and that direct
resource requests remain bounded. The existing Cloud Run candidate test in the
same workflow continues to verify the unprefixed v1 metadata routes. A request
without a `policyengine_version` query parameter selects the exact
PolicyEngine.py version installed in that candidate artifact. It does not
select the newest database row. Also request a known published version with,
using the version pinned in the candidate's `pyproject.toml`, and confirm that
each response identifies that exact selected version.

A successful response has HTTP 200, `status: "ok"`, `message: null`, and a
typed `result`. Collection results contain `policyengine_version`, `items`,
`offset`, `limit`, and `has_more`; detail results contain
`policyengine_version` and `item`. A malformed or noncanonical explicit
version returns a typed HTTP 400 error. A valid explicit version that has not
been published for the country returns a typed HTTP 404 error. An absent
catalog for the candidate's installed default version returns a typed HTTP 503
service error. None of these outcomes reads or repairs v1. Unsupported
countries and methods
return typed client errors.

Request `GET /v2/openapi.json` and confirm that the public document contains
every documented resource path and explicit component schema references for
success and error responses.

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
