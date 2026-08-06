"""Run the Stage 7 ORM boundary against an isolated toy database."""

from datetime import datetime

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from policyengine_api.constants import REPO
from policyengine_api.data.orm import SessionManager
from policyengine_api.data.v1_daos import (
    ReportDAO,
    SimulationDAO,
    V1UnitOfWork,
)
from policyengine_api.data.v1_models import V1Base


def compare_stage7_schema(database_url: str) -> list:
    """Return metadata drift without stamping or mutating the target database."""

    engine = create_engine(database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        return compare_metadata(context, V1Base.metadata)


def qualify_stage7_toy(database_url: str) -> dict[str, bool]:
    """Upgrade and exercise every migrated v1 persistence domain."""

    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    sessions = SessionManager(engine)
    unit_of_work = V1UnitOfWork(sessions)
    simulations = SimulationDAO(sessions)
    reports = ReportDAO(sessions)

    with unit_of_work.transaction() as repositories:
        policy_id = repositories.policies.create("us", "Toy", {}, "toy-policy", "toy")
        household_id = repositories.households.create(
            "us", "Toy", {}, "toy-household", "toy"
        )
        user_id = repositories.users.create_profile("toy|user", "toy-user", "us", 1)
        repositories.computed_households.create(
            household_id=household_id,
            policy_id=policy_id,
            country_id="us",
            api_version="toy",
            computed_household_json={"qualified": True},
            status="complete",
        )
        user_policy_id = repositories.user_policies.create(
            country_id="us",
            reform_id=policy_id,
            reform_label="Toy",
            baseline_id=policy_id,
            baseline_label="Toy",
            user_id=str(user_id),
            year="2026",
            geography="us",
            dataset="default",
            number_of_provisions=0,
            api_version="toy",
            added_date=1,
            updated_date=1,
            budgetary_impact=None,
            type="reform",
        )
        economy_id = repositories.economies.create(
            policy_id=policy_id,
            country_id="us",
            region="us",
            time_period="2026",
            options_json={},
            options_hash="toy-economy",
            api_version="toy",
            economy_json={"qualified": True},
            status="complete",
            message=None,
        )
        repositories.analyses.store("toy prompt", "toy answer", "complete")
        repositories.tracers.create(household_id, policy_id, "us", "toy", ["toy trace"])
        impact_id = repositories.reform_impacts.create(
            baseline_policy_id=policy_id,
            reform_policy_id=policy_id,
            country_id="us",
            region="us",
            dataset="default",
            time_period="2026",
            options_json={},
            options_hash="toy-options",
            api_version="toy",
            reform_impact_json={},
            status="computing",
            start_time=datetime(2026, 1, 1),
            execution_id="toy-impact",
        )
    simulation_id = simulations.create(
        country_id="us",
        api_version="toy",
        population_id=str(household_id),
        population_type="household",
        policy_id=policy_id,
    )
    simulations.create_run(
        simulation_id,
        run_id="toy-simulation-run",
        status="pending",
        trigger_type="qualification",
    )
    report_id = reports.create(
        country_id="us",
        simulation_1_id=simulation_id,
        simulation_2_id=None,
        api_version="toy",
        year="2026",
    )
    reports.create_run(
        report_id,
        run_id="toy-report-run",
        status="pending",
        trigger_type="qualification",
    )
    reports.set_alias(900_001, report_id)

    with unit_of_work.read() as repositories:
        core_results = {
            "policy": repositories.policies.get("us", policy_id) is not None,
            "household": repositories.households.get("us", household_id) is not None,
            "user": repositories.users.get_profile(user_id=user_id) is not None,
            "computed_household": repositories.computed_households.get(
                household_id, policy_id, "us"
            )
            is not None,
            "user_policy": repositories.user_policies.get(user_policy_id) is not None,
            "economy": repositories.economies.get(economy_id) is not None,
            "analysis": repositories.analyses.get("toy prompt") == "toy answer",
            "tracer": repositories.tracers.get(household_id, policy_id, "us")
            is not None,
            "reform_impact": repositories.reform_impacts.find(
                execution_id="toy-impact"
            )["reform_impact_id"]
            == impact_id,
        }

    return {
        "alembic_head": "alembic_version" in inspect(engine).get_table_names(),
        **core_results,
        "simulation": simulations.get_run("toy-simulation-run") is not None,
        "report": reports.get_run("toy-report-run") is not None,
        "report_alias": reports.get_alias(900_001)["canonical_report_output_id"]
        == report_id,
    }
