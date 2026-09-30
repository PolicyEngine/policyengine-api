# Observability engineering rules

Read this file before changing request correlation, calculation correlation,
logging, traces, metrics, simulation requests, or runtime stage names.

## Identifier registry

Use each identifier for its defined scope:

| Identifier | Scope | Created by | Durable |
| --- | --- | --- | --- |
| `request_id` | One HTTP request | HTTP request instrumentation | No |
| `observability_id` | One complete household calculation or society report | The first service that accepts the calculation | Yes for asynchronous reports |
| `submission_claim_id` | One attempt to acquire ownership of a simulation submission | API v1 economy service | Only as submission metadata |
| `job_id` | One annual simulation job | Simulation API | Yes, as functional job state |
| `batch_job_id` | One budget window simulation job | Simulation API | Yes, as functional batch state |
| `evaluation_id` | One Stage 12 comparison report | Stage 12 report construction | Yes, as functional report state |
| `simulation_execution_id` | One Stage 12 baseline or reform simulation | Stage 12 coordinator | Yes, as functional simulation state |

`observability_id` is a canonical UUID string used only to query diagnostic
records. Do not use it for idempotency, cache ownership, authorization,
database identity, routing, or calculation behavior. Do not create one for
health checks, metadata reads, invalid requests, missing reports, or ordinary
status requests.

## HTTP lifecycle

Transport `observability_id` only in
`X-PolicyEngine-Observability-Id`. HTTP middleware validates an incoming value
and stores it as a candidate. Middleware must not bind it or generate a new
value for every request.

A calculation boundary calls `start_observability_id`. This uses an already
bound value, then a valid incoming candidate, and otherwise creates a UUID. It
binds the selected value to the request and observability runtime. Household
calculation routes call it only after request validation. On a cache miss, the
route constructs and validates the PolicyEngine situation, binds the identifier
before the successful normalization span ends, and reuses that prepared
simulation for the calculation. Pre-acceptance validation must not emit a run
stage span that cannot carry the selected identifier. A successful cache hit
binds the identifier after the cache returns. A request that fails situation
parsing must never call `start_observability_id`.

For a new economy report, acquire submission ownership before calling
`start_observability_id`. Persist the selected identifier in the report state
written after submission. A request that reads existing report state calls
`restore_observability_id`; a persisted value is authoritative even when the
polling request supplies a different header. Older records with a null value
remain null. Never create a replacement identifier while polling.

The HTTP response contains the header only when the request started a
calculation, continued one synchronously, or restored an existing report
identifier.

## Simulation client transport

The simulation HTTP client reads identifiers from request context. Its request
hook sends `request_id` and any bound `observability_id` in their respective
headers. API v1 never replaces its selected identifier with a value from an
HTTP response.

Do not add `observability_id` to a simulation JSON body, `_telemetry`, or
execution result data class. The simulation API carries it through HTTP headers,
persists it beside functional job state, and transports captured trace context
to Modal as a separate function argument.

## Runtime stages

All API v1 span names for supported calculation configurations are defined in
`policyengine_api.observability.stages`. Runtime code imports the applicable
`StagePlan` and calls `plan.name(Stage.VALUE)`. Do not add span name string
literals in route or service code.

When adding a calculation configuration or stage:

1. Add it to `RunConfiguration` or `Stage`.
2. Add it to the applicable plan in `RUN_STAGE_REGISTRY`.
3. Import that plan in runtime code.
4. Add focused tests for the stage and identifier lifecycle.

## Metric resource identity

`service.instance.id` identifies one telemetry-producing process. Cloud Run
revision names identify deployed code and are shared by multiple containers and
Gunicorn workers, so they must not be used alone as the instance identifier.
Construct the value with `policyengine_observability.process_instance_id` after
the worker process starts.

The central collector adds the configured Google Monitoring `location` only to
metrics. Logs and traces retain the workload's actual `cloud.region`. Deploy
collector configuration changes with the `Deploy observability collector`
workflow; committing `gcp/observability/collector/config.yaml` alone does not
change the live Cloud Run service.

## Trace boundaries

HTTP instrumentation carries W3C trace context across synchronous calls. The
simulation API carries that trace context through asynchronous Modal dispatch.
The submission and worker work can therefore form one distributed trace.
Native ASGI instrumentation must start request spans with the matched route
template. Never use the unresolved request path as a span name.

A later polling request starts a new trace. Its logs and spans share the
persisted `observability_id` with the submission trace. Measure a complete
report by querying all diagnostic records with that identifier, then use the
registered stage names to break down elapsed time.

When an economy report selects or restores its identifier inside a nested
stage, reapply the identifier after that stage exits so each containing economy
span receives it. HTTP completion handling must reapply a bound identifier
before ending the server request span. Keep these calls behind local exception
boundaries so a runtime failure cannot change the response.

Stage 12 authoritative and comparison executions use the same
`observability_id` as the report that dispatched them. Their `evaluation_id`
and simulation execution identifiers remain separate functional identifiers.

## Failure behavior

Invalid observability configuration must fail during build or deployment
validation. After a service starts serving application traffic, logging,
tracing, metrics, context binding, and export failures must not alter an
application result or HTTP status.

Normalize all identifiers received from callers or downstream services. Keep a
local exception boundary around runtime context binding because observability
package failures must not escape into request processing.

Focused tests must cover:

- identifier creation at calculation submission boundaries;
- HTTP propagation to the simulation API;
- persistence and restoration during polling;
- persisted values taking precedence over polling headers;
- older records with null identifiers;
- observability failures leaving application results unchanged.
