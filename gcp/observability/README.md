# Google Cloud observability runtime

This directory contains the source used to build the API v1 OpenTelemetry
Collector:

| File | Purpose |
| --- | --- |
| `collector/config.yaml` | OTLP gRPC receiver, bounded processing, trace sampling, and Google Telemetry API export configuration |
| `collector/Dockerfile` | Collector container image built with that configuration |

The Google Cloud IAM, logging sinks, dashboard, and alert policies were
provisioned separately. This repository owns the collector image,
configuration, and deployment workflow.

## Collector behavior

The collector accepts OTLP traces and metrics over gRPC. It has no application
log pipeline. Cloud Run services write structured JSON to standard output, and
authorized Modal applications use the observability package's bounded Cloud
Logging destination.

The collector applies a memory limit, batches exports, and sends signals to
`telemetry.googleapis.com` using its Google service account. Its trace policy
retains errors, operations lasting at least 30 seconds, and currently 100% of
all remaining traces. Participating SDKs therefore use 100% head sampling so
the collector can evaluate complete traces.

The metrics pipeline assigns `location` from
`OBSERVABILITY_METRIC_LOCATION`. This is the Google Monitoring resource
location for centrally collected metrics; workload execution regions remain
available on logs and traces.

Run the `Deploy observability collector` workflow from `master` after changing
the collector image or configuration. It validates the configuration, builds
an image tagged with the source commit, updates the authenticated
`policyengine-api-v1-otel-collector` Cloud Run service, waits for its health
probes, sends authenticated trace and metric data, and reads both records back
from Cloud Trace and Cloud Monitoring. It also sends a log record and confirms
that the OTLP logs RPC rejects it. The deployment restores the Cloud Run
invoker IAM check, removes public invoker bindings, and verifies the resulting
access policy before reporting success.

The production GitHub environment supplies:

- `OBSERVABILITY_PROJECT_ID`
- `OBSERVABILITY_COLLECTOR_REGION`
- `OBSERVABILITY_COLLECTOR_SERVICE`
- `OBSERVABILITY_COLLECTOR_ARTIFACT_REPOSITORY`
- `OBSERVABILITY_COLLECTOR_IMAGE_NAME`
- `OBSERVABILITY_COLLECTOR_SERVICE_ACCOUNT`
- `OBSERVABILITY_METRIC_LOCATION`

The GitHub deployment service account has the custom
`collectorDeploymentIam` role on only the collector service. That role contains
`run.services.getIamPolicy` and `run.services.setIamPolicy`, which let the
workflow remove public invoker bindings. The project-level custom
`collectorDeploymentVerifier` role contains only `cloudtrace.traces.get`,
`monitoring.timeSeries.list`, and `resourcemanager.projects.get`, which let the
workflow read back its uniquely identified verification data.

## Participating workloads

The live GCP permissions and routing configuration cover only:

- `policyengine-api` and `policyengine-api-staging` in the API project.
- `policyengine-simulation-entry` and
  `policyengine-simulation-entry-staging` in the simulation entry project.
- The `policyengine-simulation-gateway` Modal application.
- Versioned Modal applications matching
  `policyengine-simulation-py<major>-<minor>-<patch>` or
  `policyengine-simulation-v2-py<major>-<minor>-<patch>`.

Modal smoke, precompute, ephemeral, Household API, and UK Chat applications are
excluded.

## Consumer configuration

The API and simulation repositories configure these GitHub Actions variables:

- `OBSERVABILITY_SERVICE_NAMESPACE`
- `OBSERVABILITY_TRACE_PROJECT_ID`
- `OBSERVABILITY_OTLP_ENDPOINT`
- `OBSERVABILITY_OTLP_GOOGLE_AUDIENCE`

The simulation repository additionally configures:

- `OBSERVABILITY_LOGGING_PROJECT_ID`
- `OBSERVABILITY_LOG_NAME`
- `OBSERVABILITY_GOOGLE_WORKLOAD_IDENTITY_PROVIDER`
- `OBSERVABILITY_GOOGLE_SERVICE_ACCOUNT_EMAIL`

API Cloud Run services use source-project logging sinks and therefore require
no direct Cloud Logging credentials.

## Live infrastructure record

The infrastructure was applied and verified on 2026-09-22:

- The global central log bucket in `policyengine-observability` has log
  analytics enabled and 30-day retention.
- Exact Cloud Run service filters route the two API services and two simulation
  entry services to the central bucket.
- Modal application logs use the `policyengine-api-v1-modal` log ID, and an
  exclusion prevents duplicate retention in `_Default`.
- The authenticated `policyengine-api-v1-otel-collector` service runs in
  `us-central1`.
- The collector uses the `policyengine-otel-collector` service account.
- A dedicated `modal-api-v1` Workload Identity Federation provider restricts
  access by workspace, environment, and application name.
- The only project-level `roles/logging.logWriter` identity is the API v1 Modal
  service account.
- The Cloud Monitoring dashboard and six alert policies are enabled.
- The alert policies have no notification channels, so they record incidents
  without sending email, Slack, or paging notifications.

The consumer services require `policyengine-observability` 3.0.3. Record the
deployed consumer revisions and a representative cost and volume observation
interval after the API v1 rollout.

## Metric delivery verification

After deploying the collector and both consumers, query the collector's Cloud
Run logs from the deployment timestamp forward. A successful rollout has no
new metric export errors containing `InvalidArgument`, `out-of-order`,
`Duplicate TimeSeries`, `frequency`, or a missing `location`. Then run one API
v1 society report and confirm that Cloud Monitoring receives new
`policyengine.*` metric points from the API, simulation entry service, Modal
gateway, coordinator, and both Stage 12 simulation workers.

Compare the deployed interval with the recorded pre-fix baseline: 46 collector
metric export errors comprising 863 rejected points. Trace export had no
corresponding rejected points in that interval.

## Daily telemetry error issues

The `Telemetry error issues` workflow
(`.github/workflows/telemetry-error-issues.yml`) runs at 00:45 US Eastern each
day. It reports the previous Eastern calendar day, from midnight to midnight,
which lasts 23 or 25 hours on the days the clocks change. It runs
`.github/scripts/sync_telemetry_error_issues.py`, a short entry point that calls
the `telemetry_error_issues` package beside it in `.github/scripts/`. The package's
`cli` module reads the arguments and settings and runs each step; `bigquery`
runs the queries, `records` and `groups` choose, fingerprint and measure the
failures, `rendering` writes the issue text, and `sync` updates the issues
through `github_client`. Each run:

1. Queries the central bucket through its linked BigQuery dataset
   `observability_logs`. It reads the `_AllLogs` view for ERROR records with
   the `policyengine.api-v1` service namespace in the report day and the seven
   days before it, excluding the health-check routes. It also counts
   `request.completed` records per route in the report day, for error rates.
   Each query is limited to 5 GiB billed.
2. Chooses one record per failed request and service: the exception record,
   else the error message, else the failed `request.completed` record. Records
   that tie, such as two exceptions logged at the same moment, are ordered by
   their own values, so the same records give the same report whatever order
   the query returns them in.
3. Groups failures by a 16-character HMAC-SHA256 fingerprint of the
   fingerprint algorithm number, the service family and either the exception
   type and innermost application stack frames, the route and message
   template, or the route and HTTP status. The frames are the three innermost
   whose file paths are in application packages (or, when there are none,
   the three innermost of any kind), and each is identified by its function
   name alone, without leading underscores and without its module path or
   line number. Moving a function to another module, or renaming a private
   helper `_name` to `name`, keeps the fingerprint; any other rename changes
   it. Frames come from the first traceback of the stack, which for a
   chained exception is its first cause. The logging library keeps only the
   first 16,384 characters of a stack, so a long cause can drop the final
   traceback, but the first one is always kept.
4. Creates or updates one issue per group in this repository, labelled
   `telemetry-error` and `service: <service family>`. A group opens an issue
   only after 3 production failures in at least 2 requests in one day, and at
   most 5 issues open per run. Staging counts appear in each issue but never
   open one. An issue closed as completed reopens, with the `regression`
   label, when production failures that start 24 hours after it closed meet
   the same thresholds.

An issue's "Error rate on affected routes" compares the group's failed
requests with the `request.completed` records counted on the same route
templates. Failures with no route, or with a placeholder route such as
`<unmatched>` (which a service logs for a request that matched none of its
routes), count in neither. When some requests were logged as completed but
more failed, the rate shows n/a with both counts instead of a percentage;
when none were logged as completed, it shows n/a.

This repository is public, so issues, workflow logs and job summaries hold
only fingerprints, counts, service names, exception class names, route
templates and a Logs Explorer link. Error messages, stack text and
identifiers stay in BigQuery: the queries return stacks only as file and
function names, messages only as their first three words, and identifiers
only as hashes. A failed run prints only the failed stage, the exception class
and the HTTP status.

### Running it by hand

Dispatch the workflow from `master`. `dry_run` defaults to `true`: the job
queries and groups errors and writes the actions it would take to the job
summary, without changing any issue. `report_date` (`YYYY-MM-DD`) reports a
different Eastern day, such as one a scheduled run missed.

To run it locally with your own credentials, use a throwaway fingerprint key.
Its fingerprints won't match existing issues.

```bash
GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)" \
GITHUB_TOKEN="$(gh auth token)" \
GITHUB_REPOSITORY=PolicyEngine/policyengine-api \
TELEMETRY_ERROR_FINGERPRINT_KEY="$(openssl rand -hex 32)" \
OBSERVABILITY_LOG_BUCKET=policyengine-observability \
OBSERVABILITY_LOG_BUCKET_LOCATION=global \
OBSERVABILITY_LOG_DATASET=observability_logs \
OBSERVABILITY_LOG_VIEW=_AllLogs \
OBSERVABILITY_SERVICE_NAMESPACE=policyengine.api-v1 \
uv run --frozen --only-group telemetry-error-issues \
  python .github/scripts/sync_telemetry_error_issues.py \
  --project-id policyengine-observability --dry-run
```

The workflow runs the script the same way, through
`.github/scripts/sync_telemetry_error_issues.sh`: in an environment holding
only the `telemetry-error-issues` dependency group from `pyproject.toml`,
which is `google-cloud-bigquery` at the version `uv.lock` pins. The queries
read rows by iterating each job's result over the BigQuery REST API, never
through the Storage Read API, which the service account has no role for.

### Required infrastructure

| Resource | Purpose |
| --- | --- |
| Linked BigQuery dataset `observability_logs` on the `policyengine-observability` bucket | SQL access to the bucket's log views |
| Service account `telemetry-error-issues@policyengine-observability.iam.gserviceaccount.com` | The identity the workflow queries BigQuery as |
| `roles/bigquery.jobUser` on the project, and `roles/bigquery.dataViewer` on the linked dataset | Run query jobs and read the log views |
| `roles/iam.workloadIdentityUser` on the service account for `principal://iam.googleapis.com/projects/389282473430/locations/global/workloadIdentityPools/github/subject/repo:PolicyEngine/policyengine-api:environment:telemetry-error-issues` | Lets only jobs in the `telemetry-error-issues` GitHub environment act as the service account |
| GitHub environment `telemetry-error-issues`, with deployments limited to `master` | Keeps other branches from acting as the service account |
| Environment variable `TELEMETRY_ERROR_ISSUES_SERVICE_ACCOUNT` | The service account's email address |
| Environment secret `TELEMETRY_ERROR_FINGERPRINT_KEY` | The 32-byte hexadecimal HMAC key for fingerprints |

The workflow also uses the repository secret `GCP_WORKLOAD_IDENTITY_PROVIDER`
and these repository variables, which say where the logs are:

| Repository variable | Value | Used for |
| --- | --- | --- |
| `OBSERVABILITY_PROJECT_ID` | `policyengine-observability` | The project that runs the query jobs and holds the bucket |
| `OBSERVABILITY_LOG_BUCKET` | `policyengine-observability` | The log bucket, in the Logs Explorer link |
| `OBSERVABILITY_LOG_BUCKET_LOCATION` | `global` | The bucket's location, in the Logs Explorer link |
| `OBSERVABILITY_LOG_DATASET` | `observability_logs` | The linked BigQuery dataset the queries read |
| `OBSERVABILITY_LOG_VIEW` | `_AllLogs` | The log view, which is also the name of the linked dataset's view |
| `OBSERVABILITY_SERVICE_NAMESPACE` | `policyengine.api-v1` | The `service.namespace` of the records to report; the API reads the same variable |

Each name must match a strict identifier pattern
(`.github/scripts/telemetry_error_issues/log_source.py`), because BigQuery
can't take a dataset or view name as a query parameter; the run refuses any
other value. The namespace is sent as a query parameter. The rules that decide
which group a failure belongs to stay in code, because changing one changes
fingerprints.

These resources were created on 2026-10-20:

- The linked dataset is in the BigQuery `US` location and holds one view,
  `_AllLogs`.
- `roles/bigquery.dataViewer` was granted on the dataset alone with
  `GRANT ... ON SCHEMA`; `bq update --source` would replace the dataset's
  access list. The service account needs no Cloud Logging role.
- A dry run as the service account, for 2026-10-19, read 1,648 ERROR records
  across eight days and found 15 error groups, 5 of them above the issue
  thresholds. The queries scanned about 0.18 GiB of error records and
  0.02 GiB of request counts, so a daily run stays well inside BigQuery's free
  monthly allowance.

Never rotate `TELEMETRY_ERROR_FINGERPRINT_KEY` on its own. Every fingerprint
would change, so the next run would open a second issue for each group that
already has one. A key change needs a plan for moving the existing issues to
their new fingerprints, as does any change to `FINGERPRINT_ALGORITHM` in the
script.

Fingerprint algorithm 2 replaced algorithm 1, which identified each stack
frame by its module path and function name, so that moving code between
modules no longer opens a duplicate issue. Because the algorithm number is
part of every fingerprint, message and failed-request groups got new
fingerprints too, although their inputs didn't change. Issues opened under
algorithm 1 were not carried over: the job no longer matches them, so it
neither updates nor reopens them, and a group that still fails opens a new
issue once it meets the thresholds. An algorithm 1 issue can be closed by
hand, or carried over by replacing the fingerprint at the end of its title
with the group's new one; the job then matches it by its title and rewrites
its marked section.

### Known gap: Cloud Run platform failures

The source sinks forward only records in the application log format
(`schema_version = policyengine.observability.v2`). Cloud Run request logs
are not forwarded, so requests that time out, run out of memory or crash the
container before the application logs anything never reach these reports.

## Rollback

1. Remove the OTel endpoint from participating service configuration.
2. Remove Modal remote logging configuration.
3. Revert participating services to their previous package versions and
   deployment revisions.
4. Remove the API v1 source sinks and restore the previous central direct-log
   sink and `_Default` exclusion configuration.
5. Remove collector invocation permissions, disable the `modal-api-v1`
   provider, and disable or delete the collector service.
6. Retain the central bucket for its configured retention period unless stored
   data caused the incident.

Rollback does not modify the existing `modal/modal` provider or excluded
applications.
