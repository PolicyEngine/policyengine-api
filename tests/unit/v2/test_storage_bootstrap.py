"""Isolated contract tests for explicit Supabase Storage initialization."""

import json
from pathlib import Path

import httpx
from pydantic import SecretStr
import pytest

from policyengine_api.constants import REPO
from policyengine_api.data.v2.settings import SupabaseStorageSettings
from policyengine_api.data.v2.storage_bootstrap import (
    StorageBootstrapError,
    initialize_supabase_storage,
)


PROJECT_REF = "kvrifaviwhzjztcbrfpy"
BUCKET = "policyengine-v2-alpha"
ADMIN_KEY = "test-storage-admin-secret"


def _settings(**overrides) -> SupabaseStorageSettings:
    values = {
        "project_ref": PROJECT_REF,
        "environment": "production-foundation",
        "api_url": f"https://{PROJECT_REF}.supabase.co",
        "bucket": BUCKET,
        "admin_key": SecretStr(ADMIN_KEY),
    }
    values.update(overrides)
    return SupabaseStorageSettings(**values)


def _bucket(**overrides) -> dict:
    values = {
        "id": BUCKET,
        "name": BUCKET,
        "public": False,
        "file_size_limit": None,
        "allowed_mime_types": None,
    }
    values.update(overrides)
    return values


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fresh_bootstrap_creates_then_verifies_private_bucket() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={"statusCode": "404", "code": "NoSuchBucket"},
            )
        if request.method == "POST":
            return httpx.Response(200, json={"name": BUCKET})
        return httpx.Response(200, json=_bucket())

    with _client(handler) as client:
        result = initialize_supabase_storage(_settings(), client=client)

    assert result.created is True
    assert result.public is False
    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    payload = json.loads(requests[1].content)
    assert payload == _bucket()
    assert "authorization" not in requests[1].headers
    assert requests[1].headers["apikey"] == ADMIN_KEY


def test_second_identical_bootstrap_is_a_read_only_success() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_bucket())

    with _client(handler) as client:
        result = initialize_supabase_storage(_settings(), client=client)

    assert result.created is False
    assert [request.method for request in requests] == ["GET"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public", True),
        ("name", "wrong-bucket"),
        ("file_size_limit", 1024),
        ("allowed_mime_types", ["image/png"]),
    ],
)
def test_incompatible_bucket_fails_without_update_delete_or_recreate(
    field: str,
    value,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_bucket(**{field: value}))

    with _client(handler) as client:
        with pytest.raises(StorageBootstrapError, match=field):
            initialize_supabase_storage(_settings(), client=client)

    assert [request.method for request in requests] == ["GET"]


def test_concurrent_creation_conflict_is_verified_without_overwrite() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(404)
        if request.method == "POST":
            return httpx.Response(
                400,
                json={"statusCode": "409", "code": "BucketAlreadyExists"},
            )
        return httpx.Response(200, json=_bucket())

    with _client(handler) as client:
        result = initialize_supabase_storage(_settings(), client=client)

    assert result.created is False
    assert [request.method for request in requests] == ["GET", "POST", "GET"]


def test_target_mismatch_fails_before_any_storage_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("target mismatch must make no request")

    with _client(handler) as client:
        with pytest.raises(StorageBootstrapError, match="recorded Stage 8"):
            initialize_supabase_storage(
                _settings(project_ref="aaaaaaaaaaaaaaaaaaaa"),
                client=client,
            )


def test_failures_and_results_never_expose_storage_credentials() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=ADMIN_KEY)

    with _client(handler) as client:
        with pytest.raises(StorageBootstrapError) as raised:
            initialize_supabase_storage(_settings(), client=client)

    assert ADMIN_KEY not in str(raised.value)
    assert ADMIN_KEY not in repr(_settings())


def test_bootstrap_surface_cannot_mutate_application_schema_or_data() -> None:
    implementation = (REPO / "policyengine_api/data/v2/storage_bootstrap.py").read_text(
        encoding="utf-8"
    )
    command = (REPO / "scripts/bootstrap_v2_supabase_storage.py").read_text(
        encoding="utf-8"
    )
    prohibited = {
        "V2_MIGRATION_DATABASE_URL",
        "create_all",
        "drop_all",
        "alembic",
        "sqlalchemy",
        "/rest/v1/",
        "/storage/v1/object",
    }
    assert all(value not in implementation + command for value in prohibited)
    assert "/storage/v1/bucket" in implementation
    assert "policyengine_api.api" not in command


def test_bootstrap_script_is_durable_tooling_not_one_off_scaffolding() -> None:
    path = Path("scripts/bootstrap_v2_supabase_storage.py")
    assert (REPO / path).is_file()
    assert "supabase/.temp" not in path.as_posix()
