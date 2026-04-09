from unittest.mock import MagicMock

import pytest

from policyengine_api.services.reform_impacts_service import ReformImpactsService


class TestReformImpactsService:
    def test__given_remote_database__claim_lock_uses_advisory_lock(self, monkeypatch):
        service = ReformImpactsService()

        acquired_result = MagicMock()
        acquired_result.mappings.return_value.first.return_value = {"acquired": 1}
        release_result = MagicMock()

        mock_connection = MagicMock()
        mock_connection.exec_driver_sql.side_effect = [
            acquired_result,
            release_result,
        ]

        mock_connection_context = MagicMock()
        mock_connection_context.__enter__.return_value = mock_connection
        mock_connection_context.__exit__.return_value = False

        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_connection_context

        mock_database = MagicMock()
        mock_database.local = False
        mock_database.pool = mock_pool

        monkeypatch.setattr(
            "policyengine_api.services.reform_impacts_service.database",
            mock_database,
        )

        with service.claim_lock(
            country_id="us",
            policy_id=123,
            baseline_policy_id=456,
            region="us",
            dataset="enhanced_cps",
            time_period="2026",
            options_hash="[option=value]",
            api_version="e1cache01",
        ):
            pass

        assert mock_connection.exec_driver_sql.call_count == 2

        acquire_call = mock_connection.exec_driver_sql.call_args_list[0]
        assert acquire_call.args == (
            "SELECT GET_LOCK(%s, %s) AS acquired",
            (
                service._build_lock_name(
                    country_id="us",
                    policy_id=123,
                    baseline_policy_id=456,
                    region="us",
                    dataset="enhanced_cps",
                    time_period="2026",
                    options_hash="[option=value]",
                    api_version="e1cache01",
                ),
                5,
            ),
        )
        assert len(acquire_call.args[1][0]) <= 64

        release_call = mock_connection.exec_driver_sql.call_args_list[1]
        assert release_call.args == (
            "SELECT RELEASE_LOCK(%s) AS released",
            (acquire_call.args[1][0],),
        )
        mock_connection.commit.assert_called_once()

    def test__given_remote_database_lock_timeout__claim_lock_raises(self, monkeypatch):
        service = ReformImpactsService()

        acquired_result = MagicMock()
        acquired_result.mappings.return_value.first.return_value = {"acquired": 0}

        mock_connection = MagicMock()
        mock_connection.exec_driver_sql.return_value = acquired_result

        mock_connection_context = MagicMock()
        mock_connection_context.__enter__.return_value = mock_connection
        mock_connection_context.__exit__.return_value = False

        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_connection_context

        mock_database = MagicMock()
        mock_database.local = False
        mock_database.pool = mock_pool

        monkeypatch.setattr(
            "policyengine_api.services.reform_impacts_service.database",
            mock_database,
        )

        with pytest.raises(
            TimeoutError,
            match="Could not acquire reform impact lock",
        ):
            with service.claim_lock(
                country_id="us",
                policy_id=123,
                baseline_policy_id=456,
                region="us",
                dataset="enhanced_cps",
                time_period="2026",
                options_hash="[option=value]",
                api_version="e1cache01",
            ):
                pass
