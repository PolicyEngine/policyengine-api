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

## Loading a catalog version on demand

`GET /v2/model-catalog?country_id=<us|uk>[&policyengine_version=<version>]`
returns only the small parts of one catalog version: the model and model
version (with the current-law policy id and the years offered), the entities
(`key`, `plural`, `is_person`), the basic inputs, every region and logical
input dataset, and the economy choices. A catalog without regions, such as a
household-only country's, has empty region, dataset and economy-choice lists
rather than an error. A version published before catalog format 2 has a null
`catalog_format` and empty entities and basic inputs. The result names the
selected PolicyEngine.py version, so a client that starts without a version
learns the running one and requests every other part for that exact version.
The query uses the shared `CatalogQuery` model: unknown and repeated
parameters are rejected.

`GET /v2/model-catalog/variables` (same query) returns every variable of the
version in name order, in one response, with the catalog format 2 fields:
`is_input_variable`, `hidden_input`, `module_name`, `adds_parameter_path`,
`subtracts_parameter_path` and `enum_values` (each value's name and its label,
in the type the country package declares). Where a variable's `adds` or
`subtracts` list comes from a parameter, `part_parameter_values` maps that
parameter's path to its current-law values in start-date order
(`start_date`, `end_date`, `value`), so a client picks the list for the year
it shows instead of the list resolved on 2025-01-01; a path whose parameter
the version lacks maps to an empty list. `GET /v2/variables` pages carry the
same variable fields.

`GET /v2/model-catalog/parameters` takes the same query plus one or more
`name` keys (at most 100, each an exact parameter path) and returns those
parameters in name order, each with its `economy` and `household` flags and its
current-law values in start-date order, in one response: a client showing or
editing a reform loads all of its parameters at once. `node_labels` maps each
ancestor of a returned parameter that the version stores as a parameter node
to its stored label (null when it has none), for breadcrumbs; a bracket index
such as `rates[0]` counts as a child of its schedule `rates`. `missing_names`
lists requested names the version has no parameter for, so a reform saved
against an older version still opens. `GET /v2/parameters` pages and details
carry the same `economy` and `household` flags.

`GET /v2/parameters` also accepts repeated `name` keys (at most 100) to page
only those exact parameters, and `GET /v2/parameter-values` repeated
`parameter_name` keys to page only those parameters' values. Both routes now
read their query through the shared query models (`ParameterCollectionQuery`
and `ParameterValueCollectionQuery`): unknown and repeated scalar parameters,
an unsupported `country_id` and a malformed `policyengine_version` are
rejected with HTTP 422 before any read; before, the last two returned HTTP 400
from the read and unknown parameters were ignored.

## Response caching

Every successful metadata response carries a strong `ETag`, a hash of its
exact body, and `Cache-Control: public`. A request that names its catalog with
`policyengine_version` may be reused for a day (`max-age=86400`): a published
catalog version never changes, so only a change to the route's response format
can change such a response, and the `ETag` lets a client revalidate after the
day. A request without it selects the running version, which changes on
deploy, and may be reused for five minutes (`max-age=300`). A request whose
`If-None-Match` names the current `ETag` (strong or weak form, alone or in a
list) gets HTTP 304 with no body. Error responses carry neither header.

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
4. Supply only `V2_DATA_WRITE_DATABASE_URL` and the same target identity, then
   run `uv run python scripts/publish_v2_metadata_catalog.py`.
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

Catalog format 2 adds the metadata the app's v3 workspace reads, taken only
from PolicyEngine.py's public records, which carry it from the release that
publishes entities, basic inputs and these flags:

| Record | Fields |
| --- | --- |
| Model version | `catalog_format` (2), `entities` (`key`, `plural`, `is_person`, in the package's order), `basic_inputs` (the household builder's default fields) |
| Variable | `is_input_variable`, `hidden_input`, `module_name`, `adds_parameter_path` and `subtracts_parameter_path` (the parameter whose dated value lists the variables summed; `adds` and `subtracts` keep the list PolicyEngine.py resolved), `enum_values` (`value` and declared `label`, in order), `unit` (for example `currency-USD`) and `definition_period` (`year`, `month` or `eternity`), which the household builder and breakdown read |
| Parameter | `economy`, `household` |

Bracket schedules are parameter nodes with their stored label, or none when the
package stores none. An empty basic-input list is stored as empty. Extraction
stops before reading any record if the installed PolicyEngine.py does not
publish these fields, and names each missing field: 6.7.5 and 6.11.1
publish only the variables' unit and definition period. It also stops if the
model has other than one person entity, names a basic input or a parameter path
that is not published, gives enum labels that do not match the variable's
possible values or are not JSON scalars, or gives a flag that is not a boolean.
An opt-in test, `tests/integration/test_v2_catalog_metadata_parity.py`,
compares every format 2 field for the US and the UK with what
`/{country}/metadata` builds. CI does not run it, because it extracts every
variable and parameter of the installed models, with their values, and builds
each country's v1 metadata; set `RUN_V2_CATALOG_METADATA_PARITY=1` to run it.

Publication never rewrites a stored version. A version published before
format 2 has a null `catalog_format` and null format 2 fields, and later
publications of the same PolicyEngine.py version compare it without those
fields. The first PolicyEngine.py version published after format 2 deploys
carries them.

Parameter extraction requires the PolicyEngine.py public history contract from
5.0.4 and later: values are ordered from oldest to newest, bounded `end_date`
values are inclusive and fall one day before the following `start_date`, and
the newest value is open-ended. The initializer validates that contract and
does not reorder, deduplicate, or repair package output. A value superseded on
the immediately following day therefore has equal start and end dates and is a
valid one-day interval.

Each country's default dataset is the one the installed PolicyEngine.py
release names in its manifest (`default_dataset`); the Public API sets none of
its own. Publication stops if the manifest names no default, or if the release
gives the national region another dataset. The US national region uses the
release's default (`populace_us_2024` in 6.11.1). A US state,
congressional-district, or place region uses its PolicyEngine.py regional
alternative when one is available. Until a later reviewed change removes the
fallback, a subnational region without such an alternative uses the default.
The command emits one summary warning containing only the affected region
types and counts. The UK national and country regions use the release's
default (`microcosm_uk_2024_25` in 6.11.1); a country filters that national
file. UK constituency and local-authority regions use the dataset
PolicyEngine.py routes them to, `microcosm_uk_2024_25_dense`, because the
national file has no area codes.

Review the fallback summary on every new PolicyEngine.py release. A changed
count may identify an upstream change to the release's datasets even when
publication otherwise succeeds.

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
5.2.0 distribution. Its manifest selected PolicyEngine Core 3.30.1,
PolicyEngine US 1.764.6, and PolicyEngine UK 2.90.2. Extraction produced 2
models, 2 model versions, 6,649 variables, 27,813 named parameter nodes, 99,006
parameters, 1,172,130 parameter values, 2 logical input datasets, and 826
regions. Publication took 24.120 seconds and added 7,968,103 bytes of measured
peak publisher memory. The US fallback summary reported 436 congressional
districts, 333 places, and 51 states.

The production-scale test that measured this,
`tests/integration/test_v2_catalog_publication_qualification.py`, was removed
with PolicyEngine/policyengine-api#4149: CI no longer loads the complete
catalog. Each release publishes and validates it against staging, then
production (`seed-v2-database.yml`), and the cross-database integration tests
publish selected parameter folders of the installed models and a catalog of
edge-case values (`docs/engineering/skills/testing.md`).

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
