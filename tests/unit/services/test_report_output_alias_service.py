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
