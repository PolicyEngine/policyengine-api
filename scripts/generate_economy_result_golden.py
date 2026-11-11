r"""Store economy results with the simulation service's own writer, as test data.

The Public API rebuilds a report run's economy result from the rows the
simulation service writes (``policyengine_api.services.v2.stored_reports.
economy_results``). This script runs that writer, ``report_run_result`` in
PolicyEngine/policyengine-sim-api's ``libs/policyengine-stage12-persistence``,
at one commit of a local clone, on the economy results
``tests.fixtures.economy_results`` builds and on variants of them. It writes
each result, as the writer's own model serializes it, with the report run
columns and table rows the writer returns, to
``tests/fixtures/economy_result_rows_golden.json``, which names the commit.
``tests/unit/v2/test_economy_result_rebuild.py`` rebuilds every result from
those rows, so a change in the writer fails that test once this file is
generated again from a newer commit.

Run it from the repository root, naming the clone and the commit::

    uv run --frozen --extra dev python scripts/generate_economy_result_golden.py \
        --simulation-repository ../policyengine-sim-api --commit origin/main

The writer's modules are read with ``git show`` at the commit into a
temporary directory; the clone itself is not changed. US districts are
numbered with .py's state FIPS codes and at-large states, as the simulation
service numbers them. Row IDs, which the writer draws at random, are left
out.
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixtures.economy_results import (  # noqa: E402  # the repository root is on the path only from here
    uk_economy_result,
    us_economy_result,
)

OUTPUT = REPO_ROOT / "tests" / "fixtures" / "economy_result_rows_golden.json"
WRITER = (
    "libs/policyengine-stage12-persistence/src/policyengine_stage12_persistence/"
    "report_run_results.py"
)
# Each module the writer imports, by its path in the simulation service's
# repository; each package gets an empty ``__init__.py``.
WRITER_MODULES = {
    "policyengine_stage12_persistence/report_run_results.py": WRITER,
    "policyengine_stage12_persistence/report_run_tables.py": (
        "libs/policyengine-stage12-persistence/src/policyengine_stage12_persistence/"
        "report_run_tables.py"
    ),
    **{
        f"policyengine_simulation_contract/{module}.py": (
            "libs/policyengine-simulation-contract/src/"
            f"policyengine_simulation_contract/{module}.py"
        )
        for module in ("macro_output", "spm", "json_types")
    },
}
RUN_IDS = {
    "report_run_id": UUID("00000000-0000-4000-8000-00000000c001"),
    "baseline_simulation_run_id": UUID("00000000-0000-4000-8000-00000000c002"),
    "reform_simulation_run_id": UUID("00000000-0000-4000-8000-00000000c003"),
}


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _district(name: str, **values: float) -> dict[str, Any]:
    return {
        "district": name,
        "average_household_income_change": values.get("average", 5.0),
        "relative_household_income_change": values.get("relative", 0.0004),
        "winner_percentage": 0.25,
        "loser_percentage": 0.25,
        "no_change_percentage": 0.5,
        "population": values.get("population", 700_000.0),
    }


def us_labour_supply_deciles_and_at_large_districts() -> dict[str, Any]:
    """Return a US result shaped as .py reports some states and deciles.

    .py's labour supply averages also cover deciles -1 and 0, which have no
    relative response, and DC and Wyoming each have one at-large district,
    which the writer stores as district 0. Districts are in GEOID order, the
    order the rebuild returns them in.
    """
    output = us_economy_result()
    average = output["labor_supply_response"]["decile"]["average"]
    average["income"] = {-1: 0.5, 0: 0.7, **average["income"]}
    average["substitution"] = {-1: -0.5, 0: -0.7, **average["substitution"]}
    districts = output["congressional_district_impact"]["districts"]
    california = [district["district"] for district in districts].index("CA-12")
    districts.insert(california + 1, _district("DC-01", average=-1.5))
    districts.append(_district("WY-01", population=580_000.0))
    return output


def us_negative_budget() -> dict[str, Any]:
    """Return a US result whose reform loses revenue and raises spending."""
    output = us_economy_result()
    output["budget"].update(
        tax_revenue_impact=-1500.0,
        state_tax_revenue_impact=-250.0,
        benefit_spending_impact=500.0,
        budgetary_impact=-2000.0,
    )
    return output


CASES = (
    ("us", "us", us_economy_result),
    ("uk", "uk", uk_economy_result),
    (
        "us-labour-supply-deciles-and-at-large-districts",
        "us",
        us_labour_supply_deciles_and_at_large_districts,
    ),
    ("us-negative-budget", "us", us_negative_budget),
)


def _json_value(value: object) -> object:
    """Return a row's value as JSON holds it: a UUID as its string."""
    if isinstance(value, UUID):
        return str(value)
    return value


def generate(repository: Path, commit: str) -> dict[str, Any]:
    """Run the writer at ``commit`` on every case; return what it stored."""
    resolved = _git(repository, "rev-parse", f"{commit}^{{commit}}").strip()
    writer_changed = _git(
        repository, "log", "-1", "--format=%H", resolved, "--", WRITER
    ).strip()
    with tempfile.TemporaryDirectory() as source:
        for module, path in WRITER_MODULES.items():
            target = Path(source) / module
            target.parent.mkdir(parents=True, exist_ok=True)
            (target.parent / "__init__.py").touch()
            target.write_text(_git(repository, "show", f"{resolved}:{path}"))
        sys.path.insert(0, source)
        writer = importlib.import_module(
            "policyengine_stage12_persistence.report_run_results"
        )
        contract = importlib.import_module(
            "policyengine_simulation_contract.macro_output"
        )
        # .py's US data, as the simulation service's district codes use it.
        from policyengine.countries.us.data import AT_LARGE_STATES, US_STATE_FIPS

        district_codes = writer.DistrictCodes(
            state_fips={state: int(fips) for state, fips in US_STATE_FIPS.items()},
            at_large_states=frozenset(AT_LARGE_STATES),
        )
        cases = []
        for name, country, build in CASES:
            output = build()
            stored = writer.report_run_result(
                copy.deepcopy(output),
                # The writer reads only the three IDs of its ReportRunIds.
                run_ids=SimpleNamespace(**RUN_IDS),
                country=country,
                district_codes=district_codes if country == "us" else None,
            )
            cases.append(
                {
                    "name": name,
                    "country": country,
                    "output": contract.SingleYearMacroOutput.model_validate(
                        output
                    ).model_dump(mode="json"),
                    "report_run_columns": dict(stored.report_run_columns),
                    "rows": {
                        rows.table.name: [
                            {
                                column: _json_value(value)
                                for column, value in row.items()
                                if column != "id"
                            }
                            for row in rows.rows
                        ]
                        for rows in stored.rows
                    },
                }
            )
    return {
        "generated_by": "scripts/generate_economy_result_golden.py",
        "writer": {
            "repository": "PolicyEngine/policyengine-sim-api",
            "commit": resolved,
            "path": WRITER,
            "last_changed_in": writer_changed,
        },
        "run_ids": {key: str(value) for key, value in RUN_IDS.items()},
        "cases": cases,
    }


def main() -> None:
    """Generate the fixture from the named clone and commit."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--simulation-repository", type=Path, required=True)
    parser.add_argument("--commit", default="origin/main")
    arguments = parser.parse_args()
    payload = generate(arguments.simulation_repository, arguments.commit)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {len(payload['cases'])} results from {payload['writer']['commit']}")


if __name__ == "__main__":
    main()
