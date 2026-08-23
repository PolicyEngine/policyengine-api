"""Render App Engine runtime configuration without handling secret values."""

from __future__ import annotations

import json
import os
from pathlib import Path


SIMULATION_URL_ENV_BY_ENTRYPOINT = {
    "old_gateway_direct": "OLD_SIMULATION_GATEWAY_URL",
    "cloud_run_simulation_entrypoint": "SIMULATION_ENTRYPOINT_URL",
}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _render_app_config() -> str:
    sim_entrypoint = _required("SIM_ENTRYPOINT")
    try:
        selected_url_env = SIMULATION_URL_ENV_BY_ENTRYPOINT[sim_entrypoint]
    except KeyError as error:
        raise ValueError(
            "SIM_ENTRYPOINT must be old_gateway_direct or "
            "cloud_run_simulation_entrypoint"
        ) from error

    selected_url = os.environ.get(selected_url_env, "").strip()
    if not selected_url:
        raise ValueError(
            f"{selected_url_env} is required when SIM_ENTRYPOINT={sim_entrypoint}"
        )

    replacements = {
        ".policyengine_db_instance_connection_name": _required(
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME"
        ),
        ".policyengine_db_password_secret_resource": _required(
            "POLICYENGINE_DB_PASSWORD_SECRET_RESOURCE"
        ),
        ".policyengine_github_microdata_auth_token_secret_resource": _required(
            "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN_SECRET_RESOURCE"
        ),
        ".openai_api_key_secret_resource": _required("OPENAI_API_KEY_SECRET_RESOURCE"),
        ".hugging_face_token_secret_resource": _required(
            "HUGGING_FACE_TOKEN_SECRET_RESOURCE"
        ),
        ".simulation_entrypoint_url": os.environ.get(
            "SIMULATION_ENTRYPOINT_URL", ""
        ).strip(),
        ".old_simulation_gateway_url": os.environ.get(
            "OLD_SIMULATION_GATEWAY_URL", ""
        ).strip(),
        ".sim_entrypoint": sim_entrypoint,
        ".gateway_auth_issuer": _required("GATEWAY_AUTH_ISSUER"),
        ".gateway_auth_audience": _required("GATEWAY_AUTH_AUDIENCE"),
        ".gateway_auth_client_id": _required("GATEWAY_AUTH_CLIENT_ID"),
        ".gateway_auth_client_secret_resource": _required(
            "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE"
        ),
        ".runtime_cache_environment": _required("RUNTIME_CACHE_ENVIRONMENT"),
        ".runtime_cache_url_secret_resource": _required(
            "RUNTIME_CACHE_URL_SECRET_RESOURCE"
        ),
        ".runtime_cache_ca_cert_secret_resource": _required(
            "RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE"
        ),
        ".v2_supabase_project_ref": _required("V2_SUPABASE_PROJECT_REF"),
        ".v2_supabase_environment": _required("V2_SUPABASE_ENVIRONMENT"),
    }

    template = Path("gcp/policyengine_api/app.yaml").read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        quoted_placeholder = json.dumps(placeholder)
        if quoted_placeholder not in template:
            raise ValueError(f"App Engine template is missing {placeholder}")
        template = template.replace(quoted_placeholder, json.dumps(value))
    return template


Path("app.yaml").write_text(_render_app_config(), encoding="utf-8")
Path("Dockerfile").write_text(
    Path("gcp/policyengine_api/Dockerfile").read_text(encoding="utf-8"),
    encoding="utf-8",
)
