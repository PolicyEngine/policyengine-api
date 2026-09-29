# Google Cloud observability runtime

This directory contains the source used to build the API v1 OpenTelemetry
Collector:

| File | Purpose |
| --- | --- |
| `collector/config.yaml` | OTLP gRPC receiver, bounded processing, trace sampling, and Google Telemetry API export configuration |
| `collector/Dockerfile` | Collector container image built with that configuration |

The Google Cloud IAM, logging sinks, collector service, dashboard, and alert
policies were provisioned separately. This repository does not manage or apply
those resources.

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

Changing `collector/config.yaml` does not update the live service. The image
must be rebuilt and the existing `policyengine-api-v1-otel-collector` Cloud Run
service must be updated through a separately managed deployment process. No
collector deployment workflow exists in this repository.

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

The consumer services require `policyengine-observability` 3.0.1. Record the
deployed consumer revisions and a representative cost and volume observation
interval after the API v1 rollout.

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
