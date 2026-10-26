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
`subtracts_parameter_path`, `enum_values` (each value's name and its label,
in the type the country package declares), `unit` (for example
`currency-USD`) and `definition_period` (`year`, `month` or `eternity`), which
the household builder and breakdown read (currency formatting, per-period
labels and household validation). Where a variable's `adds` or `subtracts` list
comes from a parameter, `part_parameter_values` maps that
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
`parameter_name` keys to page only those parameters' values.

Every v2 metadata route reads its query through the shared query models in
`policyengine_api.query_parameters` (`CatalogQuery`, `CatalogPageQuery` and the
resource-specific models built on them): unknown parameters, repeated scalar
parameters, a missing or unsupported `country_id`, a malformed
`policyengine_version` and out-of-range `offset` or `limit` values are
rejected with HTTP 422 before any read. Before, the routes other than the
`/v2/model-catalog` ones ignored unknown parameters, and an unsupported country
or malformed version returned HTTP 400 from the read. A country given in the
path (`/v2/tax-benefit-models/by-country/{country_id}`) that is not supported
still returns HTTP 400.

## Database round trips per request

Metadata reads use sessions in autocommit mode on the shared v2 pool
(`get_v2_read_session_factory`), which only the metadata reader opens: each
read is one statement on rows a published catalog version never changes, so no
transaction is needed, and the database receives no `BEGIN` before the reads
and no `ROLLBACK` when the session closes. The sessions refuse to flush added
or changed rows (`ReadOnlySessionError`); a statement passed directly to
`execute` is not checked, so the metadata connectors keep to `SELECT`. Each process also keeps every catalog version a request has
selected (`SelectedCatalogStore`), since a published version never changes, so
later requests for the same country and version skip the selection query;
failed selections are not kept. Measured with statement logging in a local
database, a page of 500 parameters or one parameter's values took five
statements per request before (the pool's liveness check, `BEGIN`, the catalog
selection, the read and `ROLLBACK`) and two after, once the process has
selected that version (the liveness check and the read). A route that makes
several reads, such as `/v2/model-catalog` (regions and datasets), sends one
statement per read after the liveness check. The pool's liveness check
(`pool_pre_ping`) is unchanged.

## Response caching

Every successful metadata response carries a strong `ETag`, a hash of its
exact body, and `Cache-Control: public`. A request that names its catalog with
`policyengine_version` may be reused for a day (`max-age=86400`): a published
catalog version never changes, so such a response changes only with the
route's response format or with the day it is read on, and the `ETag` lets a
client revalidate after the day. A request without it selects the running
version, which changes on deploy, and may be reused for five minutes
(`max-age=300`). A response that depends on the request's UTC day, which is
`GET /v2/parameter-values?current=true` (the values in effect today), takes
the request's instant once: the read selects that day's values, and the
response may be reused only until the UTC midnight after that instant,
whichever lifetime would otherwise apply (`max-age=0` if its headers are
written after that midnight). A request whose `If-None-Match` names the current `ETag` (strong or
weak form, alone or in a list) gets HTTP 304 with no body. Error responses
carry neither header. Every cacheable response, and every 304, carries
`Vary: Origin, Accept-Encoding`, each value once: the API reflects every
origin in `Access-Control-Allow-Origin` and a request without `Origin` gets no
such header, so a shared cache must keep responses apart by `Origin`, and gzip
compresses bodies for clients that accept it. A 304 carries the same `Vary` as
its 200. The CORS and gzip middleware append to `Vary` without checking for
values already present, so the application's outermost middleware
(`UniqueVaryMiddleware`) lists each value once. `ETag` is
listed in `Access-Control-Expose-Headers`, so
browser scripts on other origins can read it (`Cache-Control` is readable
without that).

Each API process also keeps the serialized bodies of `/v2/model-catalog` and
`/v2/model-catalog/variables` once built, each with its `ETag` computed once,
for up to eight route, country and version combinations (least recently used
dropped first; the 6.10.0 US variables body is 4,190,824 bytes uncompressed,
so eight entries hold about 12 MB for both countries' two routes at two
versions). A response is kept under the exact version it was read from,
so a request without `policyengine_version` (the process's running version,
which never changes while it runs) and one naming that version share it. Only
the first successful request per process reads the database. Requests that
arrive while that read is in progress wait for it and all receive its outcome,
the kept response or a copy of its error response, so one failing read is not
repeated by each of them; a failed read is not kept, so the first request after
it reads again. Measured locally against the full 6.10.0 US catalog, the
variables route takes about 160 ms when read and about 25 ms when kept, most of
it compression.

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
   It stops before reading anything if a UK version needs checking and
   `HUGGING_FACE_TOKEN` is unset, because the UK data repository is private.
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
publish these fields, and names each missing field: 6.7.5 and the locked 6.10.0
publish only the variables' unit and definition period. It also stops if the
model has other than one person entity, names a basic input or a parameter path
that is not published, gives enum labels that do not match the variable's
possible values or are not JSON scalars, or gives a flag that is not a boolean.
An opt-in test (`tests/integration/test_v2_catalog_metadata_parity.py`, run by
the v2 integration check) compares every format 2 field for the US and the UK
with what `/{country}/metadata` builds.

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

Regions come from the Public API's checked-in reference files, one per country
(`policyengine_api/data/v2/catalog/region_reference_files/`), not from
PolicyEngine.py's region registry. Each row lists a region's code, label, type,
parent, US state, the value that selects its households, and the v1 identifier
it replaces. Each country's default dataset is the one the installed
PolicyEngine.py release names in its manifest (`default_dataset`); the Public
API sets none of its own. Publication stops if the manifest names no default,
if the release does not certify it, or if the release routes national regions
to another dataset. A scoping rule per country and region type gives each
region its dataset from the certified data release and its filter:

| Regions | Dataset | Filter |
| --- | --- | --- |
| US national | the release's default dataset (`populace_us_2024` in 6.10.0) | none |
| US states and congressional districts | the release's state and district dataset | `row_filter` on `state_fips` or `congressional_district_geoid` |
| UK national | the release's default dataset (`microcosm_uk_2024_25` in 6.10.0) | none |
| UK nations | the release's default dataset | `row_filter` on `region` |
| UK constituencies and local authorities | the release's local-area dataset (`microcosm_uk_2024_25_dense` in 6.10.0), which carries their codes | `row_filter` on `constituency_code_oa` or `la_code_oa`, value the ONS code |

If the release names no dataset for a US state or district, those regions use
the default dataset and the command emits one summary warning with the affected
region types and counts. A UK constituency or local authority cannot fall back,
since the national file has no area codes: a release that routes no dataset to
their type stops publication. Region types without a rule, such as US places
until the data can select them, are left out and counted in the evidence's
`omitted_region_summaries`.

Before a new catalog version is published, the command reads the HDF5 metadata
of each dataset the row filters use, with ranged requests at the pinned
revision, and stops if a filter's column is missing from its dataset's
household columns. It does not check that a column holds rows for every
region's value.

Review the fallback and omitted-region summaries on every new PolicyEngine.py
release. A changed count may identify an upstream change to the certified data
release even when publication otherwise succeeds.

A catalog version is identified by its country and PolicyEngine.py version and
never changes once published. When the command republishes a stored version
whose staged regions differ from the stored ones, it keeps the stored regions
unchanged, prints a warning with the country, the version and the counts of
staged region rows the stored version lacks and of stored rows not staged, and
continues. Its evidence then describes what is stored: the region count is the
stored one, `kept_regions` lists the country, version, stored and staged region
counts, and the fallback and omitted-region summaries leave that country out,
since they describe staged regions that were not published. Every other table
must still match exactly. Region reference changes therefore take effect in the
next catalog version that is published.

## Validation evidence and retry

Successful JSON evidence contains:

- the canonical PolicyEngine.py version;
- the dependency versions derived from its packaged manifest;
- catalog entity counts;
- fallback counts and omitted-region counts by country and region type, and
  the stored and staged region counts of any stored version whose regions were
  kept;
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
first table that differs; it is never silently replaced. Regions are the
exception: they come from the Public API's reference files, so a stored version
keeps the regions it was published with (see "Source and regional dataset
behavior"). A later PolicyEngine.py version adds a catalog version without
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
version returns a typed HTTP 422 error. A valid explicit version that has not
been published for the country returns a typed HTTP 404 error. An absent
catalog for the candidate's installed default version returns a typed HTTP 503
service error. None of these outcomes reads or repairs v1. Unsupported
countries and methods
return typed client errors.

The same test loads each country's catalog in parts as a client starting
cold would: `GET /v2/model-catalog` for the running version, then
`/v2/model-catalog/variables` for that exact version twice (the second request
may be served by another instance, so its time is not necessarily a kept
response's) and once more with `If-None-Match`, which must return 304, then a
page of 500 parameters, one parameter's values (the two routes measured at
0.8–2.6 s and 0.5–0.65 s in production on 2026-10-21) and that parameter by
name. It appends each request's time and body size to the GitHub job summary,
even when an assertion fails, so every staging and production release records
these route times against its own catalog.

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
