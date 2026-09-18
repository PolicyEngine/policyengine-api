# Stage 12 worker implementation contract

This document records the implementation decisions required before the Stage 12
worker path can be built. It does not change a public request or response
contract and does not authorize the new path to provide production results.

The companion implementation is identified as
`PolicyEngine/policyengine-sim-api:stage-12-modal-worker-foundation` on the
feature branch of the same name. Its reviewed service plan is
`docs/migration/stage-12-modal-worker-foundation.md` in that repository. The
companion change explicitly preserves the existing public submission and
polling contracts; this repository remains the only owner of the generated
worker and comparison-record contract.

## Initial calculation flow

The first dual-execution flow is the standard annual society-wide comparison
identified as `economy` in `policyengine_api.migration_registry`. This flow is
submitted to the Simulation Entrypoint through
`POST /simulate/economy/comparison`.

This is the initial flow because it already crosses the Simulation Entrypoint
boundary and supplies separate baseline and reform policies. It therefore
exercises the Stage 12 report coordinator and independently scheduled
single-simulation functions without changing the Public API's synchronous
household implementation. Household calculation remains production-owned by
the current in-process implementation until Stage 13. Budget-window execution
remains outside this initial flow until Stage 15.

The reviewed Stage 12 adapter accepts the normalized annual comparison shape
currently produced by `EconomyService` and `SimulationEntrypointClient` when:

- `scope` is `macro`;
- `country` has a validated entry in the selected v2 version manifest;
- `baseline` and `reform` are JSON objects;
- `time_period` is one four-digit year;
- `region` is already normalized for the country;
- `data` is absent for the certified default dataset or identifies that exact
  dataset artifact; in both cases the packaged PolicyEngine.py bundle manifest
  supplies the authoritative identity, URI, digest, and revision;
- omitted `policyengine_version` and country-package `version` fields resolve
  to the exact versions in the selected bundle; when either field is supplied,
  it is an assertion and must match that bundle;
- `include_cliffs` is false;
- an optional `spm` selection has already passed the existing validation; and
- `_metadata` and `_telemetry`, when present, contain only their documented
  correlation and provenance fields. The Simulation Entrypoint request model
  strips `_metadata` and normalizes `_telemetry` to `telemetry`; the Stage 12
  adapter accepts and ignores that normalized correlation field.

The comparison-run adapter uses bounded reason codes and never includes the raw
request in a reason or log. The initial codes are:

| Code | Condition |
| --- | --- |
| `unsupported_flow` | The request is not an annual society-wide comparison. |
| `unsupported_scope` | The calculation scope is not `macro`. |
| `unsupported_budget_window` | The request is a multi-year budget-window calculation. |
| `unsupported_cliff_calculation` | `include_cliffs` is true. |
| `unsupported_country` | The v2 manifest has no validated worker for the country. |
| `unsupported_dataset` | The requested dataset is not certified by the selected bundle. |
| `missing_bundle_provenance` | Exact package or dataset provenance is absent. |
| `unsupported_options` | A calculation option has no reviewed v2 interpretation. |
| `unsupported_request_shape` | The request otherwise cannot be normalized without guessing. |

Every skipped request continues through the existing production implementation
unchanged. A skip does not create a partial simulation and does not change the
production response.

## Automatic execution and result comparison

`STAGE12_ENABLED` is the only Stage 12 execution setting. A missing value or
`0` disables automatic Stage 12 runs and rejects new direct submissions. `1`
submits every supported newly accepted annual society-wide calculation and
permits authenticated direct submissions. Any other value prevents service
startup. Changing the value requires a Cloud Run deployment. The separately
named Modal application remains deployed in either state.

For an enabled request, the Simulation Entrypoint first obtains the normal
production response, derives a deterministic Stage 12 identifier, prepares the
parent metadata in memory, and waits at most five seconds for Modal to
acknowledge the already-deployed report coordinator invocation. The Simulation
Entrypoint performs no Stage 12 database write on this submission path. It does
not wait for calculation or comparison completion and does not use a
process-local dispatch queue. Dispatch failure or timeout is logged and cannot
change the production response.

The Modal report coordinator creates or resolves the durable parent before it
starts child work. The deterministic identifier and parent uniqueness
constraint collapse repeated invocations for the same production job and v2
release into one logical run; a duplicate coordinator exits without starting
children when that run is already active or complete. Polls and cache hits do
not dispatch Stage 12 work. An unsupported input produces bounded telemetry but
no partial parent or simulation record.

After its independent baseline and reform simulations finish, the Stage 12
report coordinator computes its aggregate and waits up to 15 minutes to
retrieve the associated production result by its retained Modal function-call
identifier. It compares the complete aggregate result objects exactly and
writes the private comparison artifact described below. The existing
production result remains the only user-visible and authoritative result. The
comparison is attempted once for each Stage 12 execution. If production-result
retrieval, validation, artifact storage, or comparison-state persistence
fails, the successful Stage 12 calculation remains successful and its
comparison is recorded as failed. Ordinary submissions do not retry that
comparison, including repeated submissions that resolve to the same production
job. Any future operator-initiated comparison retry requires a separately
reviewed entry point and state transition.

The authenticated direct Stage 12 submission route accepts new work only when
`STAGE12_ENABLED=1`; a missing or zero value returns HTTP 503 without creating
a parent record or invoking Modal.
The authenticated status route remains available whenever its resources are
configured so existing runs remain inspectable. A direct POST returns after
Modal acknowledges the coordinator and before that coordinator is required to
create its parent row, so clients follow the returned short retry hint before
their first status request. Because a direct run has no production result, it
leaves comparison status `not_requested`.

## Versioned internal contracts

The canonical internal contract version is `1`. The framework-independent
Pydantic models under `policyengine_api.services.v2.simulations` and
`policyengine_api.services.v2.reports` are the source for producer and consumer
validation. They define:

- one strict single-simulation input;
- one report input composed of separate baseline and reform simulations;
- PolicyEngine.py bundle, country-package, data-package, dataset, and artifact
  revision provenance;
- private content-addressed artifact references;
- stable row-identity metadata; and
- canonical simulation and aggregate report artifact descriptors, including
  any detached calculation receipt needed to reproduce an aggregate result.

The canonical models also define the stored artifact payloads themselves.
`SimulationParquetPayloadContract` specifies the Parquet version, compression,
system columns, stable row and column ordering, entity identifier convention,
and required schema metadata. `AggregateReportArtifactPayload` validates the
complete aggregate JSON object before storage. Pydantic validators enforce
cross-field requirements that cannot be represented by field types alone.

Stage 12 lifecycle tables are not part of the persistent simulation or report
resource model. The reviewed SQLModel metadata in this repository remains the
schema authority for the temporary comparison tables. The companion
`policyengine-sim-api` implementation uses the corresponding versioned runtime
models and does not define another SQLModel schema or Alembic revision chain.
Changes that affect both repositories require coordinated review; no generated
cross-repository contract file is checked in or consumed at runtime.

## Artifact storage and retention

Stage 12 uses a dedicated, private GCS bucket or dedicated private bucket
namespace configured independently for each environment. No bucket name is
committed as a default. Object keys use this structure:

```text
stage-12-runs/<environment>/<year>/<month>/<comparison-run-uuid>/
  inputs/<role>.json
  simulations/<role>.parquet
  reports/aggregate.json
  reports/comparison.json
```

Normalized calculation inputs and aggregate report outputs use deterministic
UTF-8 JSON with sorted object keys, compact separators, and non-finite numbers
rejected. Population-scale simulation outputs use Parquet with Zstandard
compression, a fixed schema version, stable identifier columns, and a
deterministic column order. Database rows store only private object references,
SHA-256 content digests, schema versions, row-identity metadata, and bounded
provenance. When an option such as SPM produces a detached calculation receipt,
the simulation descriptor and Parquet metadata retain it so the coordinator can
validate the receipt before reproducing the existing aggregate response.

Only the Simulation Entrypoint, the versioned worker application, the bucket's
object-lifecycle process, and explicitly authorized operators may access the
namespace. Browser clients and ordinary Public API reads receive no access.
Service identities use the minimum object and row permissions required for
their operation; runtime identities receive no schema-migration permission.

`policyengine-api` is also the schema authority for the temporary Stage 12
tables. After the migration creates those tables, a reviewed, bounded one-off
operator script provisions one environment-specific PostgreSQL runtime role.
That role receives `SELECT`, `INSERT`, `UPDATE`, and `DELETE` only on
`stage12_evaluation_reports` and `stage12_evaluation_simulations`; cannot
create schema objects or hold privileged role attributes; and does not
participate in role membership. The same environment-specific role and secret
are presented to the Simulation Entrypoint and Modal v2 application: Cloud Run
uses it only for temporary status reads, while the Modal report coordinator
owns all parent and child writes. The one-off provisioning script is not part of
the repository, runtime, or deployment workflow and must be deleted after the
production role and secret have been independently verified. The companion
simulation deployment must connect with the resulting runtime secret and
exercise the required table operations in a rolled-back transaction. It must
also use the exact Modal service-account credential to create, read, and delete
a bounded object-storage canary. These consumer checks verify the live
configuration without creating another database-permission authority.

Inputs, simulation artifacts, aggregate artifacts, and comparison artifacts are
private objects subject to the bucket's 30-day object-lifecycle policy. The
comparison artifact records the canonical SHA-256 digest of each complete
aggregate result and every differing leaf, with its JSON Pointer path, value
presence, both values, and numeric deltas when applicable. It does not duplicate
either complete result object. The parent row stores only the comparison status,
artifact URI and digest, schema version, completion time, and bounded error
metadata.

Stage 12 does not register a periodic cleanup function and does not delete its
temporary PostgreSQL rows after 30 days. The existing `retention_expires_at`
column remains only for compatibility with the already-deployed physical
schema. The rows remain restricted operational history until Stage 14 removes
the temporary schema.

The 30-day artifact lifecycle is distinct from final removal of the two
temporary table schemas. After Stage 12 comparison running has ended, a
separately reviewed, autogenerated v2 Alembic revision in Stage 14 removes
those tables. Production `simulations`, `reports`, `report_runs`, and
user-association records must not depend on them.

The tracked follow-up change identifier is
`retire-stage-12-comparison-schema`. That Stage 14 change may begin only after
automatic comparison running has ended. It owns the autogenerated v2 Alembic
revision that removes `stage12_evaluation_reports` and
`stage12_evaluation_simulations`.
Those table names and the `evaluation_id` column are retained solely as legacy
physical database identifiers during Stage 12; application types and service
interfaces use comparison-run terminology.
