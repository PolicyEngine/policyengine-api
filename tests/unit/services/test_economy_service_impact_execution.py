"""Simulation execution states mapped to annual economic impact results."""

from unittest.mock import MagicMock

import httpx
import pytest

from policyengine_api.libs.simulation_entrypoint import (
    ModalSimulationExecution,
    SimulationRunProgress,
)
from policyengine_api.services.economy_service import (
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    EconomyService,
    ImpactStatus,
)
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_COUNTRY_ID,
    MOCK_DATA_VERSION,
    MOCK_EXECUTION_ID,
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

        def test__given_failed_us_state_job__keeps_its_error_for_two_minutes(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            mock_logger,
        ):
            # Given
            state_setup_options = setup_options.model_copy(
                update={"region": "state/ca"}
            )
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(
                job_id=MOCK_EXECUTION_ID, status="failed", error="out of memory"
            )
            stored_failure = create_mock_reform_impact(status="error")
            mock_reform_impacts_service.set_error_reform_impact.return_value = (
                stored_failure
            )
            # The next request's lookup answers from this stored failure.
            next_lookup = MagicMock(return_value=stored_failure)
            economy_service._get_most_recent_impact = next_lookup
            mock_reform_impacts_service.get_reform_impact_seconds_left.return_value = (
                120
            )
            mock_reform_impacts_service.get_reform_impact_seconds_until.return_value = (
                10
            )

            # When
            result = economy_service._handle_execution_state(
                state_setup_options, "failed", reform_impact, execution
            )

            # Then
            expected_message = (
                "Simulation entrypoint execution failed: out of memory. "
                "A new run for this state can be requested 2 minutes after this "
                "failure."
            )
            # The stored error expires, so the log keeps the failure's reason.
            # Checked first: building the expected result below logs too.
            mock_logger.log_struct.assert_any_call(
                {"message": expected_message}, severity="ERROR"
            )
            assert result == EconomicImpactResult.error(
                expected_message, retry_after_seconds=120, delete_after_seconds=10
            )
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once_with(
                execution_id=MOCK_EXECUTION_ID,
                message=expected_message,
                keep_seconds=120,
            )
            mock_reform_impacts_service.get_reform_impact_seconds_left.assert_called_once_with(
                stored_failure
            )
            mock_reform_impacts_service.get_reform_impact_seconds_until.assert_called_once_with(
                stored_failure, seconds_after_end=10
            )
            next_lookup.assert_called_once_with(state_setup_options)

        @pytest.mark.usefixtures("mock_logger")
        @pytest.mark.parametrize(
            "region",
            [MOCK_REGION, "congressional_district/CA-37", "place/NJ-57000"],
            ids=["national", "district", "place"],
        )
        def test__given_failed_us_job_outside_a_state__keeps_its_error_for_30_days(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            region,
        ):
            # Given
            region_setup_options = setup_options.model_copy(update={"region": region})
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(
                job_id=MOCK_EXECUTION_ID, status="failed", error="out of memory"
            )
            stored_failure = create_mock_reform_impact(status="error")
            mock_reform_impacts_service.set_error_reform_impact.return_value = (
                stored_failure
            )
            # The next request's lookup answers from this stored failure.
            next_lookup = MagicMock(return_value=stored_failure)
            economy_service._get_most_recent_impact = next_lookup
            mock_reform_impacts_service.get_reform_impact_seconds_left.return_value = (
                2_591_000
            )
            mock_reform_impacts_service.get_reform_impact_seconds_until.return_value = (
                10
            )

            # When
            result = economy_service._handle_execution_state(
                region_setup_options, "failed", reform_impact, execution
            )

            # Then
            expected_message = "Simulation entrypoint execution failed: out of memory"
            assert result == EconomicImpactResult.error(
                expected_message,
                retry_after_seconds=2_591_000,
                delete_after_seconds=10,
            )
            # Without keep_seconds the error has the cache's 30-day lifetime.
            mock_reform_impacts_service.set_error_reform_impact.assert_called_once_with(
                execution_id=MOCK_EXECUTION_ID,
                message=expected_message,
            )
            mock_reform_impacts_service.get_reform_impact_seconds_left.assert_called_once_with(
                stored_failure
            )
            mock_reform_impacts_service.get_reform_impact_seconds_until.assert_called_once_with(
                stored_failure, seconds_after_end=10
            )
            next_lookup.assert_called_once_with(region_setup_options)

        @pytest.mark.usefixtures("mock_logger")
        @pytest.mark.parametrize("region", ["state/ca", MOCK_REGION])
        @pytest.mark.parametrize(
            "next_answer",
            [None, create_mock_reform_impact(status="computing")],
            ids=["no-record", "another-record"],
        )
        def test__given_the_next_lookup_uses_another_record__gives_no_seconds(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            next_answer,
            region,
        ):
            # Given: the failure is stored, but the next request would start a
            # new run or answer from a newer job instead.
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(
                job_id=MOCK_EXECUTION_ID, status="failed", error="out of memory"
            )
            stored_failure = create_mock_reform_impact(status="error")
            mock_reform_impacts_service.set_error_reform_impact.return_value = (
                stored_failure
            )
            if next_answer is not None:
                next_answer.execution_id = "newer-job"
            economy_service._get_most_recent_impact = MagicMock(
                return_value=next_answer
            )

            # When
            result = economy_service._handle_execution_state(
                setup_options.model_copy(update={"region": region}),
                "failed",
                reform_impact,
                execution,
            )

            # Then
            assert result.status == ImpactStatus.ERROR
            assert result.retry_after_seconds is None
            assert result.delete_after_seconds is None
            mock_reform_impacts_service.get_reform_impact_seconds_left.assert_not_called()
            mock_reform_impacts_service.get_reform_impact_seconds_until.assert_not_called()

        @pytest.mark.usefixtures("mock_logger")
        @pytest.mark.parametrize("region", ["state/ca", MOCK_REGION])
        def test__given_the_error_is_not_stored__answers_without_seconds(
            self,
            economy_service,
            setup_options,
            mock_reform_impacts_service,
            region,
        ):
            # Given: the cache refuses the error write, so no failure is stored.
            region_setup_options = setup_options.model_copy(update={"region": region})
            reform_impact = create_mock_reform_impact(status="computing")
            execution = ModalSimulationExecution(
                job_id=MOCK_EXECUTION_ID, status="failed", error="out of memory"
            )
            mock_reform_impacts_service.set_error_reform_impact.return_value = None

            # When
            result = economy_service._handle_execution_state(
                region_setup_options, "failed", reform_impact, execution
            )

            # Then
            assert result.status == ImpactStatus.ERROR
            assert result.retry_after_seconds is None
            assert result.delete_after_seconds is None
            mock_reform_impacts_service.get_reform_impact_seconds_left.assert_not_called()
            mock_reform_impacts_service.get_reform_impact_seconds_until.assert_not_called()

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

    class TestHandleFailedImpact:
        @pytest.fixture
        def economy_service(self):
            return EconomyService()

        @pytest.mark.usefixtures("mock_logger")
        def test__given_stored_failure__answers_with_the_seconds_it_is_still_kept(
            self,
            economy_service,
            mock_reform_impacts_service,
        ):
            # Given
            stored_failure = create_mock_reform_impact(
                status="error",
                message="Simulation entrypoint execution failed: out of memory",
            )
            seconds_left = mock_reform_impacts_service.get_reform_impact_seconds_left
            seconds_left.return_value = 75
            seconds_until = mock_reform_impacts_service.get_reform_impact_seconds_until
            seconds_until.return_value = 4

            # When
            result = economy_service._handle_failed_impact(stored_failure)

            # Then
            assert result == EconomicImpactResult.error(
                "Simulation entrypoint execution failed: out of memory",
                retry_after_seconds=75,
                delete_after_seconds=4,
            )
            mock_reform_impacts_service.get_reform_impact_seconds_left.assert_called_once_with(
                stored_failure
            )

        @pytest.mark.usefixtures("mock_logger")
        def test__given_a_stored_failure_whose_lifetime_is_unreadable__gives_no_waits(
            self,
            economy_service,
            mock_reform_impacts_service,
        ):
            # Given: the failure is replayed, but its expiry cannot be read.
            stored_failure = create_mock_reform_impact(
                status="error",
                message="Simulation entrypoint execution failed: out of memory",
            )
            seconds_left = mock_reform_impacts_service.get_reform_impact_seconds_left
            seconds_left.return_value = None
            seconds_until = mock_reform_impacts_service.get_reform_impact_seconds_until
            seconds_until.return_value = 4

            # When
            result = economy_service._handle_failed_impact(stored_failure)

            # Then: no wait at all, since nothing says when a new run can start.
            assert result.retry_after_seconds is None
            assert result.delete_after_seconds is None
            seconds_until.assert_not_called()
