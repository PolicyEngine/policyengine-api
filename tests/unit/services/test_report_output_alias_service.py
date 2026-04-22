import pytest

from policyengine_api.services.report_output_alias_service import (
    ReportOutputAliasService,
)
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.simulation_service import SimulationService

alias_service = ReportOutputAliasService()
report_output_service = ReportOutputService()
simulation_service = SimulationService()


class TestReportOutputAliasService:
    def _insert_legacy_report_output(
        self,
        test_db,
        legacy_report_output_id: int,
        canonical_report: dict,
        api_version: str = "legacy-version",
        report_identity_hash: str | None = None,
        report_identity_schema_version: int | None = None,
    ) -> None:
        test_db.query(
            """
            INSERT INTO report_outputs (
                id, country_id, simulation_1_id, simulation_2_id, api_version, status, year,
                report_identity_hash, report_identity_schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legacy_report_output_id,
                canonical_report["country_id"],
                canonical_report["simulation_1_id"],
                canonical_report["simulation_2_id"],
                api_version,
                canonical_report["status"],
                canonical_report["year"],
                report_identity_hash or canonical_report.get("report_identity_hash"),
                report_identity_schema_version
                if report_identity_schema_version is not None
                else canonical_report.get("report_identity_schema_version"),
            ),
        )

    def test_resolves_to_canonical_report_output_id_when_alias_exists(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_1",
            population_type="household",
            policy_id=1,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        self._insert_legacy_report_output(test_db, 999, canonical_report)

        alias_service.set_alias(
            legacy_report_output_id=999,
            canonical_report_output_id=canonical_report["id"],
        )

        resolved_id = alias_service.resolve_canonical_report_output_id(999)

        assert resolved_id == canonical_report["id"]

    def test_returns_requested_id_when_alias_is_not_needed(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_2",
            population_type="household",
            policy_id=2,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        resolved_id = alias_service.resolve_canonical_report_output_id(
            report_output["id"]
        )

        assert resolved_id == report_output["id"]

    def test_returns_none_for_unknown_report_output(self, test_db):
        assert alias_service.resolve_canonical_report_output_id(123456) is None

    def test_set_alias_is_idempotent_for_same_canonical_report_output(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_3",
            population_type="household",
            policy_id=3,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        self._insert_legacy_report_output(test_db, 1001, canonical_report)

        assert (
            alias_service.set_alias(
                legacy_report_output_id=1001,
                canonical_report_output_id=canonical_report["id"],
            )
            is True
        )
        assert (
            alias_service.set_alias(
                legacy_report_output_id=1001,
                canonical_report_output_id=canonical_report["id"],
            )
            is True
        )

    def test_rejects_alias_to_missing_canonical_report_output(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_3a",
            population_type="household",
            policy_id=3,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        self._insert_legacy_report_output(test_db, 1002, canonical_report)

        with pytest.raises(ValueError) as exc_info:
            alias_service.set_alias(
                legacy_report_output_id=1002,
                canonical_report_output_id=999999,
            )

        assert "Canonical report output #999999 not found" in str(exc_info.value)

    def test_rejects_conflicting_alias_remap(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_4",
            population_type="household",
            policy_id=4,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        other_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2026",
        )
        self._insert_legacy_report_output(test_db, 1003, canonical_report)
        alias_service.set_alias(
            legacy_report_output_id=1003,
            canonical_report_output_id=canonical_report["id"],
        )

        with pytest.raises(ValueError) as exc_info:
            alias_service.set_alias(
                legacy_report_output_id=1003,
                canonical_report_output_id=other_report["id"],
            )

        assert (
            "Legacy report output alias already points to canonical report output "
            f"#{canonical_report['id']}"
        ) in str(exc_info.value)

    def test_rejects_alias_when_legacy_report_output_is_missing(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_4a",
            population_type="household",
            policy_id=4,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        with pytest.raises(ValueError) as exc_info:
            alias_service.set_alias(
                legacy_report_output_id=10030,
                canonical_report_output_id=canonical_report["id"],
            )

        assert "Legacy report output #10030 not found" in str(exc_info.value)

    def test_rejects_alias_when_reports_do_not_share_canonical_identity(
        self, test_db
    ):
        baseline_simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="state/tx",
            population_type="geography",
            policy_id=34,
        )
        reform_simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="state/tx",
            population_type="geography",
            policy_id=35,
        )
        default_report_spec = report_output_service.parse_report_spec_payload(
            {
                "country_id": "us",
                "report_kind": "economy_comparison",
                "time_period": "2026",
                "region": "state/tx",
                "baseline_policy_id": 34,
                "reform_policy_id": 35,
                "dataset": "default",
                "target": "general",
                "options": {},
            }
        )
        cliff_report_spec = report_output_service.parse_report_spec_payload(
            {
                "country_id": "us",
                "report_kind": "economy_comparison",
                "time_period": "2026",
                "region": "state/tx",
                "baseline_policy_id": 34,
                "reform_policy_id": 35,
                "dataset": "enhanced_us_household",
                "target": "cliff",
                "options": {"view": "tax"},
            }
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=baseline_simulation["id"],
            simulation_2_id=reform_simulation["id"],
            year="2026",
            report_spec=default_report_spec,
            report_spec_schema_version=1,
        )
        distinct_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=baseline_simulation["id"],
            simulation_2_id=reform_simulation["id"],
            year="2026",
            report_spec=cliff_report_spec,
            report_spec_schema_version=1,
        )

        with pytest.raises(ValueError) as exc_info:
            alias_service.set_alias(
                legacy_report_output_id=distinct_report["id"],
                canonical_report_output_id=canonical_report["id"],
            )

        assert "must share canonical report identity" in str(exc_info.value)

    def test_rejects_alias_when_legacy_report_output_has_no_identity(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_4b",
            population_type="household",
            policy_id=4,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        self._insert_legacy_report_output(
            test_db,
            legacy_report_output_id=10031,
            canonical_report=canonical_report,
            report_identity_hash=None,
            report_identity_schema_version=None,
        )
        test_db.query(
            """
            UPDATE report_outputs
            SET report_identity_hash = NULL, report_identity_schema_version = NULL
            WHERE id = ?
            """,
            (10031,),
        )

        with pytest.raises(ValueError) as exc_info:
            alias_service.set_alias(
                legacy_report_output_id=10031,
                canonical_report_output_id=canonical_report["id"],
            )

        assert "must have canonical report identity" in str(exc_info.value)

    def test_rejects_alias_when_legacy_and_canonical_ids_match(self, test_db):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_4c",
            population_type="household",
            policy_id=4,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )

        with pytest.raises(ValueError) as exc_info:
            alias_service.set_alias(
                legacy_report_output_id=canonical_report["id"],
                canonical_report_output_id=canonical_report["id"],
            )

        assert "must be different" in str(exc_info.value)

    def test_rejects_alias_resolution_when_canonical_report_output_is_missing(
        self, test_db
    ):
        simulation = simulation_service.create_simulation(
            country_id="us",
            population_id="household_5",
            population_type="household",
            policy_id=5,
        )
        canonical_report = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation["id"],
            simulation_2_id=None,
            year="2025",
        )
        self._insert_legacy_report_output(test_db, 1004, canonical_report)
        alias_service.set_alias(
            legacy_report_output_id=1004,
            canonical_report_output_id=canonical_report["id"],
        )
        test_db.query(
            "DELETE FROM report_outputs WHERE id = ?",
            (canonical_report["id"],),
        )

        with pytest.raises(ValueError) as exc_info:
            alias_service.resolve_canonical_report_output_id(1004)

        assert (
            f"Alias points to missing canonical report output #{canonical_report['id']}"
        ) in str(exc_info.value)
