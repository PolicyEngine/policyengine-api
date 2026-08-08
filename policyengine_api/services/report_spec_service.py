import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import ReportOutput, Simulation


REPORT_SPEC_SCHEMA_VERSION = 1
REPORT_SPEC_STATUSES = {"explicit", "backfilled_assumed"}
HOUSEHOLD_REPORT_KINDS = {"household_single", "household_comparison"}
ECONOMY_REPORT_KINDS = {"economy_single", "economy_comparison"}


class ReportSimulationInput(BaseModel):
    population_type: Literal["household", "geography"]
    population_id: str
    policy_id: int


class HouseholdReportSpec(BaseModel):
    country_id: str
    report_kind: Literal["household_single", "household_comparison"]
    time_period: str
    simulation_1: ReportSimulationInput
    simulation_2: ReportSimulationInput | None = None


class EconomyReportSpec(BaseModel):
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
    @staticmethod
    def _validate_schema_version(schema_version: int | None) -> None:
        if schema_version != REPORT_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported report spec schema version: {schema_version}"
            )

    @staticmethod
    def _get_linked_simulations(
        session: Session, report_output: ReportOutput
    ) -> tuple[Simulation, Simulation | None]:
        simulation_1 = session.get(Simulation, report_output.simulation_1_id)
        if simulation_1 is None:
            raise ValueError(
                "Report output references missing simulation "
                f"#{report_output.simulation_1_id}"
            )
        simulation_2 = None
        if report_output.simulation_2_id is not None:
            simulation_2 = session.get(Simulation, report_output.simulation_2_id)
            if simulation_2 is None:
                raise ValueError(
                    "Report output references missing simulation "
                    f"#{report_output.simulation_2_id}"
                )
        return simulation_1, simulation_2

    @staticmethod
    def _validate_report_simulation_linkage(
        report_output: ReportOutput,
        simulation_1: Simulation,
        simulation_2: Simulation | None,
    ) -> None:
        if simulation_1.id != report_output.simulation_1_id:
            raise ValueError(
                "Simulation 1 must match report_output.simulation_1_id to build a "
                "report spec"
            )
        if report_output.simulation_2_id is None:
            if simulation_2 is not None:
                raise ValueError("Report output does not reference a second simulation")
            return
        if simulation_2 is None:
            raise ValueError(
                "Report output requires a second simulation to build a comparison "
                "report spec"
            )
        if simulation_2.id != report_output.simulation_2_id:
            raise ValueError(
                "Simulation 2 must match report_output.simulation_2_id to build a "
                "report spec"
            )

    @staticmethod
    def _validate_report_country(
        report_output: ReportOutput,
        simulation_1: Simulation,
        simulation_2: Simulation | None,
    ) -> None:
        if simulation_1.country_id != report_output.country_id:
            raise ValueError(
                "Simulation 1 country must match report output country to build a "
                "report spec"
            )
        if (
            simulation_2 is not None
            and simulation_2.country_id != report_output.country_id
        ):
            raise ValueError(
                "Simulation 2 country must match report output country to build a "
                "report spec"
            )

    @staticmethod
    def infer_report_kind(
        simulation_1: Simulation, simulation_2: Simulation | None = None
    ) -> str:
        population_type = simulation_1.population_type
        if simulation_2 is not None and simulation_2.population_type != population_type:
            raise ValueError(
                "Simulation population types must match to build a report spec"
            )
        if population_type == "household":
            return "household_comparison" if simulation_2 else "household_single"
        if population_type == "geography":
            return "economy_comparison" if simulation_2 else "economy_single"
        raise ValueError(f"Unsupported simulation population type: {population_type}")

    def build_report_spec(
        self,
        report_output: ReportOutput,
        simulation_1: Simulation,
        simulation_2: Simulation | None = None,
        dataset: str = "default",
        target: Literal["general", "cliff"] = "general",
        options: dict[str, Any] | None = None,
    ) -> ReportSpec:
        self._validate_report_simulation_linkage(
            report_output, simulation_1, simulation_2
        )
        self._validate_report_country(report_output, simulation_1, simulation_2)
        report_kind = self.infer_report_kind(simulation_1, simulation_2)
        if report_kind in HOUSEHOLD_REPORT_KINDS:
            if (
                simulation_2 is not None
                and simulation_2.population_id != simulation_1.population_id
            ):
                raise ValueError(
                    "Household comparison report specs require matching household IDs"
                )
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
            raise ValueError(
                "Economy comparison report specs require matching geography IDs"
            )
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
            raise ValueError("Report spec must match the linked report and simulations")

    @staticmethod
    def _parse_report_spec(report_kind: str, raw_spec: dict) -> ReportSpec:
        if report_kind in HOUSEHOLD_REPORT_KINDS:
            return HouseholdReportSpec.model_validate(raw_spec)
        if report_kind in ECONOMY_REPORT_KINDS:
            return EconomyReportSpec.model_validate(raw_spec)
        raise ValueError(f"Unsupported report kind: {report_kind}")

    def get_report_spec(
        self, session: Session, report_output_id: int
    ) -> ReportSpec | None:
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
        if report_spec_status not in REPORT_SPEC_STATUSES:
            raise ValueError(f"Unsupported report spec status: {report_spec_status}")
        self._validate_schema_version(schema_version)
        report_output = session.get(ReportOutput, report_output_id)
        if report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found")
        self._validate_report_spec_matches_model(session, report_output, report_spec)
        report_output.report_kind = report_spec.report_kind
        report_output.report_spec_json = report_spec.model_dump()
        report_output.report_spec_schema_version = schema_version
        report_output.report_spec_status = report_spec_status
        return True
