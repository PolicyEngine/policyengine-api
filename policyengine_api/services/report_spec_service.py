"""Explicit specifications of what each v1 report output calculates."""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import ReportOutput, Simulation
from policyengine_api.utils.population_identity import canonical_numeric_household_id

REPORT_SPEC_SCHEMA_VERSION = 1
REPORT_SPEC_STATUSES = {"explicit", "backfilled_assumed"}
HOUSEHOLD_REPORT_KINDS = {"household_single", "household_comparison"}
ECONOMY_REPORT_KINDS = {"economy_single", "economy_comparison"}


class ReportSimulationInput(BaseModel):
    """The population and policy of one simulation in a household report."""

    population_type: Literal["household", "geography"]
    population_id: str
    policy_id: int


class HouseholdReportSpec(BaseModel):
    """A household report: one household under one policy, or under two to compare."""

    country_id: str
    report_kind: Literal["household_single", "household_comparison"]
    time_period: str
    simulation_1: ReportSimulationInput
    simulation_2: ReportSimulationInput | None = None


class EconomyReportSpec(BaseModel):
    """An economy report: one region under a baseline and a reform policy.

    A single-policy report uses the same policy for both.
    """

    country_id: str
    report_kind: Literal["economy_single", "economy_comparison"]
    time_period: str
    region: str
    baseline_policy_id: int
    reform_policy_id: int
    dataset: str = "default"
    target: Literal["general", "cliff"] = "general"
    options: dict[str, Any] = Field(default_factory=dict)


ReportSpec = HouseholdReportSpec | EconomyReportSpec


class ReportSpecService:
    """Service that builds, checks and stores report specs for v1 report outputs."""

    @staticmethod
    def _validate_schema_version(schema_version: int | None) -> None:
        if schema_version != REPORT_SPEC_SCHEMA_VERSION:
            msg = f"Unsupported report spec schema version: {schema_version}"
            raise ValueError(msg)

    @staticmethod
    def _get_linked_simulations(
        session: Session, report_output: ReportOutput
    ) -> tuple[Simulation, Simulation | None]:
        simulation_1 = session.get(Simulation, report_output.simulation_1_id)
        if simulation_1 is None:
            msg = (
                "Report output references missing simulation "
                f"#{report_output.simulation_1_id}"
            )
            raise ValueError(msg)
        simulation_2 = None
        if report_output.simulation_2_id is not None:
            simulation_2 = session.get(Simulation, report_output.simulation_2_id)
            if simulation_2 is None:
                msg = (
                    "Report output references missing simulation "
                    f"#{report_output.simulation_2_id}"
                )
                raise ValueError(msg)
        return simulation_1, simulation_2

    @staticmethod
    def _validate_report_simulation_linkage(
        report_output: ReportOutput,
        simulation_1: Simulation,
        simulation_2: Simulation | None,
    ) -> None:
        if simulation_1.id != report_output.simulation_1_id:
            msg = (
                "Simulation 1 must match report_output.simulation_1_id to build a "
                "report spec"
            )
            raise ValueError(msg)
        if report_output.simulation_2_id is None:
            if simulation_2 is not None:
                msg = "Report output does not reference a second simulation"
                raise ValueError(msg)
            return
        if simulation_2 is None:
            msg = (
                "Report output requires a second simulation to build a comparison "
                "report spec"
            )
            raise ValueError(msg)
        if simulation_2.id != report_output.simulation_2_id:
            msg = (
                "Simulation 2 must match report_output.simulation_2_id to build a "
                "report spec"
            )
            raise ValueError(msg)

    @staticmethod
    def _validate_report_country(
        report_output: ReportOutput,
        simulation_1: Simulation,
        simulation_2: Simulation | None,
    ) -> None:
        if simulation_1.country_id != report_output.country_id:
            msg = (
                "Simulation 1 country must match report output country to build a "
                "report spec"
            )
            raise ValueError(msg)
        if (
            simulation_2 is not None
            and simulation_2.country_id != report_output.country_id
        ):
            msg = (
                "Simulation 2 country must match report output country to build a "
                "report spec"
            )
            raise ValueError(msg)

    @staticmethod
    def infer_report_kind(
        simulation_1: Simulation, simulation_2: Simulation | None = None
    ) -> str:
        """Return the report kind implied by the simulations' population type and count.

        Raise ValueError if the two simulations' population types differ or are unknown.
        """
        population_type = simulation_1.population_type
        if simulation_2 is not None and simulation_2.population_type != population_type:
            msg = "Simulation population types must match to build a report spec"
            raise ValueError(msg)
        if population_type == "household":
            return "household_comparison" if simulation_2 else "household_single"
        if population_type == "geography":
            return "economy_comparison" if simulation_2 else "economy_single"
        msg = f"Unsupported simulation population type: {population_type}"
        raise ValueError(msg)

    def build_report_spec(
        self,
        report_output: ReportOutput,
        simulation_1: Simulation,
        simulation_2: Simulation | None = None,
        dataset: str = "default",
        target: Literal["general", "cliff"] = "general",
        options: dict[str, Any] | None = None,
    ) -> ReportSpec:
        """Build the spec implied by a report output and its linked simulations.

        Raise ValueError if the simulations do not match the report's simulation IDs or
        country, or if a comparison's simulations cover different households or regions.
        """
        self._validate_report_simulation_linkage(
            report_output, simulation_1, simulation_2
        )
        self._validate_report_country(report_output, simulation_1, simulation_2)
        report_kind = self.infer_report_kind(simulation_1, simulation_2)
        if report_kind in HOUSEHOLD_REPORT_KINDS:
            if simulation_2 is not None:
                household_ids = [
                    canonical_numeric_household_id(
                        simulation.country_id,
                        simulation.population_id,
                        simulation.population_type,
                    )
                    or simulation.population_id
                    for simulation in (simulation_1, simulation_2)
                ]
                if household_ids[0] != household_ids[1]:
                    msg = (
                        "Household comparison report specs require matching "
                        "household IDs"
                    )
                    raise ValueError(msg)
            return HouseholdReportSpec(
                country_id=report_output.country_id,
                report_kind=report_kind,
                time_period=report_output.year,
                simulation_1=ReportSimulationInput(
                    population_type=simulation_1.population_type,
                    population_id=simulation_1.population_id,
                    policy_id=simulation_1.policy_id,
                ),
                simulation_2=(
                    ReportSimulationInput(
                        population_type=simulation_2.population_type,
                        population_id=simulation_2.population_id,
                        policy_id=simulation_2.policy_id,
                    )
                    if simulation_2
                    else None
                ),
            )
        if (
            simulation_2 is not None
            and simulation_2.population_id != simulation_1.population_id
        ):
            msg = "Economy comparison report specs require matching geography IDs"
            raise ValueError(msg)
        return EconomyReportSpec(
            country_id=report_output.country_id,
            report_kind=report_kind,
            time_period=report_output.year,
            region=simulation_1.population_id,
            baseline_policy_id=simulation_1.policy_id,
            reform_policy_id=(
                simulation_2.policy_id if simulation_2 else simulation_1.policy_id
            ),
            dataset=dataset,
            target=target,
            options=options or {},
        )

    def _validate_report_spec_matches_model(
        self,
        session: Session,
        report_output: ReportOutput,
        report_spec: ReportSpec,
    ) -> None:
        simulation_1, simulation_2 = self._get_linked_simulations(
            session, report_output
        )
        expected = self.build_report_spec(
            report_output,
            simulation_1,
            simulation_2,
            dataset=(
                report_spec.dataset
                if isinstance(report_spec, EconomyReportSpec)
                else "default"
            ),
            target=(
                report_spec.target
                if isinstance(report_spec, EconomyReportSpec)
                else "general"
            ),
            options=(
                report_spec.options
                if isinstance(report_spec, EconomyReportSpec)
                else None
            ),
        )
        if report_spec != expected:
            msg = "Report spec must match the linked report and simulations"
            raise ValueError(msg)

    @staticmethod
    def _parse_report_spec(report_kind: str, raw_spec: dict) -> ReportSpec:
        if report_kind in HOUSEHOLD_REPORT_KINDS:
            return HouseholdReportSpec.model_validate(raw_spec)
        if report_kind in ECONOMY_REPORT_KINDS:
            return EconomyReportSpec.model_validate(raw_spec)
        msg = f"Unsupported report kind: {report_kind}"
        raise ValueError(msg)

    def get_report_spec(
        self, session: Session, report_output_id: int
    ) -> ReportSpec | None:
        """Return the stored spec for a report output, or None if it has none.

        Raise ValueError if the stored spec has an unsupported schema version or no
        longer matches the report's linked simulations.
        """
        report_output = session.get(ReportOutput, report_output_id)
        if report_output is None or report_output.report_spec_json is None:
            return None
        self._validate_schema_version(report_output.report_spec_schema_version)
        raw_spec = report_output.report_spec_json
        if isinstance(raw_spec, str):
            # Existing databases may contain pre-ORM JSON text. New writes below
            # always assign Python objects and leave conversion to SQLAlchemy.
            raw_spec = json.loads(raw_spec)
        report_spec = self._parse_report_spec(report_output.report_kind, raw_spec)
        self._validate_report_spec_matches_model(session, report_output, report_spec)
        return report_spec

    def set_report_spec(
        self,
        session: Session,
        report_output_id: int,
        report_spec: ReportSpec,
        report_spec_status: Literal["explicit", "backfilled_assumed"],
        schema_version: int = REPORT_SPEC_SCHEMA_VERSION,
    ) -> bool:
        """Store a report spec after checking it matches the linked simulations.

        Raise ValueError for an unknown status or schema version, a missing report, or a
        mismatched spec. Always return True; the caller owns the transaction.
        """
        if report_spec_status not in REPORT_SPEC_STATUSES:
            msg = f"Unsupported report spec status: {report_spec_status}"
            raise ValueError(msg)
        self._validate_schema_version(schema_version)
        report_output = session.get(ReportOutput, report_output_id)
        if report_output is None:
            msg = f"Report output #{report_output_id} not found"
            raise ValueError(msg)
        self._validate_report_spec_matches_model(session, report_output, report_spec)
        report_output.report_kind = report_spec.report_kind
        report_output.report_spec_json = report_spec.model_dump()
        report_output.report_spec_schema_version = schema_version
        report_output.report_spec_status = report_spec_status
        return True
