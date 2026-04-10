import datetime

from policyengine_api.constants import get_economy_impact_cache_version
from policyengine_api.services.reform_impacts_service import ReformImpactsService


def insert_reform_impact(
    test_db,
    *,
    baseline_policy_id=1,
    reform_policy_id=2,
    country_id="us",
    region="us",
    dataset="default",
    time_period="2025",
    options_json="[]",
    options_hash="[]",
    api_version=None,
    reform_impact_json='{"result": 1}',
    status="ok",
    message="Completed",
    execution_id="exec-1",
):
    if api_version is None:
        api_version = get_economy_impact_cache_version(country_id)

    test_db.query(
        """INSERT INTO reform_impact
        (baseline_policy_id, reform_policy_id, country_id, region, dataset, time_period,
        options_json, options_hash, api_version, reform_impact_json, status, message, start_time,
        execution_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            baseline_policy_id,
            reform_policy_id,
            country_id,
            region,
            dataset,
            time_period,
            options_json,
            options_hash,
            api_version,
            reform_impact_json,
            status,
            message,
            datetime.datetime(2026, 1, 1, 12, 0, 0),
            execution_id,
        ),
    )


class TestReformImpactsService:
    def test_delete_reform_impacts_deletes_completed_rows_for_exact_cache_key(
        self, test_db
    ):
        service = ReformImpactsService()
        current_version = get_economy_impact_cache_version("us")

        insert_reform_impact(
            test_db,
            api_version=current_version,
            status="ok",
            execution_id="exec-ok",
        )
        insert_reform_impact(
            test_db,
            api_version=current_version,
            status="error",
            execution_id="exec-error",
        )
        insert_reform_impact(
            test_db,
            api_version=current_version,
            status="computing",
            execution_id="exec-computing",
        )
        insert_reform_impact(
            test_db,
            api_version="e1stale01",
            status="ok",
            execution_id="exec-stale",
        )
        insert_reform_impact(
            test_db,
            dataset="enhanced_cps",
            api_version=current_version,
            status="ok",
            execution_id="exec-other-dataset",
        )

        deleted_rows = service.delete_reform_impacts(
            country_id="us",
            policy_id=2,
            baseline_policy_id=1,
            region="us",
            dataset="default",
            time_period="2025",
            options_hash="[]",
            api_version=current_version,
        )

        assert deleted_rows == 3

        remaining_rows = test_db.query(
            "SELECT execution_id, dataset, api_version, status FROM reform_impact ORDER BY execution_id"
        ).fetchall()
        assert [row["execution_id"] for row in remaining_rows] == [
            "exec-other-dataset",
            "exec-stale",
        ]

    def test_delete_reform_impact_keeps_completed_rows(self, test_db):
        service = ReformImpactsService()

        insert_reform_impact(
            test_db,
            status="ok",
            execution_id="exec-ok",
        )
        insert_reform_impact(
            test_db,
            status="computing",
            execution_id="exec-computing",
        )

        deleted_rows = service.delete_reform_impact(
            country_id="us",
            policy_id=2,
            baseline_policy_id=1,
            region="us",
            dataset="default",
            time_period="2025",
            options_hash="[]",
        )

        assert deleted_rows == 1

        remaining_rows = test_db.query(
            "SELECT execution_id, status FROM reform_impact ORDER BY execution_id"
        ).fetchall()
        assert remaining_rows == [{"execution_id": "exec-ok", "status": "ok"}]
