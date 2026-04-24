"""
Unit tests for SimulationAPIModal class.

Tests the Modal simulation API HTTP client functionality including
job submission, status polling, and error handling.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock

import httpx
import pytest

sys.modules.setdefault(
    "policyengine_api.gcp_logging",
    SimpleNamespace(logger=MagicMock()),
)
os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.libs.simulation_api_modal import (  # noqa: E402
    ModalSimulationExecution,
    SimulationAPIModal,
)
from policyengine_api.constants import (  # noqa: E402
    MODAL_EXECUTION_STATUS_COMPLETE,
    MODAL_EXECUTION_STATUS_FAILED,
    MODAL_EXECUTION_STATUS_RUNNING,
    MODAL_EXECUTION_STATUS_SUBMITTED,
)
from tests.fixtures.libs.simulation_api_modal import (  # noqa: E402
    MOCK_MODAL_JOB_ID,
    MOCK_MODAL_BASE_URL,
    MOCK_SIMULATION_PAYLOAD,
    MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY,
    MOCK_RUN_ID,
    MOCK_SIMULATION_RESULT,
    MOCK_POLICYENGINE_BUNDLE,
    MOCK_RESOLVED_APP_NAME,
    MOCK_SUBMIT_RESPONSE_SUCCESS,
    MOCK_POLL_RESPONSE_RUNNING,
    MOCK_POLL_RESPONSE_COMPLETE,
    MOCK_POLL_RESPONSE_FAILED,
    MOCK_HEALTH_RESPONSE,
    create_mock_httpx_response,
)

pytest_plugins = ("tests.fixtures.libs.simulation_api_modal",)


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


class TestSimulationAPIModal:
    """Tests for the SimulationAPIModal class."""

    class TestInit:
        def test__given_env_var_set__then_uses_env_url(self, mock_httpx_client):
            # Given
            with patch.dict(
                "os.environ",
                {"SIMULATION_API_URL": MOCK_MODAL_BASE_URL},
            ):
                # When
                api = SimulationAPIModal()

                # Then
                assert api.base_url == MOCK_MODAL_BASE_URL

        def test__given_env_var_not_set__then_uses_default_url(self, mock_httpx_client):
            # Given
            with patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("SIMULATION_API_URL", None)

                # When
                api = SimulationAPIModal()

                # Then
                assert "policyengine-simulation-gateway" in api.base_url
                assert "modal.run" in api.base_url

        def test__given_gateway_auth_env_vars__then_attaches_bearer_auth(
            self, mock_httpx_client, monkeypatch
        ):
            from policyengine_api.libs.gateway_auth import GatewayBearerAuth
            from policyengine_api.libs.simulation_api_modal import httpx as modal_httpx

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
            from policyengine_api.libs.simulation_api_modal import httpx as modal_httpx

            for key in (
                "GATEWAY_AUTH_ISSUER",
                "GATEWAY_AUTH_AUDIENCE",
                "GATEWAY_AUTH_CLIENT_ID",
                "GATEWAY_AUTH_CLIENT_SECRET",
            ):
                monkeypatch.delenv(key, raising=False)
            monkeypatch.setenv("FLASK_DEBUG", "1")

            SimulationAPIModal()

            _, kwargs = modal_httpx.Client.call_args
            assert kwargs.get("auth") is None

        def test__given_missing_gateway_auth_env_vars_outside_debug__then_raises(
            self, mock_httpx_client, monkeypatch
        ):
            from policyengine_api.libs.gateway_auth import GatewayAuthError

            for key in (
                "GATEWAY_AUTH_ISSUER",
                "GATEWAY_AUTH_AUDIENCE",
                "GATEWAY_AUTH_CLIENT_ID",
                "GATEWAY_AUTH_CLIENT_SECRET",
                "FLASK_DEBUG",
            ):
                monkeypatch.delenv(key, raising=False)

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
                api.run(MOCK_SIMULATION_PAYLOAD)

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
