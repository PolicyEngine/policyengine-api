import pytest

from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.report_spec_service import (
    EconomyReportSpec,
    HouseholdReportSpec,
    ReportSpecService,
)
from policyengine_api.services.simulation_service import SimulationService

report_output_service = ReportOutputService()
report_spec_service = ReportSpecService()
simulation_service = SimulationService()


class TestBuildReportSpec:
    def test_builds_household_comparison_report_spec(self, test_db):
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_1",
            population_type="household",
            policy_id=1,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_1",
            population_type="household",
            policy_id=2,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=simulation_2["id"],
            year="2026",
        )

        report_spec = report_spec_service.build_report_spec(
            report_output, simulation_1, simulation_2
        )

        assert isinstance(report_spec, HouseholdReportSpec)
        assert report_spec.report_kind == "household_comparison"
        assert report_spec.time_period == "2026"
        assert report_spec.simulation_1.policy_id == 1
        assert report_spec.simulation_2.policy_id == 2

    def test_builds_default_economy_report_spec(self, test_db):
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=10,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=11,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=simulation_2["id"],
            year="2027",
        )

        report_spec = report_spec_service.build_report_spec(
            report_output, simulation_1, simulation_2
        )

        assert isinstance(report_spec, EconomyReportSpec)
        assert report_spec.report_kind == "economy_comparison"
        assert report_spec.region == "ca"
        assert report_spec.dataset == "default"
        assert report_spec.target == "general"
        assert report_spec.options == {}

    def test_raises_for_mixed_population_types(self, test_db):
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="household_1",
            population_type="household",
            policy_id=1,
        )
        simulation_2 = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=2,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=simulation_2["id"],
            year="2025",
        )

        with pytest.raises(ValueError) as exc_info:
            report_spec_service.build_report_spec(
                report_output, simulation_1, simulation_2
            )

        assert "population types must match" in str(exc_info.value)


class TestPersistReportSpec:
    def test_sets_and_gets_report_spec(self, test_db):
        simulation_1 = simulation_service.create_simulation(
            country_id="us",
            population_id="ca",
            population_type="geography",
            policy_id=10,
        )
        report_output = report_output_service.create_report_output(
            country_id="us",
            simulation_1_id=simulation_1["id"],
            simulation_2_id=None,
            year="2027",
        )
        report_spec = EconomyReportSpec.model_validate(
            {
                "country_id": "us",
                "report_kind": "economy_single",
                "time_period": "2027",
                "region": "ca",
                "baseline_policy_id": 10,
                "reform_policy_id": 10,
                "dataset": "default",
                "target": "general",
                "options": {},
            }
        )

        result = report_spec_service.set_report_spec(
            report_output["id"], report_spec, report_spec_status="explicit"
        )

        assert result is True
        stored_report = test_db.query(
            """
            SELECT report_kind, report_spec_json, report_spec_schema_version, report_spec_status
            FROM report_outputs WHERE id = ?
            """,
            (report_output["id"],),
        ).fetchone()
        assert stored_report["report_kind"] == "economy_single"
        assert stored_report["report_spec_schema_version"] == 1
        assert stored_report["report_spec_status"] == "explicit"

        loaded_report_spec = report_spec_service.get_report_spec(report_output["id"])
        assert loaded_report_spec is not None
        assert loaded_report_spec.model_dump() == report_spec.model_dump()
