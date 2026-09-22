"""Verify allowed and denied Modal identities against Google WIF.

Set ``POLICYENGINE_WIF_TEST_APP`` in the local process before ``modal run``.
The script never returns or prints the Modal identity token or Google tokens.
"""

# pyright: reportMissingImports=false

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import modal

POOL = "modal-api-v1"
PROVIDER = "modal-api-v1"
APP_NAME = os.environ.get(
    "POLICYENGINE_WIF_TEST_APP",
    "policyengine-observability-wif-denied-test",
)

app = modal.App(APP_NAME)


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing deployment variable: {name}")
    return value


def _jwt_claims(token: str) -> dict[str, object]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _post_form(url: str, values: dict[str, str]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    bearer_token: str,
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
        return response.status, json.loads(body) if body else {}


def _error_result(error: urllib.error.HTTPError) -> dict[str, object]:
    try:
        payload = json.loads(error.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    error_payload = payload.get("error", {})
    if isinstance(error_payload, dict):
        error_name = error_payload.get("status") or error_payload.get("error")
    else:
        error_name = error_payload
    return {
        "http_status": error.code,
        "error": error_name,
    }


@app.function(timeout=60)
def verify_identity(
    project: str,
    project_number: str,
    workspace_id_digest: str,
) -> dict[str, object]:
    service_account = f"policyengine-api-v1-modal@{project}.iam.gserviceaccount.com"
    collector = (
        "https://policyengine-api-v1-otel-collector-"
        f"{project_number}.us-central1.run.app"
    )
    identity_token = os.environ["MODAL_IDENTITY_TOKEN"]
    claims = _jwt_claims(identity_token)
    safe_claims = {
        key: claims.get(key)
        for key in (
            "environment_name",
            "app_name",
            "function_name",
            "aud",
            "iss",
        )
    }
    workspace_id = str(claims.get("workspace_id", ""))
    workspace_id_matches = (
        hashlib.sha256(workspace_id.encode()).hexdigest() == workspace_id_digest
    )
    audience = (
        "//iam.googleapis.com/projects/"
        f"{project_number}/locations/global/workloadIdentityPools/{POOL}"
        f"/providers/{PROVIDER}"
    )
    try:
        sts_payload = _post_form(
            "https://sts.googleapis.com/v1/token",
            {
                "audience": audience,
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "requested_token_type": (
                    "urn:ietf:params:oauth:token-type:access_token"
                ),
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "subject_token": identity_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            },
        )
    except urllib.error.HTTPError as error:
        return {
            "claims": safe_claims,
            "workspace_id_matches": workspace_id_matches,
            "token_exchange": _error_result(error),
        }

    federated_token = str(sts_payload["access_token"])
    service_account_url = (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{service_account}"
    )
    access_status, access_payload = _post_json(
        f"{service_account_url}:generateAccessToken",
        {
            "scope": ["https://www.googleapis.com/auth/cloud-platform"],
            "lifetime": "300s",
        },
        bearer_token=federated_token,
    )
    service_access_token = str(access_payload["accessToken"])

    identity_status, identity_payload = _post_json(
        f"{service_account_url}:generateIdToken",
        {"audience": collector, "includeEmail": True},
        bearer_token=federated_token,
    )
    collector_identity_token = str(identity_payload["token"])
    collector_request = urllib.request.Request(
        collector,
        headers={"Authorization": f"Bearer {collector_identity_token}"},
    )
    try:
        with urllib.request.urlopen(collector_request, timeout=15) as response:
            collector_status = response.status
    except urllib.error.HTTPError as error:
        collector_status = error.code

    verification_id = f"modal-wif-{int(time.time())}"
    logging_status, _ = _post_json(
        "https://logging.googleapis.com/v2/entries:write",
        {
            "logName": f"projects/{project}/logs/policyengine-api-v1-modal",
            "resource": {
                "type": "global",
                "labels": {"project_id": project},
            },
            "entries": [
                {
                    "insertId": verification_id,
                    "jsonPayload": {
                        "schema_version": "policyengine.observability.v2",
                        "verification_id": verification_id,
                        "service.namespace": "policyengine.api-v1",
                        "service.name": safe_claims["app_name"],
                        "message": "Modal WIF verification",
                    },
                }
            ],
        },
        bearer_token=service_access_token,
    )
    return {
        "claims": safe_claims,
        "workspace_id_matches": workspace_id_matches,
        "token_exchange": {"http_status": 200},
        "service_account_access": {"http_status": access_status},
        "service_account_identity": {"http_status": identity_status},
        "collector_http_status": collector_status,
        "logging_http_status": logging_status,
        "verification_id": verification_id,
    }


@app.local_entrypoint()
def main() -> None:
    project = _required_environment("OBSERVABILITY_PROJECT_ID")
    project_number = _required_environment("OBSERVABILITY_PROJECT_NUMBER")
    workspace_id = _required_environment("MODAL_WORKSPACE_ID")
    workspace_id_digest = hashlib.sha256(workspace_id.encode()).hexdigest()
    result = getattr(verify_identity, "remote")(
        project,
        project_number,
        workspace_id_digest,
    )
    print(json.dumps(result, sort_keys=True))
