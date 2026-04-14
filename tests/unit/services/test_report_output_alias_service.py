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
