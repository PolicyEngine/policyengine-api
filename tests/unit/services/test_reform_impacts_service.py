from unittest.mock import MagicMock

import pytest

from policyengine_api.services.reform_impacts_service import ReformImpactsService


LOCK_KWARGS = {
    "country_id": "us",
    "policy_id": 123,
    "baseline_policy_id": 456,
    "region": "us",
    "dataset": "enhanced_cps",
    "time_period": "2026",
    "options_hash": "[option=value]",
    "api_version": "e1cache01",
}


def _mock_database(monkeypatch, *, local=False, query_result=None, side_effect=None):
    mock_database = MagicMock()
    mock_database.local = local
    if side_effect is not None:
        mock_database.query.side_effect = side_effect
    elif query_result is not None:
        mock_database.query.return_value = query_result
    monkeypatch.setattr(
        "policyengine_api.services.reform_impacts_service.database",
        mock_database,
    )
    return mock_database


class TestReformImpactsService:
    def test__given_reform_impact_lookup__does_not_manage_schema(self, monkeypatch):
        service = ReformImpactsService()

        select_result = MagicMock()
        select_result.fetchall.return_value = []
        mock_database = MagicMock()
        mock_database.local = False
        mock_database.query.return_value = select_result

        monkeypatch.setattr(
            "policyengine_api.services.reform_impacts_service.database",
            mock_database,
        )

        service.get_all_reform_impacts(
            "us",
            123,
            456,
            "us",
            "enhanced_cps",
            "2026",
            "[option=value]",
            "e1cache01",
        )

        mock_database.query.assert_called_once()
        query = mock_database.query.call_args.args[0]
        assert query.startswith("SELECT reform_impact_json")
        assert not query.startswith("ALTER")
        assert not query.startswith("SHOW")

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

    def test__given_local_database__claim_lock_uses_in_process_lock(self, monkeypatch):
        service = ReformImpactsService()
        mock_database = _mock_database(monkeypatch, local=True)

        with service.claim_lock(**LOCK_KWARGS):
            mock_database.query.assert_not_called()

        mock_database.pool.connect.assert_not_called()

    def test__get_all_reform_impacts__queries_dataset_and_stable_order(
        self, monkeypatch
    ):
        service = ReformImpactsService()
        query_result = MagicMock()
        query_result.fetchall.return_value = [{"status": "ok"}]
        mock_database = _mock_database(monkeypatch, query_result=query_result)

        result = service.get_all_reform_impacts(**LOCK_KWARGS)

        assert result == [{"status": "ok"}]
        query, params = mock_database.query.call_args.args
        assert "AND dataset = ?" in query
        assert "ORDER BY start_time DESC, reform_impact_id DESC" in query
        assert params == (
            "us",
            123,
            456,
            "us",
            "2026",
            "[option=value]",
            "e1cache01",
            "enhanced_cps",
        )

    def test__get_all_reform_impacts_by_options_hash_prefix__prefers_exact_hash(
        self, monkeypatch
    ):
        service = ReformImpactsService()
        query_result = MagicMock()
        query_result.fetchall.return_value = [{"options_hash": "[option=value]"}]
        mock_database = _mock_database(monkeypatch, query_result=query_result)

        result = service.get_all_reform_impacts_by_options_hash_prefix(
            **LOCK_KWARGS,
            options_hash_prefix="[option=%",
        )

        assert result == [{"options_hash": "[option=value]"}]
        query, params = mock_database.query.call_args.args
        assert "(options_hash = ? OR options_hash LIKE ? ESCAPE '\\')" in query
        assert "ORDER BY CASE WHEN options_hash = ? THEN 0 ELSE 1 END" in query
        assert params == (
            "us",
            123,
            456,
            "us",
            "2026",
            "[option=value]",
            "[option=%",
            "e1cache01",
            "enhanced_cps",
            "[option=value]",
        )

    def test__set_reform_impact__inserts_tracking_row(self, monkeypatch):
        service = ReformImpactsService()
        mock_database = _mock_database(monkeypatch)

        service.set_reform_impact(
            **LOCK_KWARGS,
            options='{"option": "value"}',
            status="computing",
            reform_impact_json="{}",
            start_time="2026-01-01 00:00:00",
            execution_id="pending:job-1",
        )

        query, params = mock_database.query.call_args.args
        assert query.startswith("INSERT INTO reform_impact")
        assert params == (
            "us",
            123,
            456,
            "us",
            "enhanced_cps",
            "2026",
            '{"option": "value"}',
            "[option=value]",
            "computing",
            "e1cache01",
            "{}",
            "2026-01-01 00:00:00",
            "pending:job-1",
        )

    def test__update_reform_impact_execution_id__returns_rowcount(self, monkeypatch):
        service = ReformImpactsService()
        query_result = MagicMock()
        query_result.rowcount = 1
        mock_database = _mock_database(monkeypatch, query_result=query_result)

        rowcount = service.update_reform_impact_execution_id(
            country_id="us",
            policy_id=123,
            baseline_policy_id=456,
            region="us",
            dataset="enhanced_cps",
            time_period="2026",
            options_hash="[option=value]",
            current_execution_id="pending:job-1",
            new_execution_id="fc-job-1",
        )

        assert rowcount == 1
        query, params = mock_database.query.call_args.args
        assert "status = 'computing'" in query
        assert params == (
            "fc-job-1",
            "us",
            123,
            456,
            "us",
            "2026",
            "[option=value]",
            "enhanced_cps",
            "pending:job-1",
        )

    def test__delete_reform_impact__only_deletes_computing_rows(self, monkeypatch):
        service = ReformImpactsService()
        mock_database = _mock_database(monkeypatch)

        service.delete_reform_impact(
            country_id="us",
            policy_id=123,
            baseline_policy_id=456,
            region="us",
            dataset="enhanced_cps",
            time_period="2026",
            options_hash="[option=value]",
        )

        query, params = mock_database.query.call_args.args
        assert "status = 'computing'" in query
        assert params == (
            "us",
            123,
            456,
            "us",
            "2026",
            "[option=value]",
            "enhanced_cps",
        )

    def test__set_error_reform_impact__updates_status_message_and_execution(
        self, monkeypatch
    ):
        service = ReformImpactsService()
        mock_database = _mock_database(monkeypatch)

        service.set_error_reform_impact(
            country_id="us",
            policy_id=123,
            baseline_policy_id=456,
            region="us",
            dataset="enhanced_cps",
            time_period="2026",
            options_hash="[option=value]",
            message="failed",
            execution_id="fc-job-1",
        )

        query, params = mock_database.query.call_args.args
        assert query.startswith("UPDATE reform_impact SET status = ?, message = ?")
        assert params[0] == "error"
        assert params[1] == "failed"
        assert params[-1] == "fc-job-1"

    def test__set_complete_reform_impact__updates_result_and_execution(
        self, monkeypatch
    ):
        service = ReformImpactsService()
        mock_database = _mock_database(monkeypatch)

        service.set_complete_reform_impact(
            country_id="us",
            reform_policy_id=123,
            baseline_policy_id=456,
            region="us",
            dataset="enhanced_cps",
            time_period="2026",
            options_hash="[option=value]",
            reform_impact_json='{"ok": true}',
            execution_id="fc-job-1",
        )

        query, params = mock_database.query.call_args.args
        assert query.startswith("UPDATE reform_impact SET status = ?, message = ?")
        assert params[0] == "ok"
        assert params[1] == "Completed"
        assert params[3] == '{"ok": true}'
        assert params[-1] == "fc-job-1"

    @pytest.mark.parametrize(
        "call_service",
        [
            lambda service: service.get_all_reform_impacts(**LOCK_KWARGS),
            lambda service: service.get_all_reform_impacts_by_options_hash_prefix(
                **LOCK_KWARGS,
                options_hash_prefix="[option=%",
            ),
            lambda service: service.set_reform_impact(
                **LOCK_KWARGS,
                options="{}",
                status="computing",
                reform_impact_json="{}",
                start_time="2026-01-01 00:00:00",
                execution_id="pending:job-1",
            ),
            lambda service: service.update_reform_impact_execution_id(
                country_id="us",
                policy_id=123,
                baseline_policy_id=456,
                region="us",
                dataset="enhanced_cps",
                time_period="2026",
                options_hash="[option=value]",
                current_execution_id="pending:job-1",
                new_execution_id="fc-job-1",
            ),
            lambda service: service.delete_reform_impact(
                country_id="us",
                policy_id=123,
                baseline_policy_id=456,
                region="us",
                dataset="enhanced_cps",
                time_period="2026",
                options_hash="[option=value]",
            ),
            lambda service: service.set_error_reform_impact(
                country_id="us",
                policy_id=123,
                baseline_policy_id=456,
                region="us",
                dataset="enhanced_cps",
                time_period="2026",
                options_hash="[option=value]",
                message="failed",
                execution_id="fc-job-1",
            ),
            lambda service: service.set_complete_reform_impact(
                country_id="us",
                reform_policy_id=123,
                baseline_policy_id=456,
                region="us",
                dataset="enhanced_cps",
                time_period="2026",
                options_hash="[option=value]",
                reform_impact_json="{}",
                execution_id="fc-job-1",
            ),
        ],
    )
    def test__given_database_error__service_methods_reraise(
        self, monkeypatch, call_service
    ):
        service = ReformImpactsService()
        _mock_database(monkeypatch, side_effect=RuntimeError("db down"))

        with pytest.raises(RuntimeError, match="db down"):
            call_service(service)
