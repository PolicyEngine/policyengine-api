"""ORM data access objects for the existing v1 schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from datetime import datetime
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from policyengine_api.data.orm import SessionManager
from policyengine_api.data.v1_models import (
    Analysis,
    ComputedHousehold,
    Economy,
    Household,
    LegacyReportOutputAlias,
    Policy,
    ReformImpact,
    ReportOutput,
    ReportOutputRun,
    Simulation,
    SimulationRun,
    Tracer,
    UserProfile,
    UserPolicy,
)


def _mapping(model: Any) -> dict[str, Any]:
    return {
        column.name: getattr(model, column.name) for column in model.__table__.columns
    }


class PolicyDAO:
    def __init__(self, session: Session):
        self.session = session

    def get(self, country_id: str, policy_id: int) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.id == policy_id,
            )
        )
        return _mapping(model) if model else None

    def find_unique(
        self, country_id: str, policy_hash: str, label: str | None
    ) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.policy_hash == policy_hash,
                Policy.label == label,
            )
        )
        return _mapping(model) if model else None

    def search(self, country_id: str, query: str) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.label.contains(query, autoescape=True),
            )
        )
        return [_mapping(model) for model in models]

    def create(
        self,
        country_id: str,
        label: str | None,
        policy_json: Any,
        policy_hash: str,
        api_version: str,
    ) -> int:
        policy = Policy(
            country_id=country_id,
            label=label,
            api_version=api_version,
            policy_json=policy_json,
            policy_hash=policy_hash,
        )
        self.session.add(policy)
        self.session.flush()
        return policy.id


class HouseholdDAO:
    def __init__(self, session: Session):
        self.session = session

    def get(self, country_id: str, household_id: int) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(Household).where(
                Household.country_id == country_id,
                Household.id == household_id,
            )
        )
        return _mapping(model) if model else None

    def create(
        self,
        country_id: str,
        label: str | None,
        household_json: Any,
        household_hash: str,
        api_version: str,
    ) -> int:
        model = Household(
            country_id=country_id,
            label=label,
            api_version=api_version,
            household_json=household_json,
            household_hash=household_hash,
        )
        self.session.add(model)
        self.session.flush()
        return model.id

    def update(
        self,
        country_id: str,
        household_id: int,
        label: str | None,
        household_json: Any,
        household_hash: str,
        api_version: str,
    ) -> bool:
        model = self.session.scalar(
            select(Household).where(
                Household.country_id == country_id,
                Household.id == household_id,
            )
        )
        if model is None:
            return False
        model.label = label
        model.household_json = household_json
        model.household_hash = household_hash
        model.api_version = api_version
        return True


class ComputedHouseholdDAO:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **values: Any) -> None:
        self.session.add(ComputedHousehold(**values))

    def upsert(self, **values: Any) -> None:
        identity = (
            values["household_id"],
            values["policy_id"],
            values["country_id"],
        )
        model = self.session.get(ComputedHousehold, identity)
        if model is None:
            self.session.add(ComputedHousehold(**values))
            return
        for key, value in values.items():
            setattr(model, key, value)

    def get(
        self,
        household_id: int,
        policy_id: int,
        country_id: str,
        *,
        api_version: str | None = None,
    ) -> dict[str, Any] | None:
        statement = select(ComputedHousehold).where(
            ComputedHousehold.household_id == household_id,
            ComputedHousehold.policy_id == policy_id,
            ComputedHousehold.country_id == country_id,
        )
        if api_version is not None:
            statement = statement.where(ComputedHousehold.api_version == api_version)
        model = self.session.scalar(statement)
        return _mapping(model) if model else None


class UserDAO:
    def __init__(self, session: Session):
        self.session = session

    def create_profile(
        self,
        auth0_id: str,
        username: str | None,
        primary_country: str,
        user_since: int,
    ) -> int:
        model = UserProfile(
            auth0_id=auth0_id,
            username=username,
            primary_country=primary_country,
            user_since=user_since,
        )
        self.session.add(model)
        self.session.flush()
        return model.user_id

    def get_profile(
        self,
        *,
        user_id: int | None = None,
        auth0_id: str | None = None,
    ) -> dict[str, Any] | None:
        if user_id is None and auth0_id is None:
            return None
        condition = (
            UserProfile.user_id == user_id
            if user_id is not None
            else UserProfile.auth0_id == auth0_id
        )
        model = self.session.scalar(select(UserProfile).where(condition))
        return _mapping(model) if model else None

    def update_profile(self, user_id: int, **values: Any) -> bool:
        model = self.session.get(UserProfile, user_id)
        if model is None:
            return False
        for key, value in values.items():
            if value is not None:
                setattr(model, key, value)
        return True


class V1Repositories:
    """Repositories bound to the same operation-scoped Session."""

    def __init__(self, session: Session):
        self.session = session
        self.policies = PolicyDAO(session)
        self.households = HouseholdDAO(session)
        self.users = UserDAO(session)
        self.computed_households = ComputedHouseholdDAO(session)
        self.user_policies = UserPolicyDAO(session)
        self.economies = EconomyDAO(session)
        self.analyses = AnalysisDAO(session)
        self.reform_impacts = ReformImpactDAO(session)
        self.tracers = TracerDAO(session)
        self.simulations = SimulationDAO(session)
        self.reports = ReportDAO(session)


class V1UnitOfWork:
    """Create one Session and transaction boundary per logical operation."""

    def __init__(self, sessions: SessionManager):
        self.sessions = sessions

    @contextmanager
    def read(self) -> Iterator[V1Repositories]:
        with self.sessions.session() as session:
            yield V1Repositories(session)

    @contextmanager
    def transaction(self) -> Iterator[V1Repositories]:
        with self.sessions.transaction() as session:
            yield V1Repositories(session)


_runtime_unit_of_work: dict[bool, V1UnitOfWork] = {}


def runtime_v1_unit_of_work(*, local: bool = False) -> V1UnitOfWork:
    """Return the process-local unit of work for the selected v1 database."""

    if local not in _runtime_unit_of_work:
        from policyengine_api.data.orm import build_v1_session_manager

        _runtime_unit_of_work[local] = V1UnitOfWork(
            build_v1_session_manager(local=local)
        )
    return _runtime_unit_of_work[local]


class UserPolicyDAO:
    IDENTITY_FIELDS = (
        "country_id",
        "reform_id",
        "baseline_id",
        "user_id",
        "year",
        "geography",
        "reform_label",
        "baseline_label",
        "dataset",
    )

    def __init__(self, session: Session):
        self.session = session

    def create(self, **values: Any) -> int:
        model = UserPolicy(**values)
        self.session.add(model)
        self.session.flush()
        return model.id

    def find_unique(self, **values: Any) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(UserPolicy).where(
                *(
                    getattr(UserPolicy, field) == values[field]
                    for field in self.IDENTITY_FIELDS
                )
            )
        )
        return _mapping(model) if model else None

    def get(self, user_policy_id: int) -> dict[str, Any] | None:
        model = self.session.get(UserPolicy, user_policy_id)
        return _mapping(model) if model else None

    def list_for_user(self, country_id: str, user_id: str) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(UserPolicy).where(
                UserPolicy.country_id == country_id,
                UserPolicy.user_id == user_id,
            )
        )
        return [_mapping(model) for model in models]

    def update(self, user_policy_id: int, values: dict[str, Any]) -> bool:
        model = self.session.get(UserPolicy, user_policy_id)
        if model is None:
            return False
        for key, value in values.items():
            setattr(model, key, value)
        return True


class EconomyDAO:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **values: Any) -> int:
        model = Economy(**values)
        self.session.add(model)
        self.session.flush()
        return model.economy_id

    def get(self, economy_id: int) -> dict[str, Any] | None:
        model = self.session.get(Economy, economy_id)
        return _mapping(model) if model else None


class AnalysisDAO:
    def __init__(self, session: Session):
        self.session = session

    def get(self, prompt: str) -> str | None:
        model = self.session.scalar(
            select(Analysis)
            .where(
                Analysis.prompt == prompt,
                Analysis.status.in_(("complete", "ok")),
            )
            .order_by(Analysis.prompt_id.desc())
        )
        return model.analysis if model else None

    def store(self, prompt: str, analysis: str | None, status: str) -> int:
        model = Analysis(prompt=prompt, analysis=analysis, status=status)
        self.session.add(model)
        self.session.flush()
        return model.prompt_id


class ReformImpactDAO:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **values: Any) -> int:
        model = ReformImpact(**values)
        self.session.add(model)
        self.session.flush()
        return model.reform_impact_id

    def find(self, *, execution_id: str) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(ReformImpact)
            .where(ReformImpact.execution_id == execution_id)
            .order_by(ReformImpact.reform_impact_id.desc())
        )
        return _mapping(model) if model else None

    @staticmethod
    def _scope(statement, **filters: Any):
        return statement.where(
            *(getattr(ReformImpact, key) == value for key, value in filters.items())
        )

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        models = self.session.scalars(
            self._scope(select(ReformImpact), **filters).order_by(
                ReformImpact.start_time.desc()
            )
        )
        return [_mapping(model) for model in models]

    def list_recent(self, limit: int) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(ReformImpact).order_by(ReformImpact.start_time.desc()).limit(limit)
        )
        return [_mapping(model) for model in models]

    def list_by_options_hash(
        self, options_hash: str, options_hash_prefix: str, **filters: Any
    ) -> list[dict[str, Any]]:
        statement = self._scope(select(ReformImpact), **filters).where(
            or_(
                ReformImpact.options_hash == options_hash,
                ReformImpact.options_hash.like(options_hash_prefix, escape="\\"),
            )
        )
        models = self.session.scalars(
            statement.order_by(
                (ReformImpact.options_hash == options_hash).desc(),
                ReformImpact.start_time.desc(),
            )
        )
        return [_mapping(model) for model in models]

    def delete_computing(self, **filters: Any) -> None:
        self.session.execute(
            self._scope(delete(ReformImpact), **filters).where(
                ReformImpact.status == "computing"
            )
        )

    def set_message(self, message: str, **filters: Any) -> bool:
        models = self.session.scalars(
            self._scope(select(ReformImpact), **filters)
        ).all()
        for model in models:
            model.message = message
        return bool(models)

    def fail(self, execution_id: str, message: str, finished_at: datetime) -> bool:
        model = self.session.scalar(
            select(ReformImpact)
            .where(ReformImpact.execution_id == execution_id)
            .order_by(ReformImpact.reform_impact_id.desc())
        )
        if model is None:
            return False
        model.status = "error"
        model.message = message
        model.end_time = finished_at
        return True

    def complete(self, execution_id: str, result: Any, finished_at: datetime) -> bool:
        model = self.session.scalar(
            select(ReformImpact)
            .where(ReformImpact.execution_id == execution_id)
            .order_by(ReformImpact.reform_impact_id.desc())
        )
        if model is None:
            return False
        model.status = "ok"
        model.message = "Completed"
        model.reform_impact_json = result
        model.end_time = finished_at
        return True


class TracerDAO:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        household_id: int,
        policy_id: int,
        country_id: str,
        api_version: str,
        tracer_output: Any,
    ) -> int:
        model = Tracer(
            household_id=household_id,
            policy_id=policy_id,
            country_id=country_id,
            api_version=api_version,
            tracer_output=tracer_output,
        )
        self.session.add(model)
        self.session.flush()
        return model.id

    def get(
        self,
        household_id: int,
        policy_id: int,
        country_id: str,
        api_version: str | None = None,
    ) -> dict[str, Any] | None:
        statement = select(Tracer).where(
            Tracer.household_id == household_id,
            Tracer.policy_id == policy_id,
            Tracer.country_id == country_id,
        )
        if api_version is not None:
            statement = statement.where(Tracer.api_version == api_version)
        model = self.session.scalar(statement.order_by(Tracer.id.desc()))
        return _mapping(model) if model else None


class SimulationDAO:
    def __init__(self, session: Session):
        self.session = session

    def get(
        self, simulation_id: int, country_id: str | None = None
    ) -> dict[str, Any] | None:
        statement = select(Simulation).where(Simulation.id == simulation_id)
        if country_id is not None:
            statement = statement.where(Simulation.country_id == country_id)
        model = self.session.scalar(statement)
        return _mapping(model) if model else None

    @staticmethod
    def get_in_session(
        session, simulation_id: int, country_id: str | None = None
    ) -> dict[str, Any] | None:
        statement = select(Simulation).where(Simulation.id == simulation_id)
        if country_id is not None:
            statement = statement.where(Simulation.country_id == country_id)
        model = session.scalar(statement)
        return _mapping(model) if model else None

    def create(self, **values: Any) -> int:
        model = Simulation(**values)
        self.session.add(model)
        self.session.flush()
        return model.id

    def find_latest(self, **filters: Any) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(Simulation)
            .where(
                *(getattr(Simulation, key) == value for key, value in filters.items())
            )
            .order_by(Simulation.id.desc())
        )
        return _mapping(model) if model else None

    @staticmethod
    def _latest_successful_run_id(runs: list[SimulationRun]) -> str | None:
        return next((run.id for run in runs if run.status == "complete"), None)

    def ensure_dual_write_state_in_session(
        self,
        session,
        simulation_id: int,
        country_id: str | None = None,
    ) -> dict[str, Any]:
        statement = (
            select(Simulation).where(Simulation.id == simulation_id).with_for_update()
        )
        if country_id is not None:
            statement = statement.where(Simulation.country_id == country_id)
        simulation = session.scalar(statement)
        if simulation is None:
            raise ValueError(f"Simulation #{simulation_id} not found")

        spec = {
            "country_id": simulation.country_id,
            "population_id": simulation.population_id,
            "population_type": simulation.population_type,
            "policy_id": simulation.policy_id,
        }
        simulation.simulation_spec_json = spec
        simulation.simulation_spec_schema_version = 1
        runs = list(
            session.scalars(
                select(SimulationRun)
                .where(SimulationRun.simulation_id == simulation_id)
                .order_by(SimulationRun.run_sequence.desc())
            )
        )
        if not runs:
            run = SimulationRun(
                id=str(uuid.uuid4()),
                simulation_id=simulation_id,
                run_sequence=1,
                status=simulation.status,
                output=simulation.output,
                error_message=simulation.error_message,
                trigger_type="initial",
                simulation_spec_snapshot_json=spec,
                country_package_version=simulation.api_version,
            )
            session.add(run)
            session.flush()
            runs = [run]
        else:
            mutable = next(
                (run for run in runs if run.id == simulation.active_run_id),
                runs[0],
            )
            mutable.status = simulation.status
            mutable.output = simulation.output
            mutable.error_message = simulation.error_message
            mutable.simulation_spec_snapshot_json = spec
            mutable.country_package_version = simulation.api_version

        latest_successful = self._latest_successful_run_id(runs)
        if simulation.status in {"pending", "running"}:
            simulation.active_run_id = runs[0].id
        else:
            simulation.active_run_id = None
        if simulation.status == "complete" and latest_successful is None:
            latest_successful = runs[0].id
        simulation.latest_successful_run_id = latest_successful
        session.flush()
        return _mapping(simulation)

    def ensure_dual_write_state(
        self, simulation_id: int, country_id: str | None = None
    ) -> dict[str, Any]:
        return self.ensure_dual_write_state_in_session(
            self.session, simulation_id, country_id
        )

    def create_or_get_with_sync(
        self,
        *,
        sync_callback,
        **values: Any,
    ) -> dict[str, Any]:
        filters = {
            key: values[key]
            for key in (
                "country_id",
                "population_id",
                "population_type",
                "policy_id",
            )
        }
        model = self.session.scalar(
            select(Simulation)
            .where(
                *(getattr(Simulation, key) == value for key, value in filters.items())
            )
            .order_by(Simulation.id.desc())
            .with_for_update()
        )
        if model is None:
            model = Simulation(**values)
            self.session.add(model)
            self.session.flush()
        return sync_callback(
            self.session,
            model.id,
            country_id=model.country_id,
        )

    def update_with_sync(
        self,
        simulation_id: int,
        country_id: str,
        values: dict[str, Any],
        sync_callback,
    ) -> dict[str, Any]:
        model = self.session.scalar(
            select(Simulation)
            .where(
                Simulation.id == simulation_id,
                Simulation.country_id == country_id,
            )
            .with_for_update()
        )
        if model is None:
            raise ValueError(f"Simulation #{simulation_id} not found")
        for key, value in values.items():
            setattr(model, key, value)
        self.session.flush()
        return sync_callback(
            self.session,
            simulation_id,
            country_id=country_id,
        )

    def update(self, simulation_id: int, **values: Any) -> bool:
        model = self.session.get(Simulation, simulation_id)
        if model is None:
            return False
        for key, value in values.items():
            setattr(model, key, value)
        return True

    def create_run(
        self, simulation_id: int, *, run_id: str, **values: Any
    ) -> dict[str, Any]:
        parent = self.session.scalar(
            select(Simulation).where(Simulation.id == simulation_id).with_for_update()
        )
        if parent is None:
            raise LookupError(f"Simulation {simulation_id} does not exist")
        sequence = (
            self.session.scalar(
                select(func.max(SimulationRun.run_sequence)).where(
                    SimulationRun.simulation_id == simulation_id
                )
            )
            or 0
        ) + 1
        model = SimulationRun(
            id=run_id,
            simulation_id=simulation_id,
            run_sequence=sequence,
            **values,
        )
        self.session.add(model)
        self.session.flush()
        return _mapping(model)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        model = self.session.get(SimulationRun, run_id)
        return _mapping(model) if model else None

    def list_runs(self, simulation_id: int) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(SimulationRun)
            .where(SimulationRun.simulation_id == simulation_id)
            .order_by(SimulationRun.run_sequence.desc())
        )
        return [_mapping(model) for model in models]


class ReportDAO:
    def __init__(self, session: Session):
        self.session = session

    def get(
        self, report_output_id: int, country_id: str | None = None
    ) -> dict[str, Any] | None:
        statement = select(ReportOutput).where(ReportOutput.id == report_output_id)
        if country_id is not None:
            statement = statement.where(ReportOutput.country_id == country_id)
        model = self.session.scalar(statement)
        return _mapping(model) if model else None

    def get_for_update(
        self, report_output_id: int, country_id: str | None = None
    ) -> dict[str, Any] | None:
        statement = (
            select(ReportOutput)
            .where(ReportOutput.id == report_output_id)
            .with_for_update()
        )
        if country_id is not None:
            statement = statement.where(ReportOutput.country_id == country_id)
        model = self.session.scalar(statement)
        return _mapping(model) if model else None

    def find_latest(self, **filters: Any) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(ReportOutput)
            .where(
                *(getattr(ReportOutput, key) == value for key, value in filters.items())
            )
            .order_by(ReportOutput.id.desc())
        )
        return _mapping(model) if model else None

    def create(self, **values: Any) -> int:
        model = ReportOutput(**values)
        self.session.add(model)
        self.session.flush()
        return model.id

    def update(self, report_output_id: int, **values: Any) -> bool:
        model = self.session.get(ReportOutput, report_output_id)
        if model is None:
            return False
        for key, value in values.items():
            setattr(model, key, value)
        return True

    def create_run(
        self, report_output_id: int, *, run_id: str, **values: Any
    ) -> dict[str, Any]:
        parent = self.session.scalar(
            select(ReportOutput)
            .where(ReportOutput.id == report_output_id)
            .with_for_update()
        )
        if parent is None:
            raise LookupError(f"Report output {report_output_id} does not exist")
        sequence = (
            self.session.scalar(
                select(func.max(ReportOutputRun.run_sequence)).where(
                    ReportOutputRun.report_output_id == report_output_id
                )
            )
            or 0
        ) + 1
        model = ReportOutputRun(
            id=run_id,
            report_output_id=report_output_id,
            run_sequence=sequence,
            **values,
        )
        self.session.add(model)
        self.session.flush()
        return _mapping(model)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        model = self.session.get(ReportOutputRun, run_id)
        return _mapping(model) if model else None

    def update_run(self, run_id: str, **values: Any) -> bool:
        model = self.session.get(ReportOutputRun, run_id)
        if model is None:
            return False
        for key, value in values.items():
            setattr(model, key, value)
        return True

    def list_runs(self, report_output_id: int) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(ReportOutputRun)
            .where(ReportOutputRun.report_output_id == report_output_id)
            .order_by(ReportOutputRun.run_sequence.desc())
        )
        return [_mapping(model) for model in models]

    def set_alias(self, legacy_id: int, canonical_id: int) -> None:
        model = self.session.get(LegacyReportOutputAlias, legacy_id)
        if model is None:
            self.session.add(
                LegacyReportOutputAlias(
                    legacy_report_output_id=legacy_id,
                    canonical_report_output_id=canonical_id,
                )
            )
        else:
            model.canonical_report_output_id = canonical_id

    def get_alias(self, legacy_id: int) -> dict[str, Any] | None:
        model = self.session.get(LegacyReportOutputAlias, legacy_id)
        return _mapping(model) if model else None
