# API v1 observability operating policy

## Scope

The machine-readable workload inventory is
[`gcp/observability/workload-inventory.template.yaml`](../../gcp/observability/workload-inventory.template.yaml).
Only the listed `policyengine-api`, simulation entry, simulation gateway, and
versioned simulation executor workloads participate.

Cloud Run candidate, canary, and tagged revisions use the identity of their
containing service and are included. Modal smoke, precompute, and ephemeral
applications are excluded. `policyengine-household-api` and
`policyengine-uk-chat` remain unchanged and receive no migration or
service-specific validation in this work.

The inventory is the configuration source for log sink filters, collector
invocation permissions, and the Modal Workload Identity Federation condition.
Telemetry attributes such as `service.namespace` do not grant access.

## Storage decision

Production and nonproduction application logs use the existing
`policyengine-observability` bucket in the `policyengine-observability` Google
Cloud project. The bucket is global, analytics enabled, and retains records for
30 days. `deployment.environment.name` distinguishes production and staging.

A single bucket is appropriate for the initial rollout because the same small
operator group requires both environments, the current bucket already exists,
and a shared analytics surface simplifies request investigations. Access is
controlled at the bucket and project level rather than by environment. This
decision must be revisited before an environment requires different readers,
retention, residency, or deletion policy.

Cloud Run writes structured JSON to standard output. Exact-service sinks in
the source projects route selected records into this bucket. Modal writes the
same records to standard output and uses the package's bounded asynchronous
Cloud Logging destination under the `policyengine-api-v1-modal` log ID. A
central exclusion prevents a directly ingested record from also being retained
in `_Default`.

Traces and metrics use Cloud Trace and Cloud Monitoring in the same project.
They are correlated with logs by resource identity, trace ID, request ID, and
job ID; they are not stored in the log bucket.

## Initial trace sampling

The initial rollout uses these head-sampling settings:

| Environment | Services | Parent-based ratio |
| --- | --- | ---: |
| Production | API v1, simulation entry, gateway, executors | 1.0 |
| Staging | API v1, simulation entry, gateway, executors | 1.0 |
| Local development | All | No remote exporter |

Sampling every initial production trace provides a complete baseline for
volume, cost, errors, and slow operations. After at least one representative
week, operators may lower the normal-request ratio only after recording a cost
and coverage review. A lower head-sampling ratio cannot retroactively retain a
request after its outcome or duration becomes known. Retaining all errors or
slow requests with a lower normal ratio therefore requires a reviewed,
bounded collector tail-sampling policy.

The checked-in collector configuration implements error and 30-second latency
policies and initially retains 100% of all remaining traces. Any later
reduction applies to the collector's general tail policy while SDK head
sampling remains at 100%, allowing the collector to evaluate completed traces.

Parent sampling decisions are preserved. Society-wide simulation dispatches
must not override a sampled parent with an unsampled child.

## Asynchronous trace relationships

Captured dispatch context contains its UTC capture time. A worker uses the
dispatch span as its parent only when all of these conditions hold:

- The work is a direct continuation of one dispatch.
- The worker starts no more than five minutes after capture.
- The invocation is not an independent retry.
- The invocation does not aggregate multiple dispatches.

Otherwise the worker starts a new trace and links the dispatch span. Request
and job identifiers remain the same in either representation. Malformed or
expired remote context is ignored without rejecting the job.

## Data policy

### Required log fields

- `schema_version`
- `timestamp`
- `severity`
- `message` or `event.name`
- `service.name`, `service.namespace`, `service.version`, `service.role`
- `deployment.environment.name` and `cloud.platform`
- Request, operation, trace, span, duration, outcome, and bounded error fields
  when applicable

Application attributes are stored below `attributes`. The initial allowlist is
limited to bounded operational values such as country, model version, backend,
requested version, resolved channel, authentication outcome, job type, and
simulation year. Attribute strings are truncated at 1,024 characters and one
record contains at most 32 application attributes.

### Trace attributes

Traces may contain the standard service resource fields, HTTP route templates,
HTTP methods, status codes, operation names, bounded deployment identifiers,
request IDs, job IDs, and explicitly approved operational attributes. Raw URLs,
query values, request bodies, response bodies, and arbitrary baggage are not
recorded.

### Metric labels

Metrics use only these bounded labels:

- `service.name`
- `service.role`
- `deployment.environment.name`
- `cloud.platform`
- `http.route`
- `http.request.method`
- `http.response.status_code_class`
- `operation.name`
- `operation.kind`
- `outcome`

Request IDs, trace IDs, job IDs, simulation IDs, raw paths, error messages,
user-provided values, unrestricted geography values, and unrestricted version
values are prohibited metric labels.

### Prohibited telemetry data

Logs, traces, metrics, and dispatch context must not contain:

- Authorization headers, cookies, credentials, tokens, or secret values
- Request or response bodies
- Household situations, entity records, or person-level values
- Reform definitions or parameter payloads
- Raw IP addresses
- Prompts, model inputs, or model responses
- Exception local variables
- Function arguments or return values captured automatically

Exception messages and stacks are truncated and passed through configured
secret-value redaction before remote delivery.

## Operational limits

Remote application delivery is best effort. Every application queue, exporter,
retry, network request, flush, and shutdown action has a finite bound. Queue
overflow drops the new record and increments a local counter. Internal
diagnostics are rate limited and written directly to standard error so they do
not recurse through a failing exporter.
