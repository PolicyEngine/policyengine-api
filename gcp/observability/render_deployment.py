"""Render Google Cloud deployment templates from validated environment values."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "rendered"
PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
TEMPLATES = (
    ("iam.template.yaml", "iam.yaml"),
    ("workload-inventory.template.yaml", "workload-inventory.yaml"),
    ("log-routing.template.yaml", "log-routing.yaml"),
    ("alerts.template.yaml", "alerts.yaml"),
    ("dashboard.template.json", "dashboard.json"),
    ("collector/service.template.yaml", "collector/service.yaml"),
)
VALIDATORS = {
    "OBSERVABILITY_PROJECT_ID": re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]"),
    "OBSERVABILITY_PROJECT_NUMBER": re.compile(r"[1-9][0-9]{5,29}"),
    "API_PROJECT_ID": re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]"),
    "SIMULATION_ENTRY_PROJECT_ID": re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]"),
    "MODAL_WORKSPACE_ID": re.compile(r"ac-[A-Za-z0-9_-]+"),
}


def _deployment_values() -> dict[str, str]:
    missing = sorted(name for name in VALIDATORS if not os.getenv(name))
    if missing:
        raise SystemExit("Missing deployment variables: " + ", ".join(missing))

    values = {name: os.environ[name] for name in VALIDATORS}
    invalid = sorted(
        name
        for name, pattern in VALIDATORS.items()
        if pattern.fullmatch(values[name]) is None
    )
    if invalid:
        raise SystemExit("Invalid deployment variables: " + ", ".join(invalid))
    return values


def _render(content: str, values: dict[str, str]) -> str:
    referenced = set(PLACEHOLDER.findall(content))
    unknown = sorted(referenced - values.keys())
    if unknown:
        raise SystemExit("Unknown deployment variables: " + ", ".join(unknown))
    rendered = PLACEHOLDER.sub(lambda match: values[match.group(1)], content)
    unresolved = sorted(set(PLACEHOLDER.findall(rendered)))
    if unresolved:
        raise SystemExit("Unresolved deployment variables: " + ", ".join(unresolved))
    return rendered


def render_deployment(output_directory: Path) -> None:
    values = _deployment_values()
    rendered_files = []
    for source_name, output_name in TEMPLATES:
        source = ROOT / source_name
        rendered_files.append((output_name, _render(source.read_text(), values)))

    for output_name, content in rendered_files:
        destination = output_directory / output_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        destination.chmod(0o600)

    variable_names = ", ".join(sorted(values))
    print(f"Rendered {len(TEMPLATES)} deployment files using: {variable_names}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination for rendered files (default: gcp/observability/rendered)",
    )
    arguments = parser.parse_args()
    render_deployment(arguments.output_dir)


if __name__ == "__main__":
    main()
