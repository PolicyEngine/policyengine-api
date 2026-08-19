"""Resolve App Engine application secrets before starting Gunicorn."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from functools import lru_cache
import os
import re


SECRET_RESOURCE_PATTERN = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")
SECRET_ENV_SOURCES = (
    ("POLICYENGINE_DB_PASSWORD", "POLICYENGINE_DB_PASSWORD_SECRET_RESOURCE"),
    (
        "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN",
        "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN_SECRET_RESOURCE",
    ),
    ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_SECRET_RESOURCE"),
    ("OPENAI_API_KEY", "OPENAI_API_KEY_SECRET_RESOURCE"),
    ("HUGGING_FACE_TOKEN", "HUGGING_FACE_TOKEN_SECRET_RESOURCE"),
)


class AppEngineRuntimeConfigurationError(RuntimeError):
    """Raised without exposing a secret value."""


@lru_cache(maxsize=None)
def _load_secret_from_secret_manager(resource_name: str) -> str:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


def hydrate_app_engine_runtime_secrets(
    environ: MutableMapping[str, str] | None = None,
    *,
    secret_loader: Callable[[str], str] | None = None,
) -> None:
    """Resolve exactly one direct or Secret Manager source for every secret."""

    values = os.environ if environ is None else environ
    loader = secret_loader or _load_secret_from_secret_manager
    for value_name, resource_name in SECRET_ENV_SOURCES:
        direct_value = values.get(value_name, "")
        resource = values.get(resource_name, "").strip()
        if direct_value and resource:
            raise AppEngineRuntimeConfigurationError(
                f"set exactly one of {value_name} or {resource_name}"
            )
        if direct_value:
            if not direct_value.strip():
                raise AppEngineRuntimeConfigurationError(f"{value_name} is empty")
            continue
        if not resource:
            raise AppEngineRuntimeConfigurationError(
                f"{value_name} or {resource_name} is required"
            )
        if SECRET_RESOURCE_PATTERN.fullmatch(resource) is None:
            raise AppEngineRuntimeConfigurationError(f"{resource_name} is invalid")
        try:
            resolved_value = loader(resource)
        except Exception as error:
            raise AppEngineRuntimeConfigurationError(
                f"{resource_name} could not be resolved"
            ) from error
        if not resolved_value or not resolved_value.strip():
            raise AppEngineRuntimeConfigurationError(f"{resource_name} is empty")
        values[value_name] = resolved_value
        values.pop(resource_name, None)


def main() -> None:
    hydrate_app_engine_runtime_secrets()
    port = os.environ.get("PORT", "8080")
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "-b",
            f":{port}",
            "policyengine_api.api",
            "--timeout",
            "900",
            "--workers",
            "5",
        ],
    )


if __name__ == "__main__":
    main()
