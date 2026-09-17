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
worker and evaluation-record contract.

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
  correlation and provenance fields.

The evaluation adapter uses bounded reason codes and never includes the raw
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
schema authority for the temporary evaluation tables. The companion
`policyengine-sim-api` implementation uses the corresponding versioned runtime
models and does not define another SQLModel schema or Alembic revision chain.
Changes that affect both repositories require coordinated review; no generated
cross-repository contract file is checked in or consumed at runtime.

## Artifact storage and retention

Stage 12 uses a dedicated, private GCS bucket or dedicated private bucket
namespace configured independently for each environment. No bucket name is
committed as a default. Object keys use this structure:

```text
stage-12-evaluation/<environment>/<year>/<month>/<evaluation-uuid>/
  inputs/<role>.json
  simulations/<role>.parquet
  reports/aggregate.json
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

Only the Simulation Entrypoint, the versioned worker application, the retention
process, and explicitly authorized operators may access the namespace. Browser
clients and ordinary Public API reads receive no access. Service identities use
the minimum object and row permissions required for their operation; runtime
identities receive no schema-migration permission.

`policyengine-api` is also the schema authority for the temporary Stage 12
tables. After the migration creates those tables, a reviewed, bounded one-off
operator script provisions one environment-specific PostgreSQL runtime role.
That role receives `SELECT`, `INSERT`, `UPDATE`, and `DELETE` only on
`stage12_evaluation_reports` and `stage12_evaluation_simulations`; cannot
create schema objects or hold privileged role attributes; and does not
participate in role membership. The one-off provisioning script is not part of
the repository, runtime, or deployment workflow and must be deleted after the
production role and secret have been independently verified. The companion
simulation deployment must connect with the resulting runtime secret and
exercise the required table operations in a rolled-back transaction. It must
also use the exact Modal service-account credential to create, read, and delete
a bounded object-storage canary. These consumer checks verify the live
configuration without creating another database-permission authority.

Inputs, simulation artifacts, aggregate artifacts, and their temporary parent
and child lifecycle rows have a 30-day retention period. Deployment must set
the retention value explicitly and must reject zero, negative, unbounded, or
greater-than-30-day values. Retention deletion removes private artifacts before
removing their lifecycle rows and must never present a missing artifact as an
available successful result.

The 30-day per-execution lifecycle is distinct from final removal of the two
temporary table schemas. After Stage 12 evaluation has ended and all retained
records have expired, a separately reviewed, autogenerated v2 Alembic revision
removes those tables. Production `simulations`, `reports`, `report_runs`, and
user-association records must not depend on them.

The tracked follow-up change identifier is
`retire-stage-12-evaluation-schema`. That change may begin only after dual
execution has ended and the newest parent and child rows have passed the
30-day retention limit. It owns the autogenerated v2 Alembic revision that
removes `stage12_evaluation_reports` and `stage12_evaluation_simulations`.
