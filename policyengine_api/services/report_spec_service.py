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
    def _validate_schema_version(self, schema_version: int | None) -> None:
        if schema_version != REPORT_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported report spec schema version: {schema_version}"
            )

    def _get_report_output_row(self, report_output_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM report_outputs WHERE id = ?",
            (report_output_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _get_simulation_row(self, simulation_id: int) -> dict | None:
        row: Row | None = database.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _get_linked_simulations(self, report_output: dict) -> tuple[dict, dict | None]:
        simulation_1 = self._get_simulation_row(report_output["simulation_1_id"])
        if simulation_1 is None:
            raise ValueError(
                "Report output references missing simulation "
                f"#{report_output['simulation_1_id']}"
            )

        simulation_2 = None
        if report_output["simulation_2_id"] is not None:
            simulation_2 = self._get_simulation_row(report_output["simulation_2_id"])
            if simulation_2 is None:
                raise ValueError(
                    "Report output references missing simulation "
                    f"#{report_output['simulation_2_id']}"
                )

        return simulation_1, simulation_2

    def _validate_report_simulation_linkage(
        self,
        report_output: dict,
        simulation_1: dict,
        simulation_2: dict | None = None,
    ) -> None:
        if simulation_1.get("id") != report_output["simulation_1_id"]:
            raise ValueError(
                "Simulation 1 must match report_output.simulation_1_id to build a "
                "report spec"
            )

        report_simulation_2_id = report_output["simulation_2_id"]
        if report_simulation_2_id is None:
            if simulation_2 is not None:
                raise ValueError("Report output does not reference a second simulation")
            return

        if simulation_2 is None:
            raise ValueError(
                "Report output requires a second simulation to build a comparison "
                "report spec"
            )
        if simulation_2.get("id") != report_simulation_2_id:
            raise ValueError(
                "Simulation 2 must match report_output.simulation_2_id to build a "
                "report spec"
            )

    def _validate_report_country(
        self,
        report_output: dict,
        simulation_1: dict,
        simulation_2: dict | None = None,
    ) -> None:
        report_country_id = report_output["country_id"]
        if simulation_1["country_id"] != report_country_id:
            raise ValueError(
                "Simulation 1 country must match report output country to build a "
                "report spec"
            )
        if simulation_2 is not None and simulation_2["country_id"] != report_country_id:
            raise ValueError(
                "Simulation 2 country must match report output country to build a "
                "report spec"
            )

    def _build_household_report_spec(
        self,
        report_output: dict,
        report_kind: str,
        simulation_1: dict,
        simulation_2: dict | None,
        time_period: str,
    ) -> HouseholdReportSpec:
        if simulation_1["population_type"] != "household":
            raise ValueError("Household report specs require household simulations")
        if (
            simulation_2 is not None
            and simulation_2["population_id"] != simulation_1["population_id"]
        ):
            raise ValueError(
                "Household comparison report specs require matching household IDs"
            )

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

    def _build_economy_report_spec(
        self,
        report_output: dict,
        report_kind: str,
        simulation_1: dict,
        simulation_2: dict | None,
        time_period: str,
        dataset: str,
        target: Literal["general", "cliff"],
        options: dict[str, Any] | None,
    ) -> EconomyReportSpec:
        if simulation_1["population_type"] != "geography":
            raise ValueError("Economy report specs require geography simulations")
        if (
            simulation_2 is not None
            and simulation_2["population_id"] != simulation_1["population_id"]
        ):
            raise ValueError(
                "Economy comparison report specs require matching geography IDs"
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

    def _validate_report_spec_matches_row(
        self, report_output: dict, report_spec: ReportSpec
    ) -> None:
        simulation_1, simulation_2 = self._get_linked_simulations(report_output)
        inferred_report_kind = self.infer_report_kind(simulation_1, simulation_2)
        if report_spec.country_id != report_output["country_id"]:
            raise ValueError("Report spec country must match report output country")
        if report_spec.time_period != report_output["year"]:
            raise ValueError("Report spec time_period must match report output year")
        if report_spec.report_kind != inferred_report_kind:
            raise ValueError("Report spec kind must match linked simulations")

        if isinstance(report_spec, HouseholdReportSpec):
            if report_spec.simulation_1.model_dump() != {
                "population_type": simulation_1["population_type"],
                "population_id": simulation_1["population_id"],
                "policy_id": simulation_1["policy_id"],
            }:
                raise ValueError(
                    "Report spec simulation_1 must match linked simulation 1"
                )

            expected_simulation_2 = (
                {
                    "population_type": simulation_2["population_type"],
                    "population_id": simulation_2["population_id"],
                    "policy_id": simulation_2["policy_id"],
                }
                if simulation_2 is not None
                else None
            )
            actual_simulation_2 = (
                report_spec.simulation_2.model_dump()
                if report_spec.simulation_2 is not None
                else None
            )
            if actual_simulation_2 != expected_simulation_2:
                raise ValueError(
                    "Report spec simulation_2 must match linked simulation 2"
                )
            return

        expected_region = simulation_1["population_id"]
        expected_baseline_policy_id = simulation_1["policy_id"]
        expected_reform_policy_id = (
            simulation_2["policy_id"]
            if simulation_2 is not None
            else simulation_1["policy_id"]
        )

        if report_spec.region != expected_region:
            raise ValueError("Report spec region must match linked simulations")
        if report_spec.baseline_policy_id != expected_baseline_policy_id:
            raise ValueError(
                "Report spec baseline_policy_id must match linked simulations"
            )
        if report_spec.reform_policy_id != expected_reform_policy_id:
            raise ValueError(
                "Report spec reform_policy_id must match linked simulations"
            )

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
        self._validate_report_simulation_linkage(
            report_output, simulation_1, simulation_2
        )
        report_kind = self.infer_report_kind(simulation_1, simulation_2)
        time_period = report_output["year"]
        self._validate_report_country(report_output, simulation_1, simulation_2)

        if report_kind in HOUSEHOLD_REPORT_KINDS:
            return self._build_household_report_spec(
                report_output=report_output,
                report_kind=report_kind,
                simulation_1=simulation_1,
                simulation_2=simulation_2,
                time_period=time_period,
            )

        return self._build_economy_report_spec(
            report_output=report_output,
            report_kind=report_kind,
            simulation_1=simulation_1,
            simulation_2=simulation_2,
            time_period=time_period,
            dataset=dataset,
            target=target,
            options=options,
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

        self._validate_schema_version(report_output["report_spec_schema_version"])
        raw_spec = self._parse_json_field(report_output["report_spec_json"])
        report_spec = self._parse_report_spec(report_output["report_kind"], raw_spec)
        self._validate_report_spec_matches_row(report_output, report_spec)
        return report_spec

    def set_report_spec(
        self,
        report_output_id: int,
        report_spec: ReportSpec,
        report_spec_status: Literal["explicit", "backfilled_assumed"],
        schema_version: int = REPORT_SPEC_SCHEMA_VERSION,
    ) -> bool:
        if report_spec_status not in REPORT_SPEC_STATUSES:
            raise ValueError(f"Unsupported report spec status: {report_spec_status}")
        self._validate_schema_version(schema_version)

        report_output = self._get_report_output_row(report_output_id)
        if report_output is None:
            raise ValueError(f"Report output #{report_output_id} not found")
        self._validate_report_spec_matches_row(report_output, report_spec)

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
