"""v1 simulations, with every write mirrored into the simulation's run history."""

import json
import uuid
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Simulation, SimulationRun
from policyengine_api.services.final_results import changes_stored_result
from policyengine_api.spm import validate_spm_calculation_provenance
from policyengine_api.utils.population_identity import (
    canonical_numeric_household_id,
    population_id_matches,
)


class InvalidSimulationIdError(Exception):
    """Raised when a simulation ID is not a non-negative integer."""


class SimulationAlreadyCompleteError(Exception):
    """Raised when an update would change the result of a complete simulation."""


@dataclass(frozen=True)
class SimulationCreateResult:
    """A simulation and whether this call created it."""

    simulation: Simulation
    created: bool


class SimulationService:
    """Simulation operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """Use this session factory, or the application's v1 one if omitted."""
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    @staticmethod
    def _select_simulation(
        session: Session,
        simulation_id: int,
        country_id: str | None = None,
        *,
        for_update: bool = False,
    ) -> Simulation | None:
        statement = select(Simulation).where(Simulation.id == simulation_id)
        if country_id is not None:
            statement = statement.where(Simulation.country_id == country_id)
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _latest_successful_run_id(runs: list[SimulationRun]) -> str | None:
        return next((run.id for run in runs if run.status == "complete"), None)

    @staticmethod
    def _has_stale_spm_output(output: object) -> bool:
        """Identify stored results that predate the compact SPM receipt contract.

        Legacy SPM output cannot be translated safely: it may omit the exact
        forecast or runtime identity now required to verify a result. Treating
        it as stale makes the existing simulation pending and clears its output
        so the calculation is run again with the installed certified bundle.
        Output without any SPM fields remains valid non-SPM output.
        """
        if not isinstance(output, dict):
            return False
        if "spm_config" in output:
            return True
        if "spm_provenance" not in output:
            return False
        try:
            validate_spm_calculation_provenance(output["spm_provenance"])
        except ValueError:
            return True
        return False

    @staticmethod
    def _computed_by_older_model(simulation: Simulation) -> bool:
        """Whether the stored result came from an older country model than this one.

        A version that cannot be compared counts as older when it differs.
        """
        stored = simulation.api_version
        installed = COUNTRY_PACKAGE_VERSIONS.get(simulation.country_id)
        try:
            return Version(str(stored)) < Version(str(installed))
        except InvalidVersion:
            return stored != installed

    @classmethod
    def _has_final_result(cls, simulation: Simulation) -> bool:
        """Whether the simulation holds a complete result that updates cannot change.

        A complete result from the installed country model, or a newer one, is
        final. A complete record without output holds no result. Stale SPM output
        is not final: it is reset to pending and run again. Nor is a result from an
        older model, which a browser that runs the calculation again replaces with
        the installed model's.
        """
        return (
            simulation.status == "complete"
            and simulation.output is not None
            and not cls._has_stale_spm_output(simulation.output)
            and not cls._computed_by_older_model(simulation)
        )

    def ensure_simulation_dual_write_state(
        self,
        session: Session,
        simulation_id: int,
        country_id: str | None = None,
    ) -> Simulation:
        """Lock a simulation and bring its spec and run rows up to date in ``session``.

        Resets a stale SPM output to pending, records the simulation spec,
        creates the first run or updates the active one (else the newest), and
        sets the active and latest successful run ids. Raises ValueError if the
        simulation is missing.
        """
        simulation = self._select_simulation(
            session,
            simulation_id,
            country_id,
            for_update=True,
        )
        if simulation is None:
            msg = f"Simulation #{simulation_id} not found"
            raise ValueError(msg)

        if self._has_stale_spm_output(simulation.output):
            simulation.status = "pending"
            simulation.output = None
            simulation.error_message = None

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
        simulation.active_run_id = (
            runs[0].id if simulation.status in {"pending", "running"} else None
        )
        if simulation.status == "complete" and latest_successful is None:
            latest_successful = runs[0].id
        simulation.latest_successful_run_id = latest_successful
        session.flush()
        return simulation

    @staticmethod
    def _lock_existing_simulation(
        session: Session,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> Simulation | None:
        """Return the simulation for this identity, locking it for update, or None."""
        exact_identity = Simulation.population_id == population_id
        statement = (
            select(Simulation)
            .where(
                Simulation.country_id == country_id,
                population_id_matches(
                    Simulation.population_id,
                    country_id,
                    population_id,
                    population_type,
                ),
                Simulation.population_type == population_type,
                Simulation.policy_id == policy_id,
            )
            .order_by(exact_identity.desc(), Simulation.id.desc())
            .with_for_update()
        )
        return session.scalar(statement)

    def _create_simulation(
        self,
        session: Session,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> Simulation:
        simulation = Simulation(
            country_id=country_id,
            api_version=COUNTRY_PACKAGE_VERSIONS.get(country_id),
            population_id=population_id,
            population_type=population_type,
            policy_id=policy_id,
            status="pending",
        )
        session.add(simulation)
        session.flush()
        return self.ensure_simulation_dual_write_state(
            session,
            simulation.id,
            country_id,
        )

    def get_or_create_simulation(
        self,
        country_id: str,
        population_id: str,
        population_type: str,
        policy_id: int,
    ) -> SimulationCreateResult:
        """Return the simulation for this population and policy, creating it if needed.

        A numeric household ID also matches its stored aliases. Stored output that
        predates the current SPM receipt format is cleared and the simulation reset to
        pending, so it is calculated again.
        """
        numeric_identity = canonical_numeric_household_id(
            country_id, population_id, population_type
        )
        if numeric_identity is not None:
            # JSON clients can send an integer. Keep SQL comparison textual so
            # MySQL cannot coerce a nonnumeric stored ID into a numeric alias.
            population_id = str(population_id)
        # Linking is not serialized against household edits: there are none. A
        # household is immutable once created, so simulation and report identity
        # stay valid without a lock, and a locking read of an id that does not
        # exist yet takes an InnoDB gap lock that blocks unrelated household
        # inserts into that range. Repeated creates are serialized by the
        # locking read of `simulations` below, which is what they contend on;
        # the household row was never the exclusion for a non-numeric id.
        with self._sessions.begin() as session:
            simulation = self._lock_existing_simulation(
                session,
                country_id,
                population_id,
                population_type,
                policy_id,
            )
            created = simulation is None
            if simulation is None:
                simulation = self._create_simulation(
                    session,
                    country_id,
                    numeric_identity or population_id,
                    population_type,
                    policy_id,
                )
            else:
                simulation = self.ensure_simulation_dual_write_state(
                    session,
                    simulation.id,
                    country_id,
                )
            return SimulationCreateResult(simulation=simulation, created=created)

    def get_simulation(
        self,
        country_id: str,
        simulation_id: int,
    ) -> Simulation | None:
        """Return the simulation in this country, or None.

        Raise InvalidSimulationIdError if ``simulation_id`` is not a non-negative int.
        """
        if type(simulation_id) is not int or simulation_id < 0:
            msg = f"Invalid simulation ID: {simulation_id}. Must be a positive integer."
            raise InvalidSimulationIdError(msg)
        with self._sessions() as session:
            return self._select_simulation(session, simulation_id, country_id)

    @staticmethod
    def _update_values(
        status: str | None,
        output: dict | list | str | None,
        error_message: str | None,
    ) -> dict:
        """Return the fields an update sets, with output decoded and its SPM checked.

        Null fields, and output that decodes to null, set nothing. Raise ValueError
        for a completion without output, output with legacy ``spm_config`` or an
        invalid SPM receipt.
        """
        values = {
            key: value
            for key, value in {
                "status": status,
                "output": output,
                "error_message": error_message,
            }.items()
            if value is not None
        }
        if isinstance(values.get("output"), str):
            values["output"] = json.loads(values["output"])
            if values["output"] is None:
                del values["output"]
        if values.get("status") == "complete" and "output" not in values:
            msg = "output is required when status is 'complete'"
            raise ValueError(msg)
        output_value = values.get("output")
        if isinstance(output_value, dict) and "spm_config" in output_value:
            msg = "Completed simulation output must not include legacy spm_config"
            raise ValueError(msg)
        if isinstance(output_value, dict) and "spm_provenance" in output_value:
            receipt = validate_spm_calculation_provenance(
                output_value["spm_provenance"]
            )
            values["output"] = {
                **output_value,
                "spm_provenance": receipt.model_dump(mode="json", by_alias=True),
            }
        return values

    def update_simulation(
        self,
        country_id: str,
        simulation_id: int,
        status: str | None = None,
        output: dict | list | str | None = None,
        error_message: str | None = None,
    ) -> Simulation | None:
        """Apply the given status, output or error message and sync the run history.

        Return None when nothing was given; a JSON-encoded null output counts as
        none. An applied update restamps the simulation with the installed country
        package version. A complete result from the installed model is final: an
        update that only repeats it returns the simulation unchanged, and one that
        would change it raises SimulationAlreadyCompleteError. Raise ValueError for
        a completion without output, output with legacy ``spm_config`` or an
        invalid SPM receipt, and LookupError if the simulation does not exist.
        """
        values = self._update_values(status, output, error_message)
        if not values:
            return None
        with self._sessions.begin() as session:
            simulation = self._select_simulation(
                session,
                simulation_id,
                country_id,
                for_update=True,
            )
            if simulation is None:
                msg = f"Simulation #{simulation_id} not found"
                raise LookupError(msg)
            if self._has_final_result(simulation):
                if changes_stored_result(simulation, values):
                    msg = (
                        f"Simulation #{simulation_id} is complete; "
                        "its result cannot be changed"
                    )
                    raise SimulationAlreadyCompleteError(msg)
                return simulation
            for key, value in values.items():
                setattr(simulation, key, value)
            simulation.api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
            return self.ensure_simulation_dual_write_state(
                session,
                simulation_id,
                country_id,
            )
