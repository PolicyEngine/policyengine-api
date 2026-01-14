"""
Unit tests for simulation_api_factory.

Tests the factory function that selects between GCP Workflows
and Modal simulation API backends.
"""

import pytest
from unittest.mock import patch, MagicMock

from tests.fixtures.libs.simulation_api_factory import (
    mock_env_use_modal_true,
    mock_env_use_modal_false,
    mock_factory_logger,
)


class TestGetSimulationApi:
    """Tests for the get_simulation_api factory function."""

    class TestModalSelection:

        def test__given_use_modal_env_true__then_returns_modal_api(
            self,
            mock_factory_logger,
        ):
            # Given
            with patch.dict(
                "os.environ",
                {"USE_MODAL_SIMULATION_API": "true"},
            ):
                # Need to reimport to pick up the env change
                from policyengine_api.libs.simulation_api_factory import (
                    get_simulation_api,
                )
                from policyengine_api.libs.simulation_api_modal import (
                    SimulationAPIModal,
                )

                # When
                api = get_simulation_api()

                # Then
                assert isinstance(api, SimulationAPIModal)

        def test__given_use_modal_env_true_uppercase__then_returns_modal_api(
            self,
            mock_factory_logger,
        ):
            # Given
            with patch.dict(
                "os.environ",
                {"USE_MODAL_SIMULATION_API": "TRUE"},
            ):
                from policyengine_api.libs.simulation_api_factory import (
                    get_simulation_api,
                )
                from policyengine_api.libs.simulation_api_modal import (
                    SimulationAPIModal,
                )

                # When
                api = get_simulation_api()

                # Then
                assert isinstance(api, SimulationAPIModal)

        def test__given_use_modal_env_true__then_logs_modal_selection(
            self,
            mock_factory_logger,
        ):
            # Given
            with patch.dict(
                "os.environ",
                {"USE_MODAL_SIMULATION_API": "true"},
            ):
                from policyengine_api.libs.simulation_api_factory import (
                    get_simulation_api,
                )

                # When
                get_simulation_api()

                # Then
                mock_factory_logger.log_struct.assert_called()
                call_args = mock_factory_logger.log_struct.call_args[0][0]
                assert "Modal" in call_args["message"]

    class TestGCPSelection:

        def test__given_use_modal_env_false__then_returns_gcp_api(
            self,
            mock_factory_logger,
        ):
            # Given
            with patch.dict(
                "os.environ",
                {
                    "USE_MODAL_SIMULATION_API": "false",
                    "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/creds.json",
                },
            ):
                # Mock the GCP client to avoid needing real credentials
                with patch(
                    "policyengine_api.libs.simulation_api.executions_v1.ExecutionsClient"
                ):
                    with patch(
                        "policyengine_api.libs.simulation_api.workflows_v1.WorkflowsClient"
                    ):
                        from policyengine_api.libs.simulation_api_factory import (
                            get_simulation_api,
                        )
                        from policyengine_api.libs.simulation_api import (
                            SimulationAPI,
                        )

                        # When
                        api = get_simulation_api()

                        # Then
                        assert isinstance(api, SimulationAPI)

        def test__given_use_modal_env_not_set__then_returns_modal_api(
            self,
            mock_factory_logger,
        ):
            # Given - default is now Modal when env var is not set
            import os

            env_copy = dict(os.environ)
            env_copy.pop("USE_MODAL_SIMULATION_API", None)

            with patch.dict("os.environ", env_copy, clear=True):
                from policyengine_api.libs.simulation_api_factory import (
                    get_simulation_api,
                )
                from policyengine_api.libs.simulation_api_modal import (
                    SimulationAPIModal,
                )

                # When
                api = get_simulation_api()

                # Then
                assert isinstance(api, SimulationAPIModal)

        def test__given_use_modal_env_false__then_logs_gcp_selection(
            self,
            mock_factory_logger,
        ):
            # Given
            with patch.dict(
                "os.environ",
                {
                    "USE_MODAL_SIMULATION_API": "false",
                    "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/creds.json",
                },
            ):
                with patch(
                    "policyengine_api.libs.simulation_api.executions_v1.ExecutionsClient"
                ):
                    with patch(
                        "policyengine_api.libs.simulation_api.workflows_v1.WorkflowsClient"
                    ):
                        from policyengine_api.libs.simulation_api_factory import (
                            get_simulation_api,
                        )

                        # When
                        get_simulation_api()

                        # Then
                        mock_factory_logger.log_struct.assert_called()
                        call_args = mock_factory_logger.log_struct.call_args[0][0]
                        assert "GCP" in call_args["message"]

    class TestGCPCredentialsError:

        def test__given_gcp_selected_without_credentials__then_raises_error(
            self,
            mock_factory_logger,
        ):
            # Given - explicitly select GCP without credentials
            import os

            env_copy = dict(os.environ)
            env_copy["USE_MODAL_SIMULATION_API"] = "false"
            env_copy.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

            with patch.dict("os.environ", env_copy, clear=True):
                from policyengine_api.libs.simulation_api_factory import (
                    get_simulation_api,
                )

                # When/Then
                with pytest.raises(ValueError) as exc_info:
                    get_simulation_api()

                assert "GOOGLE_APPLICATION_CREDENTIALS" in str(exc_info.value)
