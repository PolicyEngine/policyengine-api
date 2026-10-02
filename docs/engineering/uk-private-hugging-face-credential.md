# UK private-data Hugging Face credential

API and simulation deployments use one read-only Hugging Face credential for
the private UK runtime data. Its managed name is
`PE_UK_PRIVATE_HF_READ_TOKEN`.

## Required access

The credential must be a fine-grained token named
`pe-uk-private-hf-read-token` with read-only access to:

- the model repository `policyengine/policyengine-uk-data-private`;
- the dataset repository `policyengine/populace-uk-private`.

It must not have repository write access. The deployed API and simulation
paths do not use `policyengine/populace-uk-staging`; build and publication
credentials for that repository are separate.

## API v1 path

The selected-repository GitHub organization secret
`PE_UK_PRIVATE_HF_READ_TOKEN` is copied to the Google Secret Manager resource
`pe-uk-private-hf-read-token`. It is one member of the GitHub-owned runtime
secret batch, alongside the environment-specific database password and the
shared GitHub microdata and OpenAI credentials.

Each staging and production deployment synchronizes the shared three-secret
batch before deploying its Cloud Run candidate. Production additionally
synchronizes the existing GitHub-owned database password to
`policyengine-api-prod-db-password`. Staging deliberately leaves
`policyengine-api-staging-db-password` untouched: its value differs from the
production password and its canonical value is managed directly in Secret
Manager rather than duplicated in GitHub. Synchronization compares SHA-256
digests without logging either value and creates a new secret version only when
the value changed. It then reads back and verifies every synchronized value.

The synchronization script resolves the runtime identity from the deployed
`policyengine-api-staging` or `policyengine-api` service. It grants that identity
`roles/secretmanager.secretAccessor` on every resource synchronized for that
environment and verifies each IAM binding. A manually dispatched workflow
performs the corresponding staging or production operation when credentials
need to be rotated independently of a deployment.

Cloud Run exposes the resource as `HUGGING_FACE_TOKEN` because PolicyEngine
Core reads that compatibility environment variable. `HUGGING_FACE_TOKEN` is
not the name of the stored GitHub or Google Cloud credential.

The pull-request environment check verifies the token identity, confirms that
it has no write permission, and checks both required private repositories. The
Cloud Run candidate resolver verifies that the exact deployed revision binds
`HUGGING_FACE_TOKEN` to `pe-uk-private-hf-read-token:latest`, without printing
the credential.

The simulation-entry Cloud Run service does not receive this credential. It
submits requests to Modal and does not download model data.

## Rotation and retirement

Provision the replacement credential before merging workflow changes. Deploy
and verify staging before production. Keep the previous Google Secret Manager
resource during the rollback period; then disable its version before deleting
the resource.

Do not remove the organization secret named `HUGGING_FACE_TOKEN` as part of
this migration. Other PolicyEngine repositories still consume it.
