"""Simulation execution states mapped to annual economic impact results."""

from unittest.mock import MagicMock

import httpx
import pytest

from policyengine_api.libs.simulation_entrypoint import (
    ModalSimulationExecution,
    SimulationRunProgress,
)
from policyengine_api.services.economy_service import (
    EconomicImpactSetupOptions,
    EconomyService,
    ImpactStatus,
)
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATA_VERSION,
    MOCK_MODEL_VERSION,
    MOCK_OBSERVABILITY_ID,
    MOCK_OPTIONS,
    MOCK_OPTIONS_HASH,
    MOCK_POLICY_ID,
    MOCK_POLICYENGINE_VERSION,
    MOCK_REFORM_IMPACT_DATA,
    MOCK_REGION,
    MOCK_RESOLVED_DATASET,
    MOCK_SUBMISSION_CLAIM_ID,
    MOCK_TIME_PERIOD,
    create_mock_reform_impact,
)
from tests.fixtures.services.economy_service_helpers import (
    make_http_status_error,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")


class TestEconomyService:
    class TestHandleExecutionState:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.fixture
        def setup_options(self):
            return EconomicImpactSetupOptions(
                submission_claim_id=MOCK_SUBMISSION_CLAIM_ID,
                observability_id=MOCK_OBSERVABILITY_ID,
                country_id=MOCK_COUNTRY_ID,
                reform_policy_id=MOCK_POLICY_ID,
                baseline_policy_id=MOCK_BASELINE_POLICY_ID,
                region=MOCK_REGION,
                dataset=MOCK_RESOLVED_DATASET,
                time_period=MOCK_TIME_PERIOD,
                options=MOCK_OPTIONS,
                api_version=MOCK_API_VERSION,
                target="general",
                model_version=MOCK_MODEL_VERSION,
                policyengine_version=MOCK_POLICYENGINE_VERSION,
                data_version=MOCK_DATA_VERSION,
                options_hash=MOCK_OPTIONS_HASH,
            )

        def test_untyped_poll_error_does_not_persist_a_terminal_failure(
            self,
            economy_service,
            setup_options,
            mock_simulation_entrypoint,
            mock_reform_impacts_service,
        ):
            impact = create_mock_reform_impact(status="computing")
            error = make_http_status_error(422, payload={"detail": "Unknown error"})
            mock_simulation_entrypoint.get_execution_by_id.side_effect = error

            with pytest.raises(httpx.HTTPStatusError) as raised:
                economy_service._handle_computing_impact(setup_options, impact)

            assert raised.value is error
            mock_reform_impacts_service.set_error_reform_impact.assert_not_called()
            mock_simulation_entrypoint.run.assert_not_called()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_succeeded_state__returns_completed_result(
            self,
            economy_service,
            setup_options,
            mock_simulation_entrypoint,
            mock_reform_impacts_service,
        ):
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_simulation_entrypoint.get_execution_result.return_value = (
                MOCK_REFORM_IMPACT_DATA
            )

            result = economy_service._handle_execution_state(
                setup_options, "complete", reform_impact, mock_execution
            )

            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            mock_reform_impacts_service.set_complete_reform_impact.assert_called_once()
            write_values = (
                mock_reform_impacts_service.set_complete_reform_impact.call_args.kwargs
            )
            assert isinstance(write_values["reform_impact_json"], dict)
            assert (
                write_values["reform_impact_json"]["poverty_impact"]
                == (MOCK_REFORM_IMPACT_DATA["poverty_impact"])
            )

        @pytest.mark.usefixtures("mock_logger")
        def test__given_failed_state__returns_error_result(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact
            )

            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            assert result.message == "Simulation entrypoint execution failed"
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_active_state__returns_computing_result(
            self, economy_service, setup_options
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact
            )

            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        def test__given_unknown_state__raises_error(
            self, economy_service, setup_options
        ):
            reform_impact = create_mock_reform_impact(status="computing")

            with pytest.raises(
                ValueError, match="Unexpected sim API execution state: UNKNOWN"
            ):
                economy_service._handle_execution_state(
                    setup_options, "UNKNOWN", reform_impact
                )

        # Modal status tests
        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_complete_state__then_returns_completed_result(
            self,
            economy_service,
            setup_options,
            mock_simulation_entrypoint,
            mock_reform_impacts_service,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_simulation_entrypoint.get_execution_result.return_value = (
                MOCK_REFORM_IMPACT_DATA
            )

            # When
            result = economy_service._handle_execution_state(
                setup_options, "complete", reform_impact, mock_execution
            )

            # Then
            assert result.status == ImpactStatus.OK
            assert result.data["policyengine_bundle"] == {
                "model_version": MOCK_MODEL_VERSION,
                "policyengine_version": MOCK_POLICYENGINE_VERSION,
                "data_version": MOCK_DATA_VERSION,
                "dataset": MOCK_RESOLVED_DATASET,
            }
            mock_reform_impacts_service.set_complete_reform_impact.assert_called_once()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_failed_state__then_returns_error_result(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_execution.error = None

            # When
            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact, mock_execution
            )

            # Then
            assert result.status == ImpactStatus.ERROR
            assert result.data is None
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_failure_with_error_message__includes_error_in_message(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            mock_execution = MagicMock()
            mock_execution.error = "Simulation timed out"

            # When
            result = economy_service._handle_execution_state(
                setup_options, "failed", reform_impact, mock_execution
            )

            # Then
            assert result.status == ImpactStatus.ERROR
            # Verify the error message was passed to the service
            call_args = mock_reform_impacts_service.set_error_reform_impact.call_args
            assert "Simulation timed out" in call_args[1]["message"]

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_running_state__then_returns_computing_result(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")

            # When
            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_running_state_with_run_progress__then_relays_it(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(
                job_id="fc-job-1",
                status="running",
                run_progress=SimulationRunProgress(
                    stage="reform", progress=67, progress_max=96
                ),
            )

            # When
            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact, execution
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.run_progress.to_dict() == {
                "stage": "reform",
                "progress": 67,
                "progress_max": 96,
            }
            assert "run_progress" not in result.to_dict()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_running_state_without_run_progress__then_has_none(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(job_id="fc-job-1", status="running")

            # When
            result = economy_service._handle_execution_state(
                setup_options, "running", reform_impact, execution
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.run_progress is None

        @pytest.mark.usefixtures("mock_logger")
        def test__given_modal_submitted_state__then_returns_computing_result(
            self, economy_service, setup_options
        ):
            # Given
            reform_impact = create_mock_reform_impact(status="computing")

            # When
            result = economy_service._handle_execution_state(
                setup_options, "submitted", reform_impact
            )

            # Then
            assert result.status == ImpactStatus.COMPUTING
            assert result.data is None
