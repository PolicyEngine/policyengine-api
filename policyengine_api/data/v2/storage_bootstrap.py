"""Explicit, idempotent bootstrap for the Stage 8 private Storage bucket."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from policyengine_api.data.v2.settings import SupabaseStorageSettings


RECORDED_STORAGE_TARGETS = {
    "production-foundation": "kvrifaviwhzjztcbrfpy",
}
STORAGE_REQUEST_TIMEOUT_SECONDS = 10.0


class StorageBootstrapError(RuntimeError):
    """Raised without response bodies or credentials when bootstrap is unsafe."""


class StorageHTTPClient(Protocol):
    """Narrow HTTP surface needed by the Storage initializer."""

    def get(self, url: str, **kwargs: Any) -> httpx.Response: ...

    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True)
class StorageBucketConfiguration:
    """Reviewed Stage 8 Storage bucket properties."""

    id: str
    name: str
    public: bool = False
    file_size_limit: int | None = None
    allowed_mime_types: tuple[str, ...] | None = None

    def create_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "public": self.public,
            "file_size_limit": self.file_size_limit,
            "allowed_mime_types": (
                list(self.allowed_mime_types)
                if self.allowed_mime_types is not None
                else None
            ),
        }


@dataclass(frozen=True)
class StorageBootstrapResult:
    """Secret-free result suitable for operator output."""

    bucket: str
    created: bool
    public: bool
    environment: str
    project_ref: str


def _qualify_target(settings: SupabaseStorageSettings) -> None:
    recorded_ref = RECORDED_STORAGE_TARGETS.get(settings.environment)
    if recorded_ref != settings.project_ref:
        raise StorageBootstrapError(
            "Storage environment and project reference do not match the "
            "recorded Stage 8 target"
        )


def _headers(settings: SupabaseStorageSettings) -> dict[str, str]:
    key = settings.admin_key.get_secret_value()
    return {
        "apikey": key,
        "Content-Type": "application/json",
    }


def _decode_bucket(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as error:
        raise StorageBootstrapError(
            "Supabase Storage returned an invalid bucket response"
        ) from error
    if not isinstance(value, dict):
        raise StorageBootstrapError(
            "Supabase Storage returned an invalid bucket response"
        )
    return value


def _storage_error(response: httpx.Response) -> tuple[str | None, str | None]:
    """Return only stable, non-secret Storage error identifiers."""

    try:
        value = response.json()
    except ValueError:
        return None, None
    if not isinstance(value, dict):
        return None, None
    code = value.get("code")
    status_code = value.get("statusCode", value.get("httpStatusCode"))
    return (
        code if isinstance(code, str) else None,
        str(status_code) if status_code is not None else None,
    )


def _is_missing_bucket(response: httpx.Response) -> bool:
    code, status_code = _storage_error(response)
    return response.status_code == 404 or code == "NoSuchBucket" or status_code == "404"


def _is_creation_conflict(response: httpx.Response) -> bool:
    code, status_code = _storage_error(response)
    return (
        response.status_code == 409
        or code in {"BucketAlreadyExists", "ResourceAlreadyExists"}
        or status_code == "409"
    )


def _verify_bucket(
    observed: dict[str, Any],
    expected: StorageBucketConfiguration,
) -> None:
    expected_values = {
        "id": expected.id,
        "name": expected.name,
        "public": expected.public,
        "file_size_limit": expected.file_size_limit,
        "allowed_mime_types": (
            list(expected.allowed_mime_types)
            if expected.allowed_mime_types is not None
            else None
        ),
    }
    incompatible = {
        field: {"expected": expected_value, "observed": observed.get(field)}
        for field, expected_value in expected_values.items()
        if observed.get(field) != expected_value
    }
    if incompatible:
        fields = ", ".join(sorted(incompatible))
        raise StorageBootstrapError(
            f"existing Storage bucket has incompatible fields: {fields}"
        )


def initialize_supabase_storage(
    settings: SupabaseStorageSettings,
    *,
    client: StorageHTTPClient | None = None,
) -> StorageBootstrapResult:
    """Create or verify the recorded private bucket without replacing it."""

    _qualify_target(settings)
    expected = StorageBucketConfiguration(
        id=settings.bucket,
        name=settings.bucket,
    )
    headers = _headers(settings)
    bucket_url = (
        f"{settings.api_url}/storage/v1/bucket/{quote(settings.bucket, safe='')}"
    )
    collection_url = f"{settings.api_url}/storage/v1/bucket"
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=STORAGE_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
    )
    created = False
    try:
        try:
            response = active_client.get(bucket_url, headers=headers)
            if _is_missing_bucket(response):
                response = active_client.post(
                    collection_url,
                    headers=headers,
                    json=expected.create_payload(),
                )
                if _is_creation_conflict(response):
                    response = active_client.get(bucket_url, headers=headers)
                elif 200 <= response.status_code < 300:
                    created = True
                    response = active_client.get(bucket_url, headers=headers)
            if not 200 <= response.status_code < 300:
                raise StorageBootstrapError(
                    "Supabase Storage bucket verification failed with status "
                    f"{response.status_code}"
                )
            _verify_bucket(_decode_bucket(response), expected)
        except httpx.HTTPError as error:
            raise StorageBootstrapError(
                "Supabase Storage bucket verification request failed"
            ) from error
    finally:
        if owns_client:
            active_client.close()  # type: ignore[attr-defined]

    return StorageBootstrapResult(
        bucket=expected.id,
        created=created,
        public=expected.public,
        environment=settings.environment,
        project_ref=settings.project_ref,
    )
