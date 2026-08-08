import pytest

from policyengine_api.data.v1_models import ReportOutput, Simulation
from policyengine_api.services.report_spec_service import (
    EconomyReportSpec,
    HouseholdReportSpec,
    ReportSpecService,
)


service = ReportSpecService()


def add_simulation(
    orm_session,
    *,
    population_type="household",
    population_id="household-1",
    policy_id=1,
    country_id="us",
):
    simulation = Simulation(
        country_id=country_id,
        api_version="1",
        population_id=population_id,
        population_type=population_type,
        policy_id=policy_id,
        status="pending",
    )
    orm_session.add(simulation)
    orm_session.flush()
    return simulation


def add_report(orm_session, simulation_1, simulation_2=None, *, country_id="us"):
    report = ReportOutput(
        country_id=country_id,
        simulation_1_id=simulation_1.id,
        simulation_2_id=simulation_2.id if simulation_2 else None,
        api_version="1",
        status="pending",
        year="2026",
    )
    orm_session.add(report)
    orm_session.flush()
    return report


def test_builds_household_comparison_spec_from_models(orm_session):
    first = add_simulation(orm_session, policy_id=1)
    second = add_simulation(orm_session, policy_id=2)
    report = add_report(orm_session, first, second)

    spec = service.build_report_spec(report, first, second)

    assert isinstance(spec, HouseholdReportSpec)
    assert spec.report_kind == "household_comparison"
    assert spec.simulation_1.policy_id == 1
    assert spec.simulation_2.policy_id == 2


def test_builds_economy_spec_from_models(orm_session):
    first = add_simulation(
        orm_session,
        population_type="geography",
        population_id="ca",
        policy_id=10,
    )
    second = add_simulation(
        orm_session,
        population_type="geography",
        population_id="ca",
        policy_id=11,
    )
    report = add_report(orm_session, first, second)

    spec = service.build_report_spec(
        report, first, second, dataset="cps", options={"foo": "bar"}
    )

    assert isinstance(spec, EconomyReportSpec)
    assert spec.report_kind == "economy_comparison"
    assert spec.region == "ca"
    assert spec.dataset == "cps"
    assert spec.options == {"foo": "bar"}


def test_sets_and_gets_report_spec_as_python_json(orm_session):
    simulation = add_simulation(orm_session)
    report = add_report(orm_session, simulation)
    spec = service.build_report_spec(report, simulation)

    assert service.set_report_spec(
        orm_session, report.id, spec, report_spec_status="explicit"
    )
    loaded = service.get_report_spec(orm_session, report.id)

    assert report.report_spec_json == spec.model_dump()
    assert report.report_spec_schema_version == 1
    assert report.report_spec_status == "explicit"
    assert loaded == spec


def test_rejects_missing_linked_simulation(orm_session):
    report = ReportOutput(
        country_id="us",
        simulation_1_id=999,
        simulation_2_id=None,
        api_version="1",
        status="pending",
        year="2026",
    )
    orm_session.add(report)
    orm_session.flush()
    spec = HouseholdReportSpec.model_validate(
        {
            "country_id": "us",
            "report_kind": "household_single",
            "time_period": "2026",
            "simulation_1": {
                "population_type": "household",
                "population_id": "household-1",
                "policy_id": 1,
            },
        }
    )

    with pytest.raises(ValueError, match="references missing simulation #999"):
        service.set_report_spec(orm_session, report.id, spec, "explicit")


def test_rejects_mismatched_country(orm_session):
    simulation = add_simulation(orm_session, country_id="uk")
    report = add_report(orm_session, simulation, country_id="us")

    with pytest.raises(ValueError, match="country must match"):
        service.build_report_spec(report, simulation)


def test_rejects_mismatched_comparison_population(orm_session):
    first = add_simulation(orm_session, population_id="household-1")
    second = add_simulation(orm_session, population_id="household-2", policy_id=2)
    report = add_report(orm_session, first, second)

    with pytest.raises(ValueError, match="matching household IDs"):
        service.build_report_spec(report, first, second)


def test_rejects_unsupported_schema_version_and_status(orm_session):
    simulation = add_simulation(orm_session)
    report = add_report(orm_session, simulation)
    spec = service.build_report_spec(report, simulation)

    with pytest.raises(ValueError, match="Unsupported report spec status"):
        service.set_report_spec(orm_session, report.id, spec, "unknown")
    with pytest.raises(ValueError, match="Unsupported report spec schema version"):
        service.set_report_spec(
            orm_session, report.id, spec, "explicit", schema_version=2
        )
