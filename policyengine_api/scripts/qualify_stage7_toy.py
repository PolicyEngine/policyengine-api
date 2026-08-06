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
    AnalysisDAO,
    HouseholdDAO,
    PolicyDAO,
    ReformImpactDAO,
    ReportDAO,
    SimulationDAO,
    TracerDAO,
    UserDAO,
)
from policyengine_api.data.v1_models import V1Base


def compare_stage7_schema(database_url: str) -> list:
    """Return metadata drift without stamping or mutating the target database."""

    engine = create_engine(database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True},
        )
        return compare_metadata(context, V1Base.metadata)


def qualify_stage7_toy(database_url: str) -> dict[str, bool]:
    """Upgrade and exercise every migrated v1 persistence domain."""

    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    sessions = SessionManager(engine)
    policies = PolicyDAO(sessions)
    households = HouseholdDAO(sessions)
    users = UserDAO(sessions)
    simulations = SimulationDAO(sessions)
    reports = ReportDAO(sessions)
    analyses = AnalysisDAO(sessions)
    tracers = TracerDAO(sessions)
    impacts = ReformImpactDAO(sessions)

    policy_id = policies.create("us", "Toy", {}, "toy-policy", "toy")
    household_id = households.create("us", "Toy", {}, "toy-household", "toy")
    user_id = users.create_profile("toy|user", "toy-user", "us", 1)
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
    analyses.store("toy prompt", "toy answer", "complete")
    tracers.create(household_id, policy_id, "us", "toy", ["toy trace"])
    impact_id = impacts.create(
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

    return {
        "alembic_head": "alembic_version" in inspect(engine).get_table_names(),
        "policy": policies.get("us", policy_id) is not None,
        "household": households.get("us", household_id) is not None,
        "user": users.get_profile(user_id=user_id) is not None,
        "simulation": simulations.get_run("toy-simulation-run") is not None,
        "report": reports.get_run("toy-report-run") is not None,
        "analysis": analyses.get("toy prompt") == "toy answer",
        "tracer": tracers.get(household_id, policy_id, "us") is not None,
        "reform_impact": impacts.find(execution_id="toy-impact")["reform_impact_id"]
        == impact_id,
    }
