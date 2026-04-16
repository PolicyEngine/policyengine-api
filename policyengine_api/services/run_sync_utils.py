import json
from typing import Any


def serialize_json_field(value: dict[str, Any] | list[Any] | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def get_latest_successful_run_id(runs: list[dict]) -> str | None:
    for run in runs:
        if run["status"] == "complete":
            return run["id"]
    return None


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
