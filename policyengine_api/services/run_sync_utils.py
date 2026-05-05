import json
from typing import Any


def parse_json_field(value: dict[str, Any] | list[Any] | str | None) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def serialize_json_field(value: dict[str, Any] | list[Any] | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def get_latest_successful_run_id(runs: list[dict]) -> str | None:
    for run in runs:
        if run["status"] == "complete":
            return run["id"]
    return None


def run_matches_report_result(run: dict, report_output: dict) -> bool:
    return (
        run["status"] == report_output["status"]
        and run.get("output") == report_output.get("output")
        and run.get("error_message") == report_output.get("error_message")
    )


def select_display_report_run(
    report_output: dict, runs_descending: list[dict]
) -> dict | None:
    active_run_id = report_output.get("active_run_id")
    if active_run_id is not None:
        for run in runs_descending:
            if run["id"] == active_run_id:
                return run

    if report_output["status"] == "error":
        for run in runs_descending:
            if run_matches_report_result(run, report_output):
                return run

    latest_successful_run_id = report_output.get("latest_successful_run_id")
    if latest_successful_run_id is not None:
        for run in runs_descending:
            if run["id"] == latest_successful_run_id:
                return run

    for run in runs_descending:
        if run_matches_report_result(run, report_output):
            return run

    return runs_descending[0] if runs_descending else None


def determine_parent_pointers(
    status: str, runs_descending: list[dict]
) -> tuple[str | None, str | None]:
    newest_run = runs_descending[0] if runs_descending else None
    latest_successful_run_id = get_latest_successful_run_id(runs_descending)

    if status in {"pending", "running"} and newest_run is not None:
        return newest_run["id"], latest_successful_run_id

    if status == "complete":
        return None, latest_successful_run_id or (
            newest_run["id"] if newest_run is not None else None
        )

    return None, latest_successful_run_id
