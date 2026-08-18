"""Regression tests for the bounded recent-simulations route.

The route originally built a SQL LIMIT through an f-string. Reform impacts now
use the shared runtime cache, but the public limit, input-safety, ordering, and
v1 response-shape contracts remain unchanged.
"""

from datetime import datetime
import json

from fastapi.testclient import TestClient
from flask import Flask
import pytest

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.routes import reform_impact_routes
from policyengine_api.routes.reform_impact_routes import reform_impact_bp
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.repositories import (
    ReformImpactCache,
    reform_impact_id,
)
from policyengine_api.services.reform_impacts_service import ReformImpactsService


COMPLETED_AT = datetime(2026, 1, 1, 1)


@pytest.fixture
def reform_impacts_service(monkeypatch: pytest.MonkeyPatch) -> ReformImpactsService:
    service = ReformImpactsService(
        ReformImpactCache(
            InMemoryCacheBackend(),
            CacheNamespace("test", "api"),
        )
    )
    monkeypatch.setattr(service, "_now", lambda: COMPLETED_AT)
    monkeypatch.setattr(reform_impact_routes, "reform_impacts_service", service)
    return service


def _get_simulations(max_results=100):
    app = _create_app()
    query = "" if max_results is None else f"?max_results={max_results}"
    return app.test_client().get(f"/simulations{query}").get_json()


def _create_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(reform_impact_bp)
    return app


def _seed_reform_impacts(service: ReformImpactsService, n: int) -> None:
    for i in range(n):
        execution_id = f"exec-{i}"
        service.set_reform_impact(
            baseline_policy_id=i + 1,
            policy_id=i + 2,
            country_id="us",
            region="us",
            dataset="custom_dataset",
            time_period="2025",
            options={},
            options_hash=f"hash-{i}",
            api_version="1.0.0",
            reform_impact_json={},
            status="computing",
            start_time=datetime(2026, 1, 1, 0, i // 60, i % 60),
            execution_id=execution_id,
        )
        service.set_complete_reform_impact(
            country_id="us",
            reform_policy_id=i + 2,
            baseline_policy_id=i + 1,
            region="us",
            dataset="custom_dataset",
            time_period="2025",
            options_hash=f"hash-{i}",
            reform_impact_json={},
            execution_id=execution_id,
        )


def test_get_simulations_default_limit_caps_at_100(reform_impacts_service):
    _seed_reform_impacts(reform_impacts_service, 150)
    result = _get_simulations()
    assert len(result["result"]) == 100
    assert result["result"][0]["execution_id"] == "exec-149"
    assert result["result"][-1]["execution_id"] == "exec-50"


def test_get_simulations_clamps_huge_max_results(reform_impacts_service):
    _seed_reform_impacts(reform_impacts_service, 50)
    # A caller passing an absurdly large value must not crash and
    # must not cause a full scan; the value is clamped at 1000.
    result = _get_simulations(max_results=10**9)
    assert len(result["result"]) == 50  # only 50 seeded


def test_get_simulations_clamps_negative_max_results(reform_impacts_service):
    _seed_reform_impacts(reform_impacts_service, 5)
    # max_results of 0 or negative must still return something sane.
    result = _get_simulations(max_results=0)
    assert 1 <= len(result["result"]) <= 5


def test_get_simulations_defaults_when_none(reform_impacts_service):
    _seed_reform_impacts(reform_impacts_service, 10)
    result = _get_simulations(max_results=None)
    assert len(result["result"]) == 10  # fewer than the default 100


def test_get_simulations_rejects_non_integer_gracefully(reform_impacts_service):
    _seed_reform_impacts(reform_impacts_service, 5)
    # An invalid value must not become a cache-index bound; it falls back to
    # the default without altering the stored values.
    result = _get_simulations(max_results="100; DROP TABLE reform_impact")
    assert len(result["result"]) == 5
    assert len(reform_impacts_service.get_recent_reform_impacts(100)) == 5


def test_get_simulations_preserves_complete_v1_response_shape(
    reform_impacts_service,
):
    _seed_reform_impacts(reform_impacts_service, 1)

    impact = _get_simulations(max_results=1)["result"][0]

    assert impact == {
        "reform_impact_id": reform_impact_id("exec-0"),
        "baseline_policy_id": 1,
        "reform_policy_id": 2,
        "country_id": "us",
        "region": "us",
        "dataset": "custom_dataset",
        "time_period": "2025",
        "options_json": json.dumps({}),
        "options_hash": "hash-0",
        "api_version": "1.0.0",
        "reform_impact_json": json.dumps({}),
        "status": "ok",
        "message": "Completed",
        "start_time": "2026-01-01 00:00:00",
        "end_time": "2026-01-01 01:00:00",
        "execution_id": "exec-0",
    }


def test_get_simulations_matches_through_fastapi_fallback(reform_impacts_service):
    _seed_reform_impacts(reform_impacts_service, 1)
    app = _create_app()

    flask_response = app.test_client().get("/simulations?max_results=1")
    asgi_response = TestClient(create_asgi_app(app)).get("/simulations?max_results=1")

    assert asgi_response.status_code == flask_response.status_code == 200
    assert asgi_response.json() == flask_response.get_json()
