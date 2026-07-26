"""Export API v2 migration contracts into model-neutral review artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from policyengine_api.migration_registry import ROUTE_GROUPS  # noqa: E402
from tests.contract.registry import APP_V2_WORKFLOW_CONTRACTS  # noqa: E402


DEFAULT_JSON = REPO_ROOT / "docs" / "generated" / "migration_contracts.json"
DEFAULT_MARKDOWN = REPO_ROOT / "docs" / "engineering" / "migration-contracts.md"


def build_payload() -> dict[str, Any]:
    """Build the migration contract payload from typed registries."""

    route_groups = []
    for group in ROUTE_GROUPS:
        row = asdict(group)
        row["path_segments"] = list(row["path_segments"])
        route_groups.append(row)
    workflows = []
    request_count = 0

    for workflow in APP_V2_WORKFLOW_CONTRACTS:
        requests = []
        for request in workflow.requests:
            row = asdict(request)
            row["stable_response_fields"] = list(row["stable_response_fields"])
            row["optional_stable_response_fields"] = list(
                row["optional_stable_response_fields"]
            )
            requests.append(row)
        request_count += len(requests)
        workflows.append(
            {
                "name": workflow.name,
                "current_contract": workflow.current_contract,
                "future_owner_pr": workflow.future_owner_pr,
                "requests": requests,
            }
        )

    return {
        "version": 1,
        "metadata": {
            "route_group_count": len(route_groups),
            "workflow_count": len(workflows),
            "request_count": request_count,
            "db_entity_count": len(
                {group["db_entity"] for group in route_groups if group["db_entity"]}
            ),
            "sim_flow_count": len(
                {group["sim_flow"] for group in route_groups if group["sim_flow"]}
            ),
        },
        "route_groups": route_groups,
        "workflows": workflows,
    }


def json_text(payload: dict[str, Any]) -> str:
    """Return the canonical JSON text for a migration contract payload."""

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_markdown(payload: dict[str, Any]) -> str:
    """Render migration contracts as reviewer- and agent-readable Markdown."""

    lines = [
        "# Migration Contracts",
        "",
        "Generated from `policyengine_api/migration_registry.py` and "
        "`tests/contract/registry.py`.",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
    ]

    for key, value in payload["metadata"].items():
        label = key.replace("_", " ")
        lines.append(f"| {label} | {value} |")

    lines.extend(
        [
            "",
            "## Route Groups",
            "",
            "| Route group | Path segments | DB entity | Simulation flow |",
            "| --- | --- | --- | --- |",
        ]
    )

    for group in payload["route_groups"]:
        path_segments = ", ".join(f"`{segment}`" for segment in group["path_segments"])
        lines.append(
            f"| `{group['name']}` | {path_segments} | "
            f"`{group['db_entity'] or 'none'}` | "
            f"`{group['sim_flow'] or 'none'}` |"
        )

    lines.extend(["", "## App V2 Workflow Contracts", ""])
    for workflow in payload["workflows"]:
        lines.extend(
            [
                f"### `{workflow['name']}`",
                "",
                f"- Current contract: `{workflow['current_contract']}`",
                f"- Future owner: {workflow['future_owner_pr']}",
                "",
                "| Method | Path | Status | Route group | Stable response fields | Optional stable response fields |",
                "| --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for request in workflow["requests"]:
            fields = ", ".join(
                f"`{field}`" for field in request["stable_response_fields"]
            )
            optional_fields = ", ".join(
                f"`{field}`" for field in request["optional_stable_response_fields"]
            )
            lines.append(
                f"| `{request['method']}` | `{request['path']}` | "
                f"{request['expected_status']} | `{request['route_group']}` | "
                f"{fields} | {optional_fields} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    payload: dict[str, Any],
    *,
    json_path: Path = DEFAULT_JSON,
    markdown_path: Path = DEFAULT_MARKDOWN,
) -> None:
    """Write generated migration contract artifacts."""

    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_text(payload))
    markdown_path.write_text(render_markdown(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args(argv)

    payload = build_payload()
    write_outputs(
        payload,
        json_path=Path(args.json),
        markdown_path=Path(args.markdown),
    )
    print(
        "Exported "
        f"{payload['metadata']['workflow_count']} workflows and "
        f"{payload['metadata']['request_count']} requests to "
        f"{args.json} and {args.markdown}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
