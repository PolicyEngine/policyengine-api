# Google Cloud deployment plan

This directory defines the centralized API v1 observability resources in the
project selected by `OBSERVABILITY_PROJECT_ID`. The workload boundary is
defined in
[`workload-inventory.template.yaml`](workload-inventory.template.yaml).
Applications absent from that inventory receive no credentials or destination
permissions.

These files are a reviewable deployment plan. Applying them changes live IAM,
Cloud Logging routing, Cloud Run, and monitoring resources and therefore
requires an operator-approved deployment window.

## Resources

| File | Resource |
| --- | --- |
| `collector/config.yaml` | OTLP gRPC receiver, bounded processors, and Google Telemetry API exporter for traces and metrics |
| `collector/Dockerfile` | Google-built OTel Collector 0.160.0 plus the reviewed configuration |
| `collector/service.template.yaml` | Authenticated Cloud Run collector with fixed CPU, memory, concurrency, health checks, and scaling bounds |
| `log-routing.template.yaml` | Exact Cloud Run source sinks, restricted Modal direct-log sink, and `_Default` duplicate exclusion |
| `iam.template.yaml` | Collector and Modal service accounts, Cloud Run invokers, and a dedicated Modal API v1 identity provider |
| `dashboard.template.json` | Initial request, latency, error, dropped-item, and exporter-failure dashboard |
| `alerts.template.yaml` | Initial alert policy inputs |
| `render_deployment.py` | Validates deployment variables and writes private rendered files under `rendered/` |
| `verify.sh` | Read-only resource and routing checks after deployment |

The collector accepts traces and metrics. Application logs do not enter the
collector. Cloud Run JSON output uses source-project sinks, while authorized
Modal processes use the package's bounded Cloud Logging writer.

The initial collector tail policy retains 100% of traces. Separate error and
30-second latency policies are evaluated before the general policy. If the
general percentage is reduced after the volume review, those two policies keep
error and slow traces. SDK head sampling must remain at 100% for the collector
to receive spans needed for this decision.

## Deployment order

### 1. Configure and render deployment values

Configure these GitHub Actions repository variables:

- `OBSERVABILITY_PROJECT_ID`
- `OBSERVABILITY_PROJECT_NUMBER`
- `API_PROJECT_ID`
- `SIMULATION_ENTRY_PROJECT_ID`

Configure `MODAL_WORKSPACE_ID` as a GitHub Actions repository secret. It is
private deployment metadata and must not be printed by workflows.

Workflows that render or apply the deployment must map the values explicitly:

```yaml
env:
  OBSERVABILITY_PROJECT_ID: ${{ vars.OBSERVABILITY_PROJECT_ID }}
  OBSERVABILITY_PROJECT_NUMBER: ${{ vars.OBSERVABILITY_PROJECT_NUMBER }}
  API_PROJECT_ID: ${{ vars.API_PROJECT_ID }}
  SIMULATION_ENTRY_PROJECT_ID: ${{ vars.SIMULATION_ENTRY_PROJECT_ID }}
  MODAL_WORKSPACE_ID: ${{ secrets.MODAL_WORKSPACE_ID }}
```

The API and simulation repositories own their runtime destination settings.
Configure these GitHub Actions variables in both repositories:

- `OBSERVABILITY_SERVICE_NAMESPACE`
- `OBSERVABILITY_TRACE_PROJECT_ID`
- `OBSERVABILITY_OTLP_ENDPOINT`
- `OBSERVABILITY_OTLP_GOOGLE_AUDIENCE`

The simulation repository also configures direct Modal log delivery and its
Google identity with:

- `OBSERVABILITY_LOGGING_PROJECT_ID`
- `OBSERVABILITY_LOG_NAME`
- `OBSERVABILITY_GOOGLE_WORKLOAD_IDENTITY_PROVIDER`
- `OBSERVABILITY_GOOGLE_SERVICE_ACCOUNT_EMAIL`

The API Cloud Run service writes logs to standard output, so its source-project
sink selects the central log destination. It does not need direct Cloud
Logging credentials.

For an operator-run deployment, set the same five values in the local process
without writing them to a tracked file, then render the templates:

```bash
.venv/bin/python gcp/observability/render_deployment.py
```

The renderer validates every value, reports only variable names, and writes
files with owner-only permissions under the ignored `gcp/observability/rendered/`
directory.

### 2. Enable services

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iamcredentials.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  run.googleapis.com \
  sts.googleapis.com \
  telemetry.googleapis.com \
  tracing.googleapis.com \
  --project="${OBSERVABILITY_PROJECT_ID}"
```

### 3. Create identities

Create these service accounts in the central project:

```text
policyengine-otel-collector@${OBSERVABILITY_PROJECT_ID}.iam.gserviceaccount.com
policyengine-api-v1-modal@${OBSERVABILITY_PROJECT_ID}.iam.gserviceaccount.com
```

Grant only the roles listed in the rendered `iam.yaml`. The collector receives
`roles/telemetry.writer` and `roles/serviceusage.serviceUsageConsumer`. The
Modal identity receives `roles/logging.logWriter` and collector invocation
permission. The four existing Cloud Run identities in the inventory receive
collector invocation permission on the collector service only.

Remove project-level `roles/logging.logWriter` bindings from every identity
outside this inventory. Source-project logging service agents use conditional
`roles/logging.bucketWriter` access to the named analytics bucket and do not
receive project-level log write access. `verify.sh` fails when another
project-level log writer is present.

Create a separate `modal-api-v1` workload identity pool and provider using the
issuer, audience, mappings, workspace, environment, and application condition
in the rendered `iam.yaml`. Do not modify the existing `modal/modal` provider
during this deployment; it belongs to applications excluded from this change.
Grant the new provider permission to impersonate only the API v1 Modal service
account.

Before enabling the provider, decode one production and one staging Modal
identity token locally and confirm that `workspace_id`, `environment_name`,
and `app_name` exactly match the reviewed condition.

### 4. Build and deploy the collector

```bash
gcloud artifacts repositories create observability \
  --repository-format=docker \
  --location=us-central1 \
  --immutable-tags \
  --project="${OBSERVABILITY_PROJECT_ID}"

gcloud builds submit gcp/observability/collector \
  --tag="us-central1-docker.pkg.dev/${OBSERVABILITY_PROJECT_ID}/observability/otel-collector:0.160.0-api-v1-1" \
  --project="${OBSERVABILITY_PROJECT_ID}"

gcloud run services replace gcp/observability/rendered/collector/service.yaml \
  --region=us-central1 \
  --project="${OBSERVABILITY_PROJECT_ID}"
```

Apply `roles/run.invoker` bindings for the five identities listed in the
rendered `iam.yaml`. Do not grant unauthenticated invocation. Record the HTTPS
service URL as both `OTEL_EXPORTER_OTLP_ENDPOINT` and
`POLICYENGINE_OTEL_GOOGLE_AUDIENCE` in participating service configuration.

### 5. Configure log routing

Create one aggregated sink in each source project using the exact service and
schema filters in the rendered `log-routing.yaml`. Grant each generated sink
writer identity `roles/logging.bucketWriter` on the central log bucket.

Update `policyengine-observability-app-logs` to the listed direct-log filter.
Add the listed exclusion to `_Default`; this prevents a direct Modal log from
being stored in both `_Default` and the analytics bucket. Preserve the existing
Cloud Audit Log exclusions.

After routing one synthetic record per participating service, confirm each
`insertId` exists exactly once in the central project.

### 6. Create dashboard and alerts

```bash
gcloud monitoring dashboards create \
  --config-from-file=gcp/observability/rendered/dashboard.json \
  --project="${OBSERVABILITY_PROJECT_ID}"
```

Create the API-ready alert policies with:

```bash
.venv/bin/python gcp/observability/create_alerts.py
```

The script is idempotent by policy display name. It leaves notification-channel
configuration empty when the project has no channel; add operator-owned channel
identifiers after creating the relevant email, Slack, or paging destination.

### 7. Verify before consumer deployment

```bash
bash gcp/observability/verify.sh
```

Then use an approved workload identity to send one trace and metric. Attempt
the same request with a synthetic Modal token whose application name is not in
the inventory; token exchange or collector invocation must return permission
denial. Do not invoke an excluded application to perform this check.

For an operator-run Cloud Run identity check, temporarily grant the operator
`roles/iam.serviceAccountTokenCreator` on one inventoried runtime identity, run:

```bash
.venv/bin/python gcp/observability/verify_otel.py \
  --endpoint="${POLICYENGINE_OTEL_GOOGLE_AUDIENCE}" \
  --service-account="sim-entry-beta-runtime@${SIMULATION_ENTRY_PROJECT_ID}.iam.gserviceaccount.com"
```

Remove the temporary operator binding immediately after the check. The script
requires an authenticated `gcloud` session, sends one trace and metric, verifies
both Google Cloud stores, and confirms that the collector rejects OTLP logs.

Use [`verify_modal_wif.py`](verify_modal_wif.py) with the Modal CLI to run an
allowed app name and a synthetic denied app name. The remote function exchanges
its automatically injected Modal OIDC token, verifies service-account access,
invokes the collector, and writes one routing record without exposing any
token. Run an allowed app name from a temporary non-allowlisted environment to
verify the environment restriction, then delete that environment.

## Rollback

1. Remove the OTel endpoint from participating service configuration. Local
   structured logging continues and no remote OTel exporter is created.
2. Remove Modal remote logging configuration. Modal JSON output continues.
3. Revert each participating service to its previous package version and
   deployment revision.
4. Remove the new source sinks and restore the prior central direct-log sink
   filter and `_Default` exclusion state.
5. Remove invoker bindings, disable the `modal-api-v1` provider, and disable or
   delete the collector service.
6. Keep the central bucket during the retention period unless the stored data
   itself caused the incident.

Rollback does not modify the existing `modal/modal` provider or any excluded
application deployment.

## Deployment record

The infrastructure portion of this runbook was applied and verified on
2026-09-22:

- the global central log bucket retains records for 30
  days and has log analytics enabled;
- exact source-project sinks route the two API services and the two simulation
  entry services to that bucket;
- the authenticated collector runs in `us-central1` as
  `policyengine-api-v1-otel-collector`;
- the dedicated `modal-api-v1` identity provider is active with the workspace,
  environment, and application conditions in the rendered `iam.yaml`;
- the only project-level `roles/logging.logWriter` identity is the API v1
  Modal service account;
- the dashboard and six alert policies are present and enabled; and
- the project currently has no alert notification channel, so the policies
  record incidents without sending email, Slack, or paging notifications.

The package and consumer service rollout remains pending until the three draft
pull requests are reviewed, the package is published as version 2.0, and the
temporary Git source pins in both consumer repositories are replaced with the
published version. Run the synthetic cross-service request, volume and cost
measurement, and destination comparison after those deployments. Record the
deployed revisions and the observation interval here before declaring the
consumer rollout complete.
