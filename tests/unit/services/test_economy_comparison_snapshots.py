"""Characterization snapshots of the published economy comparison outputs.

``compare_economic_outputs`` and the UK area breakdowns build the economy impact
results the Public API returns and caches, so these tests pin their complete
output: every key in insertion order, every value with its type, and every float
bit for bit (by ``repr``). The inputs exercise the UK and US paths and each
branch of the comparison: budgets, deciles, poverty, inequality, labour supply,
wealth deciles (including their logged failure), cliffs, and the constituency and
local-authority breakdowns with every region filter and income-change bucket.

The expected values live in ``tests/data/economy_comparison_snapshots.json``. To
regenerate them after an intended change to the published output, run this module
with ``ECONOMY_COMPARISON_SNAPSHOTS=update`` and review the diff.
"""

import hashlib
import json
import logging
import math
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel

from policyengine_api.services import economy_comparison
from policyengine_api.services.economy_comparison import (
    compare_economic_outputs,
    uk_constituency_breakdown,
    uk_local_authority_breakdown,
)

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "economy_comparison_snapshots.json"
)
UPDATE_SNAPSHOTS = os.environ.get("ECONOMY_COMPARISON_SNAPSHOTS") == "update"

HOUSEHOLD_COUNT = 16
PERSON_COUNT = 18

# Reform-to-baseline income ratios chosen to land households (and areas made of
# one household) in each income-change bucket, on and around its boundaries.
INCOME_CHANGE_FACTORS = [
    1.1,
    1.02,
    1.0,
    0.98,
    0.9,
    1.0004,
    0.9996,
    1.05,
    0.95,
    1.001,
    0.999,
    1.0500001,
]

# One area per nation prefix and income-change bucket, one with an unknown prefix
# and a zero-income household (a NaN relative change), and a blended area.
AREA_CODES = [
    "E14000530",
    "S14000001",
    "W07000041",
    "N06000001",
    "E14000531",
    "K99999999",
    "S14000002",
    "N06000002",
]


def _household_values(build: Callable[[int], Any]) -> list:
    return [build(index) for index in range(HOUSEHOLD_COUNT)]


def _person_values(build: Callable[[int], Any]) -> list:
    return [build(index) for index in range(PERSON_COUNT)]


def _baseline_incomes() -> list[float]:
    incomes = _household_values(
        lambda index: 1000.0 * (index + 1) - (index % 3) * 137.5
    )
    incomes[5] = 0.0
    incomes[7] = -250.0
    return incomes


def _reform_incomes() -> list[float]:
    return [
        income * INCOME_CHANGE_FACTORS[index % len(INCOME_CHANGE_FACTORS)]
        for index, income in enumerate(_baseline_incomes())
    ]


def _income_deciles() -> list[float]:
    deciles = _household_values(lambda index: float(index % 10 + 1))
    deciles[15] = -1.0
    return deciles


def _economy(
    *,
    country_id: str,
    side: str,
    include_wealth: bool,
) -> dict[str, Any]:
    """Build one side of a general economy with household and person arrays."""
    is_reform = side == "reform"
    shift = 1 if is_reform else 0
    economy: dict[str, Any] = {
        "type": "general",
        "total_tax": 4.2e11 + shift * 3.25e9,
        "total_state_tax": 7.5e10 - shift * 1.1e8,
        "total_benefits": 2.9e11 + shift * 1.75e9,
        "total_net_income": 1.6e12 + shift * 2.5e9,
        "gini": 0.4217 - shift * 0.0031,
        "top_10_percent_share": 0.3125 - shift * 0.0042,
        "top_1_percent_share": 0.1033 - shift * 0.0011,
        "substitution_lsr": 1.25e8 * shift - 3.0e7,
        "income_lsr": -7.5e7 * shift + 1.0e7,
        "budgetary_impact_lsr": 4.0e8 * shift + 2.5e7,
        "weekly_hours": 1.18e9 + shift * 2.3e6,
        "weekly_hours_income_effect": 1.0e6 * shift - 2.0e5,
        "weekly_hours_substitution_effect": -3.0e6 * shift + 4.0e5,
        "household_net_income": _reform_incomes() if is_reform else _baseline_incomes(),
        "household_weight": _household_values(lambda index: 1.0 + (index % 4) * 0.5),
        "household_income_decile": _income_deciles(),
        "household_count_people": _household_values(lambda index: float(index % 4 + 1)),
        "substitution_lsr_hh": _household_values(
            lambda index: (index % 5 - 2) * 12.5 * (1.5 if is_reform else 1.0)
        ),
        "income_lsr_hh": _household_values(
            lambda index: (index % 3 - 1) * 7.25 * (0.5 if is_reform else 1.0)
        ),
        "employment_income_hh": _household_values(
            lambda index: 20000.0 + index * 1500.0
        ),
        "self_employment_income_hh": _household_values(
            lambda index: 0.0 if index % 2 else 3500.0 + index * 10.0
        ),
        "person_in_poverty": _person_values(
            lambda index: (index % 4 == 0) or (is_reform and index % 9 == 1)
        ),
        "person_in_deep_poverty": _person_values(
            lambda index: index % 8 == 0 and not (is_reform and index % 16 == 0)
        ),
        "person_weight": _person_values(lambda index: 1.0 + (index % 5) * 0.25),
        "age": _person_values(
            lambda index: [3, 17, 18, 30, 64, 65, 80, 12, 45][index % 9]
        ),
        "is_male": _person_values(lambda index: index % 2 == 0),
        "race": (
            _person_values(
                lambda index: ["WHITE", "BLACK", "HISPANIC", "OTHER"][index % 4]
            )
            if country_id == "us"
            else None
        ),
    }
    if country_id == "uk":
        economy["programs"] = {
            "income_tax": 2.4e11 + shift * 1.5e9,
            "national_insurance": 1.6e11 - shift * 2.0e8,
            "universal_credit": 6.1e10 + shift * 7.5e8,
        }
    if include_wealth:
        economy["household_wealth_decile"] = _household_values(
            lambda index: float((index + 3) % 10 + 1)
        )
    return economy


def _numpy_economy(economy: dict[str, Any]) -> dict[str, Any]:
    """Return the economy with every list replaced by a numpy array."""
    return {
        key: np.array(value) if isinstance(value, list) else value
        for key, value in economy.items()
    }


def _cliff_economy(*, side: str) -> dict[str, Any]:
    is_reform = side == "reform"
    return {
        "type": "cliff",
        "cliff_gap": 1.875e9 if is_reform else 2.0625e9,
        "cliff_share": 0.0421 if is_reform else 0.0457,
    }


def _area_names(prefix: str) -> pd.DataFrame:
    """Return an area table (code, name, x, y) in the shape of the UK datasets."""
    return pd.DataFrame(
        {
            "code": AREA_CODES,
            "name": [f"{prefix} {index}" for index in range(len(AREA_CODES))],
            "x": [float(index * 3 % 7) for index in range(len(AREA_CODES))],
            "y": [index * 2 - 5 for index in range(len(AREA_CODES))],
        }
    )


def _area_weights(seed_offset: int) -> np.ndarray:
    """Return area-by-household weights: one household per area, then blends."""
    weights = np.zeros((len(AREA_CODES), HOUSEHOLD_COUNT))
    for area_index in range(len(AREA_CODES)):
        weights[area_index, area_index] = 1.0
    weights[6] = [
        ((index + seed_offset) % 5) * 0.75 for index in range(HOUSEHOLD_COUNT)
    ]
    weights[7, 7] = 2.0
    return weights


class FakeUKDatasets:
    """Stand in for the Hugging Face downloads, the HDF5 weights and the CSVs."""

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self._weights = {
            "parliamentary_constituency_weights.h5": _area_weights(0),
            "local_authority_weights.h5": _area_weights(2),
        }
        self._names = {
            "constituencies_2024.csv": _area_names("Constituency"),
            "local_authorities_2021.csv": _area_names("Local authority"),
        }

    def download(self, *, repo: str, repo_filename: str) -> str:
        self.calls.append(["download", repo, repo_filename])
        return f"/fake/{repo}/{repo_filename}"

    def open_weights(self, path: str, mode: str) -> "FakeWeightsFile":
        self.calls.append(["h5py.File", path, mode])
        return FakeWeightsFile({"2025": self._weights[Path(path).name]})

    def read_names(self, path: str) -> pd.DataFrame:
        self.calls.append(["read_csv", path])
        return self._names[Path(path).name].copy()


class FakeWeightsFile:
    """A context manager that yields a mapping like an open ``h5py.File``."""

    def __init__(self, datasets: dict[str, np.ndarray]) -> None:
        self._datasets = datasets

    def __enter__(self) -> dict[str, np.ndarray]:
        return self._datasets

    def __exit__(self, *_exc_info: object) -> bool:
        return False


@pytest.fixture
def uk_datasets() -> Iterator[FakeUKDatasets]:
    datasets = FakeUKDatasets()
    with (
        patch.object(
            economy_comparison, "download_huggingface_dataset", datasets.download
        ),
        patch.object(economy_comparison.h5py, "File", datasets.open_weights),
        patch.object(economy_comparison.pd, "read_csv", datasets.read_names),
    ):
        yield datasets


class _RecordingHandler(logging.Handler):
    """Keep every record logged to the logger it is attached to."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def comparison_logs() -> Iterator[list[logging.LogRecord]]:
    """Record what the comparison module logs, whatever the global logging setup.

    Other tests load logging configuration that disables existing loggers, so
    the module logger is enabled and recorded directly for the test's duration.
    """
    records: list[logging.LogRecord] = []
    handler = _RecordingHandler(records)
    logger = economy_comparison.logger
    previous_state = (logger.disabled, logger.level)
    logger.disabled = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.disabled, previous_level = previous_state
        logger.setLevel(previous_level)


def _canonical_key(key: object) -> str:
    """Keep string keys as they are and tag any other key with its type."""
    if isinstance(key, str):
        return key
    return f"{type(key).__name__}:{key!r}"


def _canonical(value: object) -> object:
    """Return a JSON-safe form of ``value`` that keeps every type and float bit."""
    if isinstance(value, BaseModel):
        return {
            "model": type(value).__name__,
            "fields": _canonical(value.model_dump()),
        }
    if isinstance(value, dict):
        return {_canonical_key(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return {
            type(value).__name__: [_canonical(item) for item in value],
        }
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, float | np.floating):
        return f"{type(value).__name__}:{float(value)!r}"
    if isinstance(value, int | np.integer | np.bool_):
        return f"{type(value).__name__}:{value!r}"
    raise TypeError(type(value).__name__)


def _key_order(value: object, path: str = "") -> dict[str, list[str]]:
    """Map each dict's path to its keys in insertion order, so reorders show up."""
    if isinstance(value, BaseModel):
        return _key_order(value.model_dump(), path)
    orders: dict[str, list[str]] = {}
    if isinstance(value, dict):
        orders[path] = [_canonical_key(key) for key in value]
        for key, item in value.items():
            orders.update(_key_order(item, f"{path}/{_canonical_key(key)}"))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            orders.update(_key_order(item, f"{path}[{index}]"))
    return orders


def _observed(
    result: object,
    datasets: FakeUKDatasets | None,
    comparison_logs: list[logging.LogRecord],
) -> dict[str, Any]:
    return {
        "result_type": type(result).__name__,
        "result": _canonical(result),
        "key_order": _key_order(result),
        "dataset_calls": datasets.calls if datasets is not None else [],
        "logs": [
            [
                record.name,
                record.levelname,
                record.getMessage(),
                record.exc_info[0].__name__ if record.exc_info else None,
            ]
            for record in comparison_logs
            if record.name.startswith("policyengine_api")
        ],
    }


def _load_snapshots() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {"cases": {}, "outputs": {}}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _write_snapshot(case_name: str, observed: dict[str, Any], output_id: str) -> None:
    """Record a case, sharing one stored output between cases that agree."""
    snapshots = _load_snapshots()
    snapshots["cases"][case_name] = output_id
    snapshots["outputs"][output_id] = observed
    used_outputs = set(snapshots["cases"].values())
    snapshots["outputs"] = {
        stored_id: stored
        for stored_id, stored in snapshots["outputs"].items()
        if stored_id in used_outputs
    }
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshots, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )


def _assert_matches_snapshot(case_name: str, observed: dict[str, Any]) -> None:
    serialized = json.dumps(observed, sort_keys=True)
    if UPDATE_SNAPSHOTS:
        output_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        _write_snapshot(case_name, json.loads(serialized), output_id)
        return
    snapshots = _load_snapshots()
    assert case_name in snapshots["cases"], f"no snapshot recorded for {case_name}"
    expected = snapshots["outputs"][snapshots["cases"][case_name]]
    assert json.loads(serialized) == expected
    assert serialized == json.dumps(expected, sort_keys=True)


GENERAL_CASES = {
    "uk_general_all_regions": ("uk", None, True, False),
    "uk_general_country_scotland": ("uk", "country/scotland", True, False),
    "uk_general_constituency_by_name": (
        "uk",
        "constituency/Constituency 3",
        True,
        False,
    ),
    "uk_general_numpy_inputs": ("uk", "country/northern_ireland", True, True),
    "us_general_national_without_wealth_deciles": ("us", "us", False, False),
    "us_general_state_with_wealth_deciles": ("us", "state/ca", True, False),
}


@pytest.mark.parametrize("case_name", sorted(GENERAL_CASES))
def test_compare_economic_outputs_general_matches_snapshot(
    case_name, uk_datasets, comparison_logs
):
    country_id, region, include_wealth, use_numpy = GENERAL_CASES[case_name]
    economy_country = country_id or "us"
    baseline = _economy(
        country_id=economy_country, side="baseline", include_wealth=include_wealth
    )
    reform = _economy(
        country_id=economy_country, side="reform", include_wealth=include_wealth
    )
    if use_numpy:
        baseline, reform = _numpy_economy(baseline), _numpy_economy(reform)

    result = compare_economic_outputs(baseline, reform, country_id, region)

    _assert_matches_snapshot(case_name, _observed(result, uk_datasets, comparison_logs))


@pytest.mark.parametrize(
    ("case_name", "baseline_type", "country_id"),
    [
        ("uk_cliff", "cliff", "uk"),
        ("us_cliff", "cliff", "us"),
        ("unknown_type", "household", "us"),
        ("missing_type", None, "uk"),
    ],
)
def test_compare_economic_outputs_other_types_match_snapshot(
    case_name, baseline_type, country_id, comparison_logs
):
    baseline = _cliff_economy(side="baseline")
    reform = _cliff_economy(side="reform")
    if baseline_type is None:
        del baseline["type"]
    else:
        baseline["type"] = baseline_type

    result = compare_economic_outputs(baseline, reform, country_id, None)

    _assert_matches_snapshot(case_name, _observed(result, None, comparison_logs))


BREAKDOWN_REGIONS = [
    None,
    "uk",
    "country/england",
    "country/scotland",
    "country/wales",
    "country/northern_ireland",
    "country/ENGLAND",
    "country/Northern_Ireland",
    "country/unknown",
    "country/",
    "constituency/Constituency 4",
    f"constituency/{AREA_CODES[6]}",
    "constituency/Missing",
    "local_authority/Local authority 4",
    f"local_authority/{AREA_CODES[7]}",
    "local_authority/Missing",
    "state/ca",
]


def _uk_breakdown_economies() -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = {"household_net_income": _baseline_incomes()}
    reform = {"household_net_income": _reform_incomes()}
    return baseline, reform


@pytest.mark.parametrize(
    ("breakdown_name", "breakdown"),
    [
        ("constituency", uk_constituency_breakdown),
        ("local_authority", uk_local_authority_breakdown),
    ],
)
@pytest.mark.parametrize("region", BREAKDOWN_REGIONS)
def test_uk_area_breakdowns_match_snapshot(
    breakdown_name, breakdown, region, uk_datasets, comparison_logs
):
    baseline, reform = _uk_breakdown_economies()

    result = breakdown(baseline, reform, "uk", region)

    _assert_matches_snapshot(
        f"{breakdown_name}_breakdown_region_{region}",
        _observed(result, uk_datasets, comparison_logs),
    )


@pytest.mark.parametrize(
    ("breakdown_name", "breakdown"),
    [
        ("constituency", uk_constituency_breakdown),
        ("local_authority", uk_local_authority_breakdown),
    ],
)
@pytest.mark.parametrize("country_id", ["us", None, "UK"])
def test_uk_area_breakdowns_outside_uk_match_snapshot(
    breakdown_name, breakdown, country_id, uk_datasets, comparison_logs
):
    baseline, reform = _uk_breakdown_economies()

    result = breakdown(baseline, reform, country_id, None)

    _assert_matches_snapshot(
        f"{breakdown_name}_breakdown_country_{country_id}",
        _observed(result, uk_datasets, comparison_logs),
    )


def test_uk_area_breakdowns_with_numpy_incomes_match_snapshot(
    uk_datasets, comparison_logs
):
    baseline, reform = _uk_breakdown_economies()
    baseline = _numpy_economy(baseline)
    reform = _numpy_economy(reform)

    results = {
        "constituency": uk_constituency_breakdown(baseline, reform, "uk"),
        "local_authority": uk_local_authority_breakdown(baseline, reform, "uk"),
    }

    _assert_matches_snapshot(
        "area_breakdowns_numpy_incomes",
        _observed(results, uk_datasets, comparison_logs),
    )


def test_snapshot_inputs_reach_every_income_change_bucket(uk_datasets):
    """Guard the inputs: each bucket and a NaN area change must stay exercised."""
    baseline, reform = _uk_breakdown_economies()

    result = uk_constituency_breakdown(baseline, reform, "uk")

    assert result is not None
    assert all(count > 0 for count in result.outcomes_by_region["uk"].values())
    assert any(
        math.isnan(area.relative_household_income_change)
        for area in result.by_constituency.values()
    )
    assert uk_datasets.calls
