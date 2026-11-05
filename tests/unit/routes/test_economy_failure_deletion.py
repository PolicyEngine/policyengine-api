"""DELETE on the economy URL removes the stored failure the GET answers from."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from flask import Flask
from flask_cors import CORS
from werkzeug.datastructures import MultiDict

from policyengine_api import worker_spm
from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.query_parameters import AnnualEconomyQuery, parse_multidict_query
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache import reform_impacts
from policyengine_api.runtime_cache.core import CacheCoordinationError, CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactCache,
)
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactExecution,
    ReformImpactsService,
)
from tests.fixtures.services.economy_service import ECONOMY_SERVICE_LOGGER_MODULES

FAILED_JOB = "failed-worker-job"
NEXT_JOB = "next-worker-job"
WORKER_ERROR = "Worker exhausted available memory"
STATE_QUERY = {"region": "state/ca", "time_period": "2026", "version": "1.0.0"}
LOCKED_MESSAGE = (
    "This failure was recorded less than 10 seconds ago, so it was not deleted. "
    "It can be deleted in {seconds} seconds."
)
NOT_FOUND_BODY = {
    "status": "error",
    "message": "No economic impact is stored for this request.",
    "result": None,
}
# The failed jobs a DELETE covers: (country, query beyond the version and year).
JOB_KINDS = [
    pytest.param("us", {"region": "us"}, id="us-national"),
    pytest.param("us", {"region": "state/ca"}, id="us-state"),
    pytest.param("us", {"region": "congressional_district/CA-37"}, id="us-district"),
    pytest.param("us", {"region": "place/NJ-57000"}, id="us-place"),
    pytest.param("uk", {"region": "uk"}, id="uk-national"),
    pytest.param(
        "uk", {"region": "uk", "breakdown": "local_areas"}, id="uk-local-areas"
    ),
]


class SharedClock:
    """One manual clock for the fake cache's expiry and the service's end times."""

    START = datetime(2026, 11, 5, 12, 0)

    def __init__(self) -> None:
        self.seconds = 0.0

    def cache_seconds(self) -> float:
        return self.seconds

    def service_time(self) -> datetime:
        return self.START + timedelta(seconds=self.seconds)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


@dataclass
class Harness:
    client: object
    cache: ReformImpactCache
    impacts: ReformImpactsService
    gateway: Mock
    clock: SharedClock
    country_id: str
    query: dict[str, str]

    @property
    def url(self) -> str:
        query = "&".join(f"{name}={value}" for name, value in self.query.items())
        return f"/{self.country_id}/economy/1/over/2?{query}"

    def stored(self) -> list[CachedReformImpact]:
        return self.cache.recent(10)


def _harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    country_id: str = "us",
    query: dict[str, str] | None = None,
    store_job: bool = True,
) -> Harness:
    # The fake worker reports an ordinary failure with no SPM output, so SPM
    # certification is out of this test's scope.
    monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: None)
    monkeypatch.setattr(reform_impacts, "jittered_ttl", lambda ttl: ttl - 7)
    query = {"time_period": "2026", "version": "1.0.0", **(query or STATE_QUERY)}
    clock = SharedClock()
    gateway = Mock()
    gateway.resolve_app_name.side_effect = lambda _country, version=None, **_: (
        "test-worker",
        version,
    )
    gateway.get_execution_by_id.return_value = SimpleNamespace(error=WORKER_ERROR)
    gateway.get_execution_status.return_value = "failed"
    gateway.get_execution_id.return_value = NEXT_JOB
    cache = ReformImpactCache(
        InMemoryCacheBackend(now=clock.cache_seconds),
        CacheNamespace("test", "failure-deletion"),
    )
    impacts = ReformImpactsService(cache, now=clock.service_time)
    policies = Mock()
    policies.get_policy_json.return_value = {}
    service = EconomyService(
        policy_service_=policies,
        reform_impacts_service_=impacts,
        simulation_entrypoint_=gateway,
    )
    if store_job:
        parsed = parse_multidict_query(AnnualEconomyQuery, MultiDict(query))
        setup = service._build_economic_impact_setup_options(
            service._with_normalized_region(
                economy_routes._annual_impact_request(country_id, 1, 2, parsed)
            ),
            time_period=parsed.time_period,
        )
        service._resolve_runtime_bundle_for_setup_options(setup)
        impacts.set_reform_impact(
            service._reform_impact_identity(setup),
            ReformImpactExecution(execution_id=FAILED_JOB, start_time=None),
            options=setup.options,
            status="computing",
            reform_impact_json={},
        )
    monkeypatch.setattr(economy_routes, "economy_service", service)
    for module_name in ECONOMY_SERVICE_LOGGER_MODULES:
        monkeypatch.setattr(f"{module_name}.logger", Mock())
    app = Flask(__name__)
    app.config["TESTING"] = True
    CORS(app)
    app.register_blueprint(economy_routes.economy_bp)
    return Harness(
        client=app.test_client(),
        cache=cache,
        impacts=impacts,
        gateway=gateway,
        clock=clock,
        country_id=country_id,
        query=query,
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return _harness(monkeypatch)


def _locked_body(seconds: int) -> dict[str, object]:
    return {
        "status": "error",
        "message": LOCKED_MESSAGE.format(seconds=seconds),
        "result": None,
        "delete_after_seconds": seconds,
    }


def _not_a_failure_body(status: str) -> dict[str, object]:
    return {
        "status": "error",
        "message": (
            f"The stored economic impact is {status}, not a failure, so it was "
            "not deleted."
        ),
        "result": None,
        "delete_after_seconds": None,
    }


def test_a_delete_inside_the_lockout_is_refused_with_the_seconds_left(
    harness: Harness,
) -> None:
    failed = harness.client.get(harness.url)
    at_once = harness.client.delete(harness.url)
    harness.clock.advance(3.5)
    part_way = harness.client.delete(harness.url)
    replayed = harness.client.get(harness.url)

    assert failed.status_code == 502
    assert failed.json["delete_after_seconds"] == 10
    assert at_once.status_code == 409
    assert at_once.json == _locked_body(10)
    # Rounded up, so a client that waits this long is never early.
    assert part_way.status_code == 409
    assert part_way.json == _locked_body(7)
    assert replayed.status_code == 502
    assert replayed.json["delete_after_seconds"] == 7
    assert [impact.status for impact in harness.stored()] == ["error"]


def test_a_delete_after_the_lockout_lets_the_next_get_start_a_new_run(
    harness: Harness,
) -> None:
    harness.client.get(harness.url)
    harness.clock.advance(10)

    deleted = harness.client.delete(harness.url)
    nothing_left = harness.stored()
    next_get = harness.client.get(harness.url)

    assert deleted.status_code == 204
    assert deleted.data == b""
    assert nothing_left == []
    assert next_get.status_code == 200
    assert next_get.json["status"] == "computing"
    harness.gateway.run.assert_called_once()
    assert [(impact.execution_id, impact.status) for impact in harness.stored()] == [
        (NEXT_JOB, "computing")
    ]


@pytest.mark.parametrize(("country_id", "query"), JOB_KINDS)
def test_a_delete_covers_every_kind_of_failed_job(
    monkeypatch: pytest.MonkeyPatch, country_id: str, query: dict[str, str]
) -> None:
    harness = _harness(monkeypatch, country_id=country_id, query=query)

    failed = harness.client.get(harness.url)
    harness.clock.advance(10)
    deleted = harness.client.delete(harness.url)

    assert failed.status_code == 502, failed.json
    assert failed.json["delete_after_seconds"] == 10
    assert deleted.status_code == 204, deleted.json
    assert harness.stored() == []


@pytest.mark.parametrize("status", ["computing", "ok"])
def test_a_delete_never_removes_a_computing_or_completed_job(
    harness: Harness, status: str
) -> None:
    if status == "ok":
        harness.cache.update(FAILED_JOB, status="ok", message="Completed")
    before = harness.stored()
    harness.clock.advance(60)

    refused = harness.client.delete(harness.url)

    assert refused.status_code == 409
    assert refused.json == _not_a_failure_body(status)
    assert harness.stored() == before
    harness.gateway.get_execution_by_id.assert_not_called()


def test_a_delete_with_nothing_stored_answers_404(monkeypatch) -> None:
    harness = _harness(monkeypatch, store_job=False)

    response = harness.client.delete(harness.url)

    assert response.status_code == 404
    assert response.json == NOT_FOUND_BODY


def test_a_second_delete_finds_nothing_stored(harness: Harness) -> None:
    harness.client.get(harness.url)
    harness.clock.advance(10)

    first = harness.client.delete(harness.url)
    second = harness.client.delete(harness.url)

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json == NOT_FOUND_BODY


@pytest.mark.parametrize(
    "query_string",
    [
        "region=state/ca&version=1.0.0",
        "region=state/ca&time_period=2026&unexpected=1",
        "region=state/ca&region=us&time_period=2026",
        "region=state/ca&time_period=not-a-year",
        "region=us&time_period=2026&breakdown=local_areas",
    ],
    ids=["missing-year", "unknown", "duplicate", "invalid-year", "us-breakdown"],
)
def test_a_delete_validates_its_query_exactly_as_the_get_does(
    harness: Harness, query_string: str
) -> None:
    url = f"/us/economy/1/over/2?{query_string}"

    get = harness.client.get(url)
    delete = harness.client.delete(url)

    assert get.status_code == 400
    assert delete.status_code == 400
    assert delete.json == get.json
    assert [impact.status for impact in harness.stored()] == ["computing"]


def test_a_delete_for_an_unsupported_country_answers_as_the_get_does(
    harness: Harness,
) -> None:
    url = "/xx/economy/1/over/2?region=xx&time_period=2026"

    get = harness.client.get(url)
    delete = harness.client.delete(url)

    assert delete.status_code == get.status_code == 400
    assert delete.json == get.json


def _before_the_atomic_delete(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, interleaved
) -> Mock:
    """Run ``interleaved`` once, after the DELETE chose a record, before it acts."""
    delete_failure = harness.cache.delete_failure
    calls = Mock()

    def delete_after_interleaving(failure: CachedReformImpact) -> bool:
        calls(failure)
        if calls.call_count == 1:
            interleaved()
        return delete_failure(failure)

    monkeypatch.setattr(harness.cache, "delete_failure", delete_after_interleaving)
    return calls


def _store_newer_job(harness: Harness) -> CachedReformImpact:
    [failure] = harness.stored()
    newer_job = replace(
        failure,
        reform_impact_id=reform_impacts.reform_impact_id(NEXT_JOB),
        status="computing",
        message=None,
        end_time=None,
        start_time=datetime(2026, 11, 5, 12, 1),
        execution_id=NEXT_JOB,
    )
    assert harness.cache.set(newer_job)
    return newer_job


def test_a_delete_leaves_a_job_that_a_get_submitted_at_the_same_moment(
    monkeypatch: pytest.MonkeyPatch, harness: Harness
) -> None:
    harness.client.get(harness.url)
    harness.clock.advance(10)
    newer_jobs: list[CachedReformImpact] = []
    _before_the_atomic_delete(
        monkeypatch, harness, lambda: newer_jobs.append(_store_newer_job(harness))
    )

    deleted = harness.client.delete(harness.url)

    assert deleted.status_code == 204
    assert harness.stored() == newer_jobs


def test_a_delete_rechecks_when_the_failure_expired_and_a_new_job_replaced_it(
    monkeypatch: pytest.MonkeyPatch, harness: Harness
) -> None:
    harness.client.get(harness.url)
    harness.clock.advance(10)

    def expire_the_failure_and_submit() -> None:
        newer_job = _store_newer_job(harness)
        harness.cache.client.delete(harness.cache._record_key(FAILED_JOB))
        assert harness.stored() == [newer_job]

    calls = _before_the_atomic_delete(
        monkeypatch, harness, expire_the_failure_and_submit
    )

    refused = harness.client.delete(harness.url)

    assert refused.status_code == 409
    assert refused.json == _not_a_failure_body("computing")
    assert [(impact.execution_id, impact.status) for impact in harness.stored()] == [
        (NEXT_JOB, "computing")
    ]
    assert calls.call_count == 1


def test_a_delete_rechecks_a_failure_that_was_recorded_again(
    monkeypatch: pytest.MonkeyPatch, harness: Harness
) -> None:
    harness.client.get(harness.url)
    harness.clock.advance(10)
    # A late poll of the same job records the failure again, just now.
    _before_the_atomic_delete(
        monkeypatch,
        harness,
        lambda: harness.cache.update(FAILED_JOB, end_time=harness.clock.service_time()),
    )

    refused = harness.client.delete(harness.url)

    assert refused.status_code == 409
    assert refused.json == _locked_body(10)
    assert [impact.status for impact in harness.stored()] == ["error"]


def test_a_delete_gives_up_when_the_record_keeps_changing(
    monkeypatch: pytest.MonkeyPatch, harness: Harness
) -> None:
    harness.client.get(harness.url)
    harness.clock.advance(10)
    always_changed = Mock(return_value=False)
    monkeypatch.setattr(harness.cache, "delete_failure", always_changed)

    with pytest.raises(CacheCoordinationError):
        harness.client.delete(harness.url)

    assert always_changed.call_count == 3
    assert [impact.status for impact in harness.stored()] == ["error"]


def test_a_browser_may_send_the_delete_from_another_origin(
    harness: Harness,
) -> None:
    origin = "https://app.policyengine.org"
    flask_app = harness.client.application
    client = TestClient(create_asgi_app(flask_app))
    harness.client.get(harness.url)

    preflight = client.options(
        harness.url,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "DELETE",
        },
    )
    flask_preflight = harness.client.options(
        harness.url,
        headers={"Origin": origin, "Access-Control-Request-Method": "DELETE"},
    )
    refused = client.delete(harness.url, headers={"Origin": origin})
    harness.clock.advance(10)
    deleted = client.delete(harness.url, headers={"Origin": origin})

    # The ASGI layer answers the preflight before Flask; Flask-CORS answers it
    # the same way when Flask serves alone.
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert "DELETE" in preflight.headers["access-control-allow-methods"]
    assert flask_preflight.status_code == 200
    assert flask_preflight.headers["Access-Control-Allow-Origin"] == origin
    assert "DELETE" in flask_preflight.headers["Access-Control-Allow-Methods"]
    # A refusal and a removal are both readable from the other origin.
    assert refused.status_code == 409
    assert refused.headers["access-control-allow-origin"] == origin
    assert deleted.status_code == 204
    assert deleted.headers["access-control-allow-origin"] == origin
