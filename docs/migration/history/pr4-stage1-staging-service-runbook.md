# PR 4 Stage 1 Runbook: Staging Service Split + Startup De-flake

> Per-stage record. Current behavior:
> see [`../cloud-run-operations.md`](../cloud-run-operations.md).

Stage 1 of the public host cutover splits staging Cloud Run deploys onto a dedicated
`policyengine-api-staging` service. Previously, both the staging and production CI tracks
targeted the single `policyengine-api` service, and the staging promote step put a
staging-configured revision on 100% of the production service URL during every push. That
is harmless while nothing public routes to the service URL, and unacceptable once a load
balancer fronts it.

Stage 1 also de-flakes candidate startup (plan items 3–5): `--cpu-boost` on candidate
deploys, a gunicorn entrypoint that binds the port before the multi-minute app import
(Cloud Run hard-caps startup-probe time at 240s, which the import raced and lost on
roughly half of first attempts), and `--max-time`/interval tuning on `health_check.sh`.
Mechanics and rationale live in the operations doc; the evidence (failing runs, revision
logs, the 240s platform cap) is recorded in the Stage 1 section of
`api-v1-pr4-cloud-run-host-cutover-execution-plan.md` in the planning folder.

## One-Time Bootstrap (completed 2026-07-02)

The CI pipeline cannot create this service itself, for two reasons:

1. `deploy_cloud_run_candidate.sh` always deploys with `--no-traffic` (the PR 3
   candidate-then-promote pattern). gcloud rejects `--no-traffic` when creating a new
   service, because a new service must route 100% of traffic to its first revision.
2. The GitHub deploy service account holds `roles/run.developer`, which can create and
   deploy services but cannot set IAM policy. The `allUsers` -> `roles/run.invoker`
   binding that `--allow-unauthenticated` needs on a new service must be created by a
   project owner or `roles/run.admin` principal. (The production service's binding was
   created manually during PR 3.)

Bootstrap command, run once by a project owner before merging the Stage 1 PR:

```bash
gcloud run deploy policyengine-api-staging \
  --project policyengine-api \
  --region us-central1 \
  --image us-docker.pkg.dev/cloudrun/container/hello \
  --allow-unauthenticated \
  --service-account policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com
```

The placeholder image is intentional: the first CI staging deploy replaces the revision
entirely, since `deploy_cloud_run_candidate.sh` sets every flag (image, env vars, secrets,
resources, service account, Cloud SQL attachment) explicitly on each deploy.

## Verification

```bash
gcloud run services describe policyengine-api-staging \
  --project policyengine-api --region us-central1 \
  --format "value(status.url, spec.template.spec.serviceAccountName)"
gcloud run services get-iam-policy policyengine-api-staging \
  --project policyengine-api --region us-central1
curl -s -o /dev/null -w '%{http_code}\n' <service URL>
```

Expected: service URL resolves, runtime service account is
`policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com`, IAM policy contains
`allUsers` with `roles/run.invoker`, and the curl returns 200.

## Steady State After Stage 1

Described in [`../cloud-run-operations.md`](../cloud-run-operations.md) (topology,
startup behavior, IAM/secrets follow-ups) — that document, not this record, tracks
current reality.

## Exit Gates

Evaluated on the first post-merge push cycle (source of truth: the Stage 1 section of
`api-v1-pr4-cloud-run-host-cutover-execution-plan.md` in the planning folder):

- `gcloud run services describe policyengine-api --region us-central1` shows only
  `stage3-prod-*` tags at 100% at all times, including after the staging promote step.
- `policyengine-api-staging` is healthy and passes the staging integration suite via its
  own URL.
- `X-PolicyEngine-Backend` is present and correct on the App Engine production URL, the
  Cloud Run staging service URL, and the Cloud Run production service URL.
- New revisions show startup CPU boost in `gcloud run services describe`; every Cloud Run
  deploy job (staging + prod candidate) green on first attempt.
- Revision logs show the port bound within ~15s of instance start and `/readiness-check`
  healthy within the `health_check.sh` budget; the container-start → ready duration is
  recorded as an input to Stage 2's timing qualification.
