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
`pe-uk-private-hf-read-token`. Both API v1 Cloud Run runtime service accounts
receive `roles/secretmanager.secretAccessor` for that resource. The
synchronization script resolves the runtime identities from the deployed
`policyengine-api-staging` and `policyengine-api` services rather than relying
on a duplicated account-name configuration value, then verifies both IAM
bindings.
The synchronization workflow reads the newly stored version back and compares
it in memory with the GitHub value without logging either value.

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
