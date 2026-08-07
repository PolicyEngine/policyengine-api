"""ORM data access objects for the existing v1 schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from policyengine_api.data.orm import SessionManager
from policyengine_api.data.v1_models import (
    ComputedHousehold,
    Household,
    LegacyReportOutputAlias,
    Policy,
    ReportOutput,
    ReportOutputRun,
    Simulation,
    SimulationRun,
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


class V1DAOs:
    """DAOs bound to the same operation-scoped Session."""

    def __init__(self, session: Session):
        self.session = session
        self.policies = PolicyDAO(session)
        self.households = HouseholdDAO(session)
        self.computed_households = ComputedHouseholdDAO(session)
        self.simulations = SimulationDAO(session)
        self.reports = ReportDAO(session)


class V1UnitOfWork:
    """Create one Session and transaction boundary per logical operation."""

    def __init__(self, sessions: SessionManager):
        self.sessions = sessions

    @contextmanager
    def read(self) -> Iterator[V1DAOs]:
        with self.sessions.session() as session:
            yield V1DAOs(session)

    @contextmanager
    def transaction(self) -> Iterator[V1DAOs]:
        with self.sessions.transaction() as session:
            yield V1DAOs(session)


_runtime_unit_of_work: dict[bool, V1UnitOfWork] = {}


def runtime_v1_unit_of_work(*, local: bool = False) -> V1UnitOfWork:
    """Return the process-local unit of work for the selected v1 database."""

    if local not in _runtime_unit_of_work:
        from policyengine_api.data.orm import build_v1_session_manager

        _runtime_unit_of_work[local] = V1UnitOfWork(
            build_v1_session_manager(local=local)
        )
    return _runtime_unit_of_work[local]


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
