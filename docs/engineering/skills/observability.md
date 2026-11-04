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

The client's transport (`policyengine_api/libs/simulation_entrypoint_transport.py`)
sends a GET once more, on a new connection, after `httpx.ReadError`,
`httpx.WriteError` or `httpx.RemoteProtocolError`. It never retries a POST,
which may already have submitted a job, a timeout or an HTTP error status. The
retry's connect, read, write and pool timeouts are each at most 10 seconds
(`RETRY_TIMEOUT_SECONDS`), or the request's own if lower, and a retry that
times out is not retried again.

A GET that gets no response, after that retry where it applies, raises
`SimulationEntrypointConnectionError`, which the economy routes answer with
502. There are two exceptions:

- For a finished stored impact, the annual economy route asks which worker app
  the request resolves to, to check whether the impact is out of date
  (`_should_refresh_cached_impact` in `services/economy_stored_impacts.py`).
  If that request gets no response, the route answers from the stored impact
  as it is.
- `health_check` (`GET /health` on the simulation service) returns False, and
  `/simulation-gateway-check` answers 503.

Because the client is given its transport, httpx doesn't read the
`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` or `NO_PROXY` environment variables
for it: httpx builds proxy transports from them only when it builds its own
transport. None of them is set where the API runs. Setting one has no effect
on this client.

Each request the client sends, a retry included, is one
`simulation_entrypoint.request` event through the observability runtime
(`policyengine_api/libs/simulation_request_diagnostics.py`):

- `connection.new` says whether the attempt tried to open a new connection. It
  is true for a connection that was refused, which has no file descriptor.
- A connection that opened records its age, file descriptor, local port and
  request number. A reused one also records its idle time, which runs from
  the end of the last response read on it (httpcore's
  `http11.receive_response_body.complete` trace event, before the connection
  goes back to the pool).
- httpcore's trace events give when each step happened (`timing.<step>_ms`).
- A failed attempt records the type, errno and errno name of the `OSError` in
  the exception chain, the time from sending the request to the failure, and
  whether a retry follows. It never records the error's message, which can
  quote a response header.
- When a read, a write or a TLS handshake on the connection fails, or a read
  returns no data because the server closed the connection, the attempt also
  records the socket's file descriptor, local port and readiness at that
  moment (`failure.socket_*`). It never reads the socket's pending error
  (`SO_ERROR`): reading it clears it, and on a reassigned file descriptor it
  would clear another socket's error. A failed TLS handshake closes the
  socket, so the connection's file descriptor and local port from when it
  connected are recorded instead.

The v1 Cloud SQL pool (`policyengine_api/data/orm_pool_events.py`) records:

- `database_pool.connect`, `database_pool.invalidate`,
  `database_pool.soft_invalidate`, `database_pool.close` and
  `database_pool.close_detached`, each with the database socket's file
  descriptor and local port. The connect listener saves them in the pool
  entry's `info`, because pymysql drops its socket before it raises the error
  that invalidates a connection.
- `database_pool.error` for each database error, with whether it came from
  the checkout ping (`pool_pre_ping`) and was a disconnect, the error's type,
  the driver's error code and the `OSError` in its chain, never its message. A
  failed ping invalidates the connection with a bare `InvalidatePoolError`, so
  only this record has the ping's cause.

The pool also sends every message from the Cloud SQL connector's lazy refresh
module to the logs at INFO: a certificate refresh starting, completing or
failing, the new certificate's expiry, and, for each new database connection,
that the cached certificate is still valid.

A file descriptor number is free for reuse as soon as its socket closes. A
database connection that opens with the number of an HTTP connection that is
still open, with no close recorded for that number in between, would show that
the HTTP connection's socket was closed underneath it. A failed attempt whose
`failure.socket_local_port` differs from its `connection.local_port` had its
file descriptor reassigned to another socket.

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
