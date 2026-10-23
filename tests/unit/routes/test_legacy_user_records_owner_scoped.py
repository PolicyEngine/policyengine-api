"""Every operation on a legacy (v1) user record is owner-scoped.

The v1 user records are ``user_profiles``, ``user_policies`` and the
``user_policy_mirror_events`` that copy saved policies to v2. The routes that
read and changed them (``/{country_id}/user-profile`` and
``/{country_id}/user-policy``) took the owner from the request (a ``user_id``,
``auth0_id`` or record ``id``) and checked no credential, so they are removed.
Signed-in users reach their saved work through the v2 routes, which take the
owner from the verified credential. What these tests hold:

1. No route of the deployed application, Flask or native, serves the removed
   paths.
2. No module an HTTP route can import reads or writes those tables: the v1
   user-record models and the v1 saved-policy service are out of reach.
3. For every request to the removed paths, whatever its method, country,
   identifier, query, body or credentials, the answer is 404 or 405, and no
   stored user record is changed or echoed back.
"""

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from policyengine_api.asgi_factory import NativeRouteDependencies, create_asgi_app
from policyengine_api.constants import COUNTRIES
from policyengine_api.data.v1_models import (
    UserPolicy,
    UserPolicyMirrorEvent,
    UserProfile,
)
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)

PACKAGE_ROOT = Path(__file__).parents[3] / "policyengine_api"
LEGACY_USER_PATH_SEGMENTS = ("user-profile", "user-policy")
# Modules that read or write the v1 user-record tables.
LEGACY_USER_RECORD_MODULES = frozenset(
    {
        "policyengine_api.services.user_policy_service",
        "policyengine_api.services.user_policy_mirroring",
        "policyengine_api.services.user_service",
        "policyengine_api.routes.user_profile_routes",
    }
)
LEGACY_USER_RECORD_MODELS = frozenset(
    {"UserProfile", "UserPolicy", "UserPolicyMirrorEvent"}
)
# Everything that serves HTTP: the two application modules and every route
# module, Flask and native.
HTTP_ENTRY_POINTS = (
    "policyengine_api.api",
    "policyengine_api.asgi",
    "policyengine_api.asgi_factory",
)
SEEDED_SECRETS = (
    "auth0|seeded-owner",
    "seeded-username",
    "Seeded saved reform",
    "auth0|seeded-saved-policy-owner",
)


class _HealthyGateway:
    def check_health(self) -> None:
        return None


class _MetadataReader:
    def get_metadata(self, country_id: str) -> dict:
        return {"country_id": country_id}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_modules() -> dict[str, ast.Module]:
    return {
        _module_name(path): ast.parse(path.read_text(encoding="utf-8"))
        for path in PACKAGE_ROOT.rglob("*.py")
    }


def _imported_names(module_name: str, tree: ast.Module) -> set[str]:
    """Every module this one imports anywhere in its body, function-local included."""
    package = module_name.rsplit(".", 1)[0]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.rsplit(".", node.level - 1)[0]
                base = f"{anchor}.{base}" if base else anchor
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names)
    return imported


def _http_reachable_modules() -> set[str]:
    modules = _package_modules()
    roots = {
        name
        for name in modules
        if name in HTTP_ENTRY_POINTS
        or name.startswith(
            ("policyengine_api.routes.", "policyengine_api.fastapi_routes.")
        )
    }
    reachable: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in reachable or name not in modules:
            continue
        reachable.add(name)
        for imported in _imported_names(name, modules[name]):
            # Importing a.b.c also runs a and a.b.
            parts = imported.split(".")
            pending.extend(".".join(parts[:end]) for end in range(1, len(parts) + 1))
    return reachable


def _imports_legacy_user_model(tree: ast.Module) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("data.v1_models")
        for alias in node.names
        if alias.name in LEGACY_USER_RECORD_MODELS
    }


@pytest.fixture
def asgi_client(mock_v2_runtime_settings):
    from policyengine_api.api import app as flask_app

    app = create_asgi_app(
        flask_app,
        route_settings=RouteImplementationSettings(
            health=RouteImplementation.FASTAPI_NATIVE,
            specification=RouteImplementation.FASTAPI_NATIVE,
            metadata=RouteImplementation.FASTAPI_NATIVE,
        ),
        dependencies=NativeRouteDependencies(
            readiness_probe=lambda: True,
            gateway_client_factory=_HealthyGateway,
            metadata_reader_factory=_MetadataReader,
            specification_provider=lambda: {"openapi": "3.0.0"},
        ),
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def seeded_user_records(orm_session_factory):
    with orm_session_factory.begin() as session:
        session.add(
            UserProfile(
                user_id=1,
                auth0_id="auth0|seeded-owner",
                username="seeded-username",
                primary_country="us",
                user_since=1,
            )
        )
        session.add(
            UserPolicy(
                id=1,
                country_id="us",
                reform_id=2,
                reform_label="Seeded saved reform",
                baseline_id=1,
                baseline_label="Current law",
                user_id="auth0|seeded-saved-policy-owner",
                year="2026",
                geography="us",
                dataset=None,
                number_of_provisions=1,
                api_version="1",
                added_date=1,
                updated_date=1,
                budgetary_impact=None,
                type=None,
            )
        )
    return orm_session_factory


def _user_record_snapshot(session_factory) -> tuple:
    """Every stored v1 user record, by column value."""
    with session_factory() as session:
        return tuple(
            tuple(
                tuple(getattr(row, column.name) for column in model.__table__.columns)
                for row in session.scalars(select(model))
            )
            for model in (UserProfile, UserPolicy, UserPolicyMirrorEvent)
        )


def test_deployed_application_serves_no_legacy_user_route(asgi_client):
    from policyengine_api.api import app as flask_app

    flask_rules = {rule.rule for rule in flask_app.url_map.iter_rules()}
    native_paths = {
        getattr(route, "path", "") for route in asgi_client.app.app.router.routes
    }

    for path in flask_rules | native_paths:
        segments = path.strip("/").split("/")
        assert not set(segments) & set(LEGACY_USER_PATH_SEGMENTS), path


def test_no_http_route_can_reach_the_legacy_user_record_tables():
    modules = _package_modules()
    reachable = _http_reachable_modules()

    # The walk must see the application, or the check proves nothing.
    assert {
        "policyengine_api.api",
        "policyengine_api.routes.policy_routes",
        "policyengine_api.fastapi_routes.v2.user_policies.routes",
    } <= reachable
    assert reachable & LEGACY_USER_RECORD_MODULES == set()
    assert {
        name: sorted(models)
        for name in sorted(reachable)
        if (models := _imports_legacy_user_model(modules[name]))
    } == {}


def test_reachability_check_detects_a_route_that_imports_the_saved_policy_service():
    tree = ast.parse(
        "from policyengine_api.services.user_policy_service import UserPolicyService\n"
        "from policyengine_api.data.v1_models import UserProfile\n"
    )

    assert "policyengine_api.services.user_policy_service" in _imported_names(
        "policyengine_api.routes.example_routes", tree
    )
    assert _imports_legacy_user_model(tree) == {"UserProfile"}


_identifiers = st.one_of(
    st.integers(min_value=-1, max_value=2**31),
    st.sampled_from(
        ["auth0|seeded-owner", "auth0|seeded-saved-policy-owner", "me", "1"]
    ),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="|-_."
        ),
        min_size=1,
        max_size=24,
    ),
)
_ownership_fields = st.dictionaries(
    st.sampled_from(
        ["id", "user_id", "auth0_id", "username", "reform_label", "primary_country"]
    ),
    st.one_of(_identifiers, st.none()),
    max_size=6,
)
_credentials = st.one_of(
    st.just({}),
    st.builds(
        lambda token: {"Authorization": f"Bearer {token}"},
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.", min_size=1),
    ),
    st.builds(
        lambda value: {UNAUTHENTICATED_USER_HEADER: str(value)},
        st.uuids(),
    ),
)


@st.composite
def legacy_user_requests(draw) -> dict:
    country = draw(st.one_of(st.sampled_from(COUNTRIES), st.just("zz")))
    segment = draw(st.sampled_from(LEGACY_USER_PATH_SEGMENTS))
    suffix = draw(st.one_of(st.just(""), st.builds(lambda i: f"/{i}", _identifiers)))
    method = draw(st.sampled_from(["GET", "POST", "PUT", "PATCH", "DELETE"]))
    query = draw(_ownership_fields)
    body = draw(st.one_of(st.none(), _ownership_fields))
    return {
        "method": method,
        "url": f"/{country}/{segment}{suffix}",
        "params": {key: str(value) for key, value in query.items()},
        "json": body,
        "headers": draw(_credentials),
    }


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(request=legacy_user_requests())
def test_no_request_to_a_removed_path_reads_or_changes_a_user_record(
    asgi_client, seeded_user_records, request
):
    before = _user_record_snapshot(seeded_user_records)

    with patch("policyengine_api.migration_logging.logger"):
        response = asgi_client.request(
            request["method"],
            request["url"],
            params=request["params"],
            content=None if request["json"] is None else json.dumps(request["json"]),
            headers={"Content-Type": "application/json", **request["headers"]},
        )

    assert response.status_code in {404, 405}, (request, response.text)
    assert not any(secret in response.text for secret in SEEDED_SECRETS)
    assert _user_record_snapshot(seeded_user_records) == before
