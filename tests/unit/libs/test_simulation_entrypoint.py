"""
Unit tests for SimulationAPIModal class.

Tests the selectable simulation API HTTP client functionality including
job submission, status polling, and error handling.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from flask import Flask, g

sys.modules.setdefault(
    "policyengine_api.gcp_logging",
    SimpleNamespace(logger=MagicMock()),
)
os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.constants import (  # noqa: E402
    MODAL_EXECUTION_STATUS_COMPLETE,
    MODAL_EXECUTION_STATUS_FAILED,
    MODAL_EXECUTION_STATUS_RUNNING,
    MODAL_EXECUTION_STATUS_SUBMITTED,
)
from policyengine_api.libs.simulation_entrypoint import (  # noqa: E402
    ModalBudgetWindowBatchExecution,
    ModalSimulationExecution,
    SimulationAPIModal,
    SimulationEntrypointClient,
    resolve_simulation_entrypoint_url,
)
from policyengine_api.request_context import (  # noqa: E402
    REQUEST_ID_HEADER,
    _asgi_request_id,
)

from tests.fixtures.libs.simulation_entrypoint import (  # noqa: E402
    MOCK_BATCH_JOB_ID,
    MOCK_BATCH_POLL_RESPONSE_COMPLETE,
    MOCK_BATCH_POLL_RESPONSE_FAILED,
    MOCK_BATCH_POLL_RESPONSE_RUNNING,
    MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS,
    MOCK_HEALTH_RESPONSE,
    MOCK_MODAL_BASE_URL,
    MOCK_MODAL_JOB_ID,
    MOCK_POLICYENGINE_BUNDLE,
    MOCK_POLL_RESPONSE_COMPLETE,
    MOCK_POLL_RESPONSE_FAILED,
    MOCK_POLL_RESPONSE_RUNNING,
    MOCK_RESOLVED_APP_NAME,
    MOCK_RUN_ID,
    MOCK_SIMULATION_PAYLOAD,
    MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY,
    MOCK_SIMULATION_RESULT,
    MOCK_SUBMIT_RESPONSE_SUCCESS,
    create_mock_httpx_response,
)

pytest_plugins = ("tests.fixtures.libs.simulation_entrypoint",)

GATEWAY_AUTH_TEST_ENV_VARS = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
)

ENTRYPOINT_TEST_ENV_VARS = (
    "SIM_ENTRYPOINT",
    "OLD_SIMULATION_GATEWAY_URL",
    "SIMULATION_ENTRYPOINT_URL",
)


class RequestRecordingHTTPXClient:
    """Minimal HTTPX-compatible client that executes request event hooks."""

    instances = []

    def __init__(self, *, event_hooks=None, **kwargs):
        self.event_hooks = event_hooks or {}
        self.requests = []
        type(self).instances.append(self)

    def _response(self, method, url, json=None):
        request = httpx.Request(method, url, json=json)
        for hook in self.event_hooks.get("request", []):
            hook(request)
        self.requests.append(request)

        path = request.url.path
        if method == "POST" and path.endswith("/comparison"):
            payload = MOCK_SUBMIT_RESPONSE_SUCCESS
            status_code = 202
        elif method == "POST" and path.endswith("/budget-window"):
            payload = MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS
            status_code = 202
        elif "/budget-window-jobs/" in path:
            payload = MOCK_BATCH_POLL_RESPONSE_RUNNING
            status_code = 202
        elif "/jobs/" in path:
            payload = MOCK_POLL_RESPONSE_RUNNING
            status_code = 202
        elif "/versions/" in path:
            payload = {
                "latest": "1.459.0",
                "1.459.0": MOCK_RESOLVED_APP_NAME,
            }
            status_code = 200
        else:
            payload = MOCK_HEALTH_RESPONSE
            status_code = 200

        return httpx.Response(status_code, request=request, json=payload)

    def post(self, url, json=None):
        return self._response("POST", url, json=json)

    def get(self, url):
        return self._response("GET", url)


@pytest.fixture(autouse=True)
def clear_gateway_auth_env(monkeypatch):
    """Isolate unit tests from gateway-auth env injected during Docker builds."""
    for key in GATEWAY_AUTH_TEST_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    for key in ENTRYPOINT_TEST_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", MOCK_MODAL_BASE_URL)


def test_generic_client_name_retains_old_class_alias():
    assert SimulationAPIModal is SimulationEntrypointClient


def test_legacy_simulation_api_modules_export_entrypoint_aliases():
    from policyengine_api.libs import (
        simulation_api,
        simulation_api_modal,
        simulation_entrypoint,
    )

    assert simulation_api.SimulationAPIClient is SimulationEntrypointClient
    assert simulation_api_modal.SimulationAPIClient is SimulationEntrypointClient
    assert (
        simulation_api.simulation_api
        is simulation_entrypoint.simulation_entrypoint
        is simulation_api_modal.simulation_api_modal
    )


def test_direct_entrypoint_prefers_explicit_old_gateway_url(monkeypatch):
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://old.example.test/")
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", "https://new.example.test")

    assert resolve_simulation_entrypoint_url("old_gateway_direct") == (
        "https://old.example.test"
    )


def test_cloud_run_entrypoint_uses_entrypoint_url(monkeypatch):
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://old.example.test")
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", "https://new.example.test/")

    assert resolve_simulation_entrypoint_url("cloud_run_simulation_entrypoint") == (
        "https://new.example.test"
    )


def test_cloud_run_entrypoint_requires_entrypoint_url(monkeypatch):
    monkeypatch.delenv("SIMULATION_ENTRYPOINT_URL", raising=False)

    with pytest.raises(ValueError, match="SIMULATION_ENTRYPOINT_URL is required"):
        resolve_simulation_entrypoint_url("cloud_run_simulation_entrypoint")


def test_direct_entrypoint_requires_old_gateway_url(monkeypatch):
    monkeypatch.delenv("OLD_SIMULATION_GATEWAY_URL", raising=False)

    with pytest.raises(ValueError, match="OLD_SIMULATION_GATEWAY_URL is required"):
        resolve_simulation_entrypoint_url("old_gateway_direct")


@pytest.mark.parametrize(
    ("entrypoint", "env_name"),
    [
        ("old_gateway_direct", "OLD_SIMULATION_GATEWAY_URL"),
        ("cloud_run_simulation_entrypoint", "SIMULATION_ENTRYPOINT_URL"),
    ],
)
def test_selected_entrypoint_rejects_invalid_url(monkeypatch, entrypoint, env_name):
    monkeypatch.setenv(env_name, "not-an-absolute-url")

    with pytest.raises(ValueError, match="absolute HTTP"):
        resolve_simulation_entrypoint_url(entrypoint)


class TestModalSimulationExecution:
    """Tests for the ModalSimulationExecution dataclass."""

    class TestNameProperty:
        def test__given_job_id__then_name_returns_job_id(self):
            # Given
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_SUBMITTED,
            )

            # When
            name = execution.name

            # Then
            assert name == MOCK_MODAL_JOB_ID

    class TestAttributes:
        def test__given_complete_execution__then_all_attributes_accessible(
            self,
        ):
            # Given
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_COMPLETE,
                result=MOCK_SIMULATION_RESULT,
                error=None,
            )

            # Then
            assert execution.job_id == MOCK_MODAL_JOB_ID
            assert execution.status == MODAL_EXECUTION_STATUS_COMPLETE
            assert execution.result == MOCK_SIMULATION_RESULT
            assert execution.error is None

        def test__given_failed_execution__then_error_attribute_populated(self):
            # Given
            error_message = "Simulation timed out"
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_FAILED,
                result=None,
                error=error_message,
            )

            # Then
            assert execution.status == MODAL_EXECUTION_STATUS_FAILED
            assert execution.error == error_message
            assert execution.result is None


class TestModalBudgetWindowBatchExecution:
    """Tests for the ModalBudgetWindowBatchExecution dataclass."""

    def test__given_batch_job_id__then_name_returns_batch_job_id(self):
        execution = ModalBudgetWindowBatchExecution(
            batch_job_id=MOCK_BATCH_JOB_ID,
            status=MODAL_EXECUTION_STATUS_SUBMITTED,
        )

        assert execution.name == MOCK_BATCH_JOB_ID


class TestSimulationAPIModal:
    """Tests for the SimulationAPIModal class."""

    class TestInit:
        def test__given_env_var_set__then_uses_env_url(self, mock_httpx_client):
            # Given
            with patch.dict(
                "os.environ",
                {
                    "SIM_ENTRYPOINT": "cloud_run_simulation_entrypoint",
                    "SIMULATION_ENTRYPOINT_URL": MOCK_MODAL_BASE_URL,
                },
            ):
                # When
                api = SimulationAPIModal()

                # Then
                assert api.base_url == MOCK_MODAL_BASE_URL

        def test__given_selected_url_not_set__then_fails_startup(
            self, mock_httpx_client
        ):
            # Given
            with patch.dict("os.environ", {}, clear=False):
                import os

                os.environ["SIM_ENTRYPOINT"] = "old_gateway_direct"
                os.environ.pop("OLD_SIMULATION_GATEWAY_URL", None)

                # When / Then
                with pytest.raises(
                    ValueError,
                    match="OLD_SIMULATION_GATEWAY_URL is required",
                ):
                    SimulationAPIModal()

        def test__given_gateway_auth_env_vars__then_attaches_bearer_auth(
            self, mock_httpx_client, monkeypatch
        ):
            from policyengine_api.libs.gateway_auth import GatewayBearerAuth
            from policyengine_api.libs.simulation_entrypoint import httpx as modal_httpx

            monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://tenant.auth0.com")
            monkeypatch.setenv("GATEWAY_AUTH_AUDIENCE", "https://sim-gateway")
            monkeypatch.setenv("GATEWAY_AUTH_CLIENT_ID", "id")
            monkeypatch.setenv("GATEWAY_AUTH_CLIENT_SECRET", "secret")

            SimulationAPIModal()

            _, kwargs = modal_httpx.Client.call_args
            assert isinstance(kwargs.get("auth"), GatewayBearerAuth)

        def test__given_missing_gateway_auth_env_vars__then_no_auth_attached(
            self, mock_httpx_client, monkeypatch, mock_modal_logger
        ):
            from policyengine_api.libs.simulation_entrypoint import httpx as modal_httpx

            for key in (
                "GATEWAY_AUTH_ISSUER",
                "GATEWAY_AUTH_AUDIENCE",
                "GATEWAY_AUTH_CLIENT_ID",
                "GATEWAY_AUTH_CLIENT_SECRET",
            ):
                monkeypatch.delenv(key, raising=False)
            monkeypatch.delenv("GATEWAY_AUTH_REQUIRED", raising=False)

            SimulationAPIModal()

            _, kwargs = modal_httpx.Client.call_args
            assert kwargs.get("auth") is None

        def test__given_missing_gateway_auth_env_vars_when_required__then_raises(
            self, mock_httpx_client, monkeypatch
        ):
            from policyengine_api.libs.gateway_auth import GatewayAuthError

            for key in (
                "GATEWAY_AUTH_ISSUER",
                "GATEWAY_AUTH_AUDIENCE",
                "GATEWAY_AUTH_CLIENT_ID",
                "GATEWAY_AUTH_CLIENT_SECRET",
            ):
                monkeypatch.delenv(key, raising=False)
            monkeypatch.setenv("GATEWAY_AUTH_REQUIRED", "1")

            with pytest.raises(GatewayAuthError, match="Gateway auth is required"):
                SimulationAPIModal()

        def test__given_partial_gateway_auth_env_vars__then_raises(
            self, mock_httpx_client, monkeypatch
        ):
            from policyengine_api.libs.gateway_auth import GatewayAuthError

            monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://tenant.auth0.com")
            monkeypatch.setenv("GATEWAY_AUTH_AUDIENCE", "aud")
            monkeypatch.delenv("GATEWAY_AUTH_CLIENT_ID", raising=False)
            monkeypatch.delenv("GATEWAY_AUTH_CLIENT_SECRET", raising=False)

            with pytest.raises(GatewayAuthError):
                SimulationAPIModal()

        def test__given_client_initialized__then_installs_one_request_id_hook(
            self, mock_httpx_client
        ):
            from policyengine_api.libs.simulation_entrypoint import httpx as modal_httpx

            SimulationAPIModal()

            _, kwargs = modal_httpx.Client.call_args
            assert list(kwargs["event_hooks"]) == ["request"]
            assert len(kwargs["event_hooks"]["request"]) == 1

        def test__given_flask_request__then_hook_uses_current_request_id(
            self, mock_httpx_client
        ):
            from policyengine_api.libs.simulation_entrypoint import httpx as modal_httpx

            SimulationAPIModal()
            hook = modal_httpx.Client.call_args.kwargs["event_hooks"]["request"][0]
            request = httpx.Request("GET", MOCK_MODAL_BASE_URL)
            app = Flask("request-id-test")

            token = _asgi_request_id.set("asgi-request-id")
            try:
                with app.test_request_context():
                    g.request_id = "flask-request-id"
                    hook(request)
            finally:
                _asgi_request_id.reset(token)

            assert request.headers[REQUEST_ID_HEADER] == "flask-request-id"

        def test__given_asgi_request__then_hook_uses_current_request_id(
            self, mock_httpx_client
        ):
            from policyengine_api.libs.simulation_entrypoint import httpx as modal_httpx

            SimulationAPIModal()
            hook = modal_httpx.Client.call_args.kwargs["event_hooks"]["request"][0]
            request = httpx.Request("GET", MOCK_MODAL_BASE_URL)
            token = _asgi_request_id.set("asgi-request-id")
            try:
                hook(request)
            finally:
                _asgi_request_id.reset(token)

            assert request.headers[REQUEST_ID_HEADER] == "asgi-request-id"

        def test__given_no_request_context__then_hook_omits_request_id(
            self, monkeypatch, mock_modal_logger
        ):
            from policyengine_api.libs import simulation_entrypoint as module

            RequestRecordingHTTPXClient.instances.clear()
            monkeypatch.setattr(
                module.httpx,
                "Client",
                RequestRecordingHTTPXClient,
            )
            api = SimulationAPIModal()

            assert api.health_check() is True
            request = RequestRecordingHTTPXClient.instances[-1].requests[-1]
            assert REQUEST_ID_HEADER not in request.headers

        @pytest.mark.parametrize(
            ("entrypoint", "url_env_name"),
            [
                ("old_gateway_direct", "OLD_SIMULATION_GATEWAY_URL"),
                (
                    "cloud_run_simulation_entrypoint",
                    "SIMULATION_ENTRYPOINT_URL",
                ),
            ],
        )
        def test__given_request_context__then_all_calls_forward_request_id(
            self,
            monkeypatch,
            mock_modal_logger,
            entrypoint,
            url_env_name,
        ):
            from policyengine_api.libs import simulation_entrypoint as module

            RequestRecordingHTTPXClient.instances.clear()
            monkeypatch.setenv("SIM_ENTRYPOINT", entrypoint)
            monkeypatch.setenv(url_env_name, MOCK_MODAL_BASE_URL)
            monkeypatch.setattr(
                module.httpx,
                "Client",
                RequestRecordingHTTPXClient,
            )
            api = SimulationAPIModal()
            app = Flask("request-id-all-calls")

            with app.test_request_context():
                g.request_id = "flask-request-id"
                api.run(MOCK_SIMULATION_PAYLOAD)
                api.run_budget_window_batch(MOCK_SIMULATION_PAYLOAD)
                api.get_execution_by_id(MOCK_MODAL_JOB_ID)
                api.get_budget_window_batch_by_id(MOCK_BATCH_JOB_ID)
                api.resolve_app_name("us", "1.459.0")
                assert api.health_check() is True

            requests = RequestRecordingHTTPXClient.instances[-1].requests
            assert {request.url.path for request in requests} == {
                "/simulate/economy/comparison",
                "/simulate/economy/budget-window",
                f"/jobs/{MOCK_MODAL_JOB_ID}",
                f"/budget-window-jobs/{MOCK_BATCH_JOB_ID}",
                "/versions/us",
                "/health",
            }
            assert all(
                request.headers[REQUEST_ID_HEADER] == "flask-request-id"
                for request in requests
            )

    class TestRun:
        def test__given_valid_payload__then_returns_execution_with_job_id(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
            )
            api = SimulationAPIModal()

            # When
            execution = api.run(MOCK_SIMULATION_PAYLOAD)

            # Then
            assert execution.job_id == MOCK_MODAL_JOB_ID
            assert execution.run_id == MOCK_RUN_ID
            assert execution.status == MODAL_EXECUTION_STATUS_SUBMITTED
            assert execution.policyengine_bundle == MOCK_POLICYENGINE_BUNDLE
            assert execution.resolved_app_name == MOCK_RESOLVED_APP_NAME
            mock_httpx_client.post.assert_called_once()

        def test__given_valid_payload__then_posts_to_correct_endpoint(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
            )
            api = SimulationAPIModal()

            # When
            api.run(MOCK_SIMULATION_PAYLOAD)

            # Then
            call_args = mock_httpx_client.post.call_args
            assert "/simulate/economy/comparison" in call_args[0][0]
            assert call_args[1]["json"] == MOCK_SIMULATION_PAYLOAD

        def test__given_telemetry_payload__then_preserves_it_in_post_body(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
            )
            api = SimulationAPIModal()

            api.run(MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY)

            call_args = mock_httpx_client.post.call_args
            assert call_args[1]["json"]["_telemetry"]["run_id"] == MOCK_RUN_ID

        def test__given_model_and_data_versions__then_translates_payload_for_modal(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
            )
            payload = {
                **MOCK_SIMULATION_PAYLOAD,
                "model_version": "1.459.0",
                "policyengine_version": "4.18.3",
                "data_version": "1.77.0",
            }
            api = SimulationAPIModal()

            api.run(payload)

            posted_payload = mock_httpx_client.post.call_args.kwargs["json"]
            assert posted_payload["version"] == "1.459.0"
            assert posted_payload["policyengine_version"] == "4.18.3"
            assert "model_version" not in posted_payload
            assert "data_version" not in posted_payload

        def test__given_api_v1_default_bundle_payload__then_posts_gateway_contract_body(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
            )
            payload = {
                "country": "us",
                "scope": "macro",
                "reform": {"gov.irs.income.bracket.rates.2": {"2026-01-01": 0.24}},
                "baseline": {},
                "time_period": "2026",
                "region": "state/ca",
                "data": None,
                "include_cliffs": False,
                "model_version": "1.729.0",
                "policyengine_version": "4.18.3",
                "data_version": None,
                "_metadata": {
                    "process_id": "job_20260629120000_1234",
                    "model_version": "1.729.0",
                    "policyengine_version": "4.18.3",
                    "data_version": None,
                    "dataset": "default",
                    "resolved_app_name": "policyengine-simulation-py4-18-3",
                },
                "_telemetry": {
                    "run_id": "run_20260629120000_1234",
                    "process_id": "job_20260629120000_1234",
                    "capture_mode": "disabled",
                },
            }
            expected_gateway_keys = {
                "country",
                "scope",
                "reform",
                "baseline",
                "time_period",
                "region",
                "include_cliffs",
                "version",
                "policyengine_version",
                "_metadata",
                "_telemetry",
            }
            api = SimulationAPIModal()

            api.run(payload)

            posted_payload = mock_httpx_client.post.call_args.kwargs["json"]
            assert set(posted_payload) == expected_gateway_keys
            assert posted_payload["version"] == "1.729.0"
            assert posted_payload["policyengine_version"] == "4.18.3"
            assert posted_payload["region"] == "state/ca"
            assert posted_payload["_metadata"]["dataset"] == "default"
            assert "data" not in posted_payload
            assert "model_version" not in posted_payload
            assert "data_version" not in posted_payload

        def test__given_http_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_response = create_mock_httpx_response(
                status_code=400,
                json_data={"error": "Invalid request"},
            )
            mock_httpx_client.post.return_value = mock_response
            api = SimulationAPIModal()

            # When/Then
            with pytest.raises(httpx.HTTPStatusError):
                api.run(MOCK_SIMULATION_PAYLOAD)

        def test__given_network_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.post.side_effect = httpx.RequestError("Connection failed")
            api = SimulationAPIModal()

            # When/Then
            with pytest.raises(httpx.RequestError):
                api.run(MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY)

            log_payload = mock_modal_logger.log_struct.call_args.args[0]
            assert "Simulation entrypoint request error" in log_payload["message"]
            assert log_payload["run_id"] == MOCK_RUN_ID

    class TestResolveAppName:
        def test__given_country_and_version__then_returns_registered_app(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,
                json_data={
                    "latest": "1.459.0",
                    "1.459.0": MOCK_RESOLVED_APP_NAME,
                },
            )
            api = SimulationAPIModal()

            app_name, resolved_version = api.resolve_app_name("us", "1.459.0")

            assert app_name == MOCK_RESOLVED_APP_NAME
            assert resolved_version == "1.459.0"

        def test__given_unknown_version__then_raises_value_error(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,
                json_data={
                    "latest": "1.459.0",
                    "1.459.0": MOCK_RESOLVED_APP_NAME,
                },
            )
            api = SimulationAPIModal()

            with pytest.raises(
                ValueError, match="Unknown version 9.9.9 for country us"
            ):
                api.resolve_app_name("us", "9.9.9")

        def test__given_policyengine_version__then_returns_registered_bundle_app(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,
                json_data={
                    "latest": "4.18.3",
                    "4.18.3": MOCK_RESOLVED_APP_NAME,
                },
            )
            api = SimulationAPIModal()

            app_name, resolved_version = api.resolve_app_name(
                "us",
                "1.729.0",
                policyengine_version="4.18.3",
            )

            assert app_name == MOCK_RESOLVED_APP_NAME
            assert resolved_version == "1.729.0"
            mock_httpx_client.get.assert_called_once_with(
                f"{api.base_url}/versions/policyengine"
            )

    class TestRunBudgetWindowBatch:
        def test__given_valid_payload__then_returns_batch_execution(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS,
            )
            api = SimulationAPIModal()

            execution = api.run_budget_window_batch(MOCK_SIMULATION_PAYLOAD)

            assert execution.batch_job_id == MOCK_BATCH_JOB_ID
            assert execution.status == MODAL_EXECUTION_STATUS_SUBMITTED
            call_args = mock_httpx_client.post.call_args
            assert "/simulate/economy/budget-window" in call_args[0][0]

        def test__given_model_and_data_versions__then_translates_payload_for_modal(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.post.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS,
            )
            payload = {
                **MOCK_SIMULATION_PAYLOAD,
                "model_version": "1.459.0",
                "policyengine_version": "4.18.3",
                "data_version": "1.77.0",
            }
            api = SimulationAPIModal()

            api.run_budget_window_batch(payload)

            posted_payload = mock_httpx_client.post.call_args.kwargs["json"]
            assert posted_payload["version"] == "1.459.0"
            assert posted_payload["policyengine_version"] == "4.18.3"
            assert "model_version" not in posted_payload
            assert "data_version" not in posted_payload

        def test__given_http_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_response = create_mock_httpx_response(
                status_code=400,
                json_data={"error": "Invalid request"},
            )
            mock_httpx_client.post.return_value = mock_response
            api = SimulationAPIModal()

            with pytest.raises(httpx.HTTPStatusError):
                api.run_budget_window_batch(MOCK_SIMULATION_PAYLOAD)

        def test__given_network_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.post.side_effect = httpx.RequestError("Connection failed")
            api = SimulationAPIModal()

            with pytest.raises(httpx.RequestError):
                api.run_budget_window_batch(MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY)

            log_payload = mock_modal_logger.log_struct.call_args.args[0]
            assert log_payload["run_id"] == MOCK_RUN_ID

    class TestGetExecutionById:
        def test__given_running_job__then_returns_running_status(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_POLL_RESPONSE_RUNNING,
            )
            api = SimulationAPIModal()

            # When
            execution = api.get_execution_by_id(MOCK_MODAL_JOB_ID)

            # Then
            assert execution.job_id == MOCK_MODAL_JOB_ID
            assert execution.status == MODAL_EXECUTION_STATUS_RUNNING
            assert execution.result is None

        def test__given_complete_job__then_returns_result(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,
                json_data=MOCK_POLL_RESPONSE_COMPLETE,
            )
            api = SimulationAPIModal()

            # When
            execution = api.get_execution_by_id(MOCK_MODAL_JOB_ID)

            # Then
            assert execution.status == MODAL_EXECUTION_STATUS_COMPLETE
            assert execution.result == MOCK_SIMULATION_RESULT
            assert execution.policyengine_bundle == MOCK_POLICYENGINE_BUNDLE
            assert execution.resolved_app_name == MOCK_RESOLVED_APP_NAME

        def test__given_failed_job__then_returns_error(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,  # Failed jobs still return 200 with error in body
                json_data=MOCK_POLL_RESPONSE_FAILED,
            )
            api = SimulationAPIModal()

            # When
            execution = api.get_execution_by_id(MOCK_MODAL_JOB_ID)

            # Then
            assert execution.status == MODAL_EXECUTION_STATUS_FAILED
            assert execution.error == "Simulation timed out"

        def test__given_job_id__then_polls_correct_endpoint(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            # Given
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_POLL_RESPONSE_RUNNING,
            )
            api = SimulationAPIModal()

            # When
            api.get_execution_by_id(MOCK_MODAL_JOB_ID)

            # Then
            call_args = mock_httpx_client.get.call_args
            assert f"/jobs/{MOCK_MODAL_JOB_ID}" in call_args[0][0]

        def test__given_unexpected_http_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=403,
                json_data={"detail": "Forbidden"},
            )
            api = SimulationAPIModal()

            with pytest.raises(httpx.HTTPStatusError):
                api.get_execution_by_id(MOCK_MODAL_JOB_ID)

        def test__given_network_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.side_effect = httpx.RequestError("Connection failed")
            api = SimulationAPIModal()

            with pytest.raises(httpx.RequestError):
                api.get_execution_by_id(MOCK_MODAL_JOB_ID)

            log_payload = mock_modal_logger.log_struct.call_args.args[0]
            assert MOCK_MODAL_JOB_ID in log_payload["message"]

    class TestGetBudgetWindowBatchById:
        def test__given_running_batch__then_returns_running_status(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=202,
                json_data=MOCK_BATCH_POLL_RESPONSE_RUNNING,
            )
            api = SimulationAPIModal()

            execution = api.get_budget_window_batch_by_id(MOCK_BATCH_JOB_ID)

            assert execution.batch_job_id == MOCK_BATCH_JOB_ID
            assert execution.status == MODAL_EXECUTION_STATUS_RUNNING
            assert execution.completed_years == ["2026"]
            assert execution.running_years == ["2027"]
            assert execution.queued_years == ["2028"]

        def test__given_complete_batch__then_returns_result(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,
                json_data=MOCK_BATCH_POLL_RESPONSE_COMPLETE,
            )
            api = SimulationAPIModal()

            execution = api.get_budget_window_batch_by_id(MOCK_BATCH_JOB_ID)

            assert execution.status == MODAL_EXECUTION_STATUS_COMPLETE
            assert execution.result == MOCK_BATCH_POLL_RESPONSE_COMPLETE["result"]

        def test__given_failed_batch__then_returns_error(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=500,
                json_data=MOCK_BATCH_POLL_RESPONSE_FAILED,
            )
            api = SimulationAPIModal()

            execution = api.get_budget_window_batch_by_id(MOCK_BATCH_JOB_ID)

            assert execution.status == MODAL_EXECUTION_STATUS_FAILED
            assert execution.failed_years == ["2027"]
            assert execution.error == "Budget window failed"

        def test__given_unexpected_http_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=404,
                json_data={"detail": "Budget-window job not found"},
            )
            api = SimulationAPIModal()

            with pytest.raises(httpx.HTTPStatusError):
                api.get_budget_window_batch_by_id(MOCK_BATCH_JOB_ID)

        def test__given_network_error__then_raises_exception(
            self,
            mock_httpx_client,
            mock_modal_logger,
        ):
            mock_httpx_client.get.side_effect = httpx.RequestError("Connection failed")
            api = SimulationAPIModal()

            with pytest.raises(httpx.RequestError):
                api.get_budget_window_batch_by_id(MOCK_BATCH_JOB_ID)

            log_payload = mock_modal_logger.log_struct.call_args.args[0]
            assert MOCK_BATCH_JOB_ID in log_payload["message"]

    class TestGetExecutionId:
        def test__given_execution__then_returns_job_id(self, mock_httpx_client):
            # Given
            api = SimulationAPIModal()
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_SUBMITTED,
            )

            # When
            execution_id = api.get_execution_id(execution)

            # Then
            assert execution_id == MOCK_MODAL_JOB_ID

    class TestGetExecutionStatus:
        def test__given_execution__then_returns_status_string(self, mock_httpx_client):
            # Given
            api = SimulationAPIModal()
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_RUNNING,
            )

            # When
            status = api.get_execution_status(execution)

            # Then
            assert status == MODAL_EXECUTION_STATUS_RUNNING

    class TestGetExecutionResult:
        def test__given_complete_execution__then_returns_result(
            self, mock_httpx_client
        ):
            # Given
            api = SimulationAPIModal()
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_COMPLETE,
                result=MOCK_SIMULATION_RESULT,
            )

            # When
            result = api.get_execution_result(execution)

            # Then
            assert result == MOCK_SIMULATION_RESULT

        def test__given_incomplete_execution__then_returns_none(
            self, mock_httpx_client
        ):
            # Given
            api = SimulationAPIModal()
            execution = ModalSimulationExecution(
                job_id=MOCK_MODAL_JOB_ID,
                status=MODAL_EXECUTION_STATUS_RUNNING,
                result=None,
            )

            # When
            result = api.get_execution_result(execution)

            # Then
            assert result is None

    class TestHealthCheck:
        def test__given_healthy_api__then_returns_true(
            self, mock_httpx_client, mock_modal_logger
        ):
            # Given
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=200,
                json_data=MOCK_HEALTH_RESPONSE,
            )
            api = SimulationAPIModal()

            # When
            is_healthy = api.health_check()

            # Then
            assert is_healthy is True

        def test__given_unhealthy_api__then_returns_false(
            self, mock_httpx_client, mock_modal_logger
        ):
            # Given
            mock_httpx_client.get.return_value = create_mock_httpx_response(
                status_code=503,
                json_data={"status": "unhealthy"},
            )
            api = SimulationAPIModal()

            # When
            is_healthy = api.health_check()

            # Then
            assert is_healthy is False

        def test__given_network_error__then_returns_false(
            self, mock_httpx_client, mock_modal_logger
        ):
            # Given
            mock_httpx_client.get.side_effect = httpx.RequestError("Connection failed")
            api = SimulationAPIModal()

            # When
            is_healthy = api.health_check()

            # Then
            assert is_healthy is False
