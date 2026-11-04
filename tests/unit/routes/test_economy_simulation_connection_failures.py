"""The economy routes answer 502 when the simulation service gives no response.

The route, the economy service and the Simulation Entrypoint client are the
real ones; only the simulation service is a httpx.MockTransport, opened through
the client's retrying transport, as in production.
"""

from unittest.mock import Mock

import httpx
import pytest
from flask import Flask

from policyengine_api import worker_spm
from policyengine_api.libs import simulation_request_diagnostics
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.libs.simulation_entrypoint_transport import (
    SimulationEntrypointTransport,
)
from policyengine_api.routes import economy_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import ReformImpactCache
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from tests.fixtures.services.economy_service import ECONOMY_SERVICE_LOGGER_MODULES
from tests.fixtures.spm import worker_versions_document

SELECTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "baseline",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
ANNUAL_URL = "/us/economy/1/over/2?region=us&time_period=2026&version=1.0.0"
BUDGET_WINDOW_URL = (
    "/us/economy/1/over/2/budget-window"
    "?region=us&start_year=2026&window_size=2&version=1.0.0"
)
GATEWAY_AUTH_ENV_VARS = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
)


class SimulationService:
    """A MockTransport handler for the simulation service's read-only routes.

    A path in ``broken_paths`` raises httpx.ReadError on every request, as a
    connection that breaks after the request is sent does.
    """

    def __init__(self, *, broken_paths=(), versions=None):
        self.broken_paths = set(broken_paths)
        self.versions = versions if versions is not None else {}
        self.requests = []

    def handle(self, request):
        path = request.url.path
        self.requests.append((request.method, path))
        if path in self.broken_paths:
            msg = "[Errno 32] Broken pipe"
            raise httpx.ReadError(msg, request=request)
        if path == "/versions":
            return httpx.Response(200, json=self.versions)
        if path == "/versions/policyengine":
            return httpx.Response(200, json=self.versions.get("policyengine", {}))
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def economy_client(monkeypatch):
    """Return a factory for a Flask test client over a scripted simulation service."""
    for name in GATEWAY_AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://simulation.example.test")
    monkeypatch.setattr(simulation_request_diagnostics, "get_runtime", Mock)
    for module_name in ECONOMY_SERVICE_LOGGER_MODULES:
        monkeypatch.setattr(f"{module_name}.logger", Mock())

    def build(service, *, selection):
        monkeypatch.setattr(worker_spm, "normalize_spm_selection", lambda *_: selection)
        gateway = SimulationEntrypointClient(
            transport=SimulationEntrypointTransport(
                open_transport=lambda: httpx.MockTransport(service.handle)
            )
        )
        policies = Mock()
        policies.get_policy_json.return_value = {}
        cache = ReformImpactCache(
            InMemoryCacheBackend(), CacheNamespace("test", "connection-failures")
        )
        monkeypatch.setattr(
            economy_routes,
            "economy_service",
            EconomyService(
                policy_service_=policies,
                reform_impacts_service_=ReformImpactsService(cache),
                simulation_entrypoint_=gateway,
            ),
        )
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(economy_routes.economy_bp)
        return app.test_client()

    return build


def unreachable_body(path):
    return {
        "status": "error",
        "message": f"No response from the simulation service to GET {path}",
        "result": None,
        "retry_after_seconds": None,
    }


def test_runtime_bundle_request_that_breaks_twice_gives_502(economy_client):
    service = SimulationService(broken_paths={"/versions/policyengine"})
    client = economy_client(service, selection=None)

    response = client.get(ANNUAL_URL)

    assert response.status_code == 502
    assert response.json == unreachable_body("/versions/policyengine")
    # Sent once and retried once; no job was submitted.
    assert service.requests == [("GET", "/versions/policyengine")] * 2


@pytest.mark.parametrize("url", [ANNUAL_URL, BUDGET_WINDOW_URL])
def test_versions_request_that_breaks_twice_gives_502_not_400(economy_client, url):
    service = SimulationService(broken_paths={"/versions"})
    client = economy_client(service, selection=SELECTION)

    response = client.get(url)

    assert response.status_code == 502
    assert response.json == unreachable_body("/versions")
    assert service.requests == [("GET", "/versions")] * 2


def test_spm_validation_failure_keeps_its_400(economy_client):
    # The worker answers, but certifies no SPM capability for its bundle.
    versions = worker_versions_document()
    versions["spm_capabilities"] = {}
    service = SimulationService(versions=versions)
    client = economy_client(service, selection=SELECTION)

    response = client.get(ANNUAL_URL)

    assert response.status_code == 400
    [error] = response.json["errors"]
    assert error["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
    assert service.requests == [("GET", "/versions")]


def test_spm_capability_error_status_keeps_its_400(economy_client):
    # An error status is an answer, not a broken connection: still a 400.
    service = SimulationService()
    service.handle = lambda request: httpx.Response(503, json={"detail": "down"})
    client = economy_client(service, selection=SELECTION)

    response = client.get(ANNUAL_URL)

    assert response.status_code == 400
    [error] = response.json["errors"]
    assert error["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
