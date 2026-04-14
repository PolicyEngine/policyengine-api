import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.engine.row import Row

from policyengine_api.data import database

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
    def _get_report_output_row(self, report_output_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def infer_report_kind(
        self,
        simulation_1: dict,
        simulation_2: dict | None = None,
    ) -> str:
        population_type = simulation_1["population_type"]
        if (
            simulation_2 is not None
            and simulation_2["population_type"] != population_type
        ):
            raise ValueError(
                "Simulation population types must match to build a report spec"
            )

        if population_type == "household":
            return (
                "household_comparison"
                if simulation_2 is not None
                else "household_single"
            )

        if population_type == "geography":
            return (
                "economy_comparison" if simulation_2 is not None else "economy_single"
            )

        raise ValueError(f"Unsupported simulation population type: {population_type}")

    def build_report_spec(
        self,
        report_output: dict,
        simulation_1: dict,
        simulation_2: dict | None = None,
        dataset: str = "default",
        target: Literal["general", "cliff"] = "general",
        options: dict[str, Any] | None = None,
    ) -> ReportSpec:
        report_kind = self.infer_report_kind(simulation_1, simulation_2)
        time_period = report_output["year"]

        if report_kind in HOUSEHOLD_REPORT_KINDS:
            return HouseholdReportSpec.model_validate(
                {
                    "country_id": report_output["country_id"],
                    "report_kind": report_kind,
                    "time_period": time_period,
                    "simulation_1": {
                        "population_type": simulation_1["population_type"],
                        "population_id": simulation_1["population_id"],
                        "policy_id": simulation_1["policy_id"],
                    },
                    "simulation_2": (
                        {
                            "population_type": simulation_2["population_type"],
                            "population_id": simulation_2["population_id"],
                            "policy_id": simulation_2["policy_id"],
                        }
                        if simulation_2 is not None
                        else None
                    ),
                }
            )

        return EconomyReportSpec.model_validate(
            {
                "country_id": report_output["country_id"],
                "report_kind": report_kind,
                "time_period": time_period,
                "region": simulation_1["population_id"],
                "baseline_policy_id": simulation_1["policy_id"],
                "reform_policy_id": (
                    simulation_2["policy_id"]
                    if simulation_2 is not None
                    else simulation_1["policy_id"]
                ),
                "dataset": dataset,
                "target": target,
                "options": options or {},
            }
        )

    def _parse_json_field(self, value: str | dict | None) -> dict | None:
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value

    def _parse_report_spec(self, report_kind: str, raw_spec: dict) -> ReportSpec:
        if report_kind in HOUSEHOLD_REPORT_KINDS:
            return HouseholdReportSpec.model_validate(raw_spec)
        if report_kind in ECONOMY_REPORT_KINDS:
            return EconomyReportSpec.model_validate(raw_spec)
        raise ValueError(f"Unsupported report kind: {report_kind}")

    def get_report_spec(self, report_output_id: int) -> ReportSpec | None:
        report_output = self._get_report_output_row(report_output_id)
        if report_output is None or report_output["report_spec_json"] is None:
            return None

        raw_spec = self._parse_json_field(report_output["report_spec_json"])
        return self._parse_report_spec(report_output["report_kind"], raw_spec)

    def set_report_spec(
        self,
        report_output_id: int,
        report_spec: ReportSpec,
        report_spec_status: Literal["explicit", "backfilled_assumed"],
        schema_version: int = REPORT_SPEC_SCHEMA_VERSION,
    ) -> bool:
        if report_spec_status not in REPORT_SPEC_STATUSES:
            raise ValueError(f"Unsupported report spec status: {report_spec_status}")

        report_output = self._get_report_output_row(report_output_id)
        if report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found")

        database.query(
            """
            UPDATE report_outputs
            SET report_kind = ?, report_spec_json = ?, report_spec_schema_version = ?, report_spec_status = ?
            WHERE id = ?
            """,
            (
                report_spec.report_kind,
                report_spec.model_dump_json(),
                schema_version,
                report_spec_status,
                report_output_id,
            ),
        )
        return True
