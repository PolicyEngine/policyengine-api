"""Characterization of every outcome of the worker economy-result SPM check."""

import pytest
from pydantic import ValidationError

from policyengine_api.spm import SPMValidationError
from policyengine_api.worker_spm import validate_worker_result

SELECTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "ce_trend",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
OTHER_SELECTION = {**SELECTION, "scenario": "zero_real"}
CODE = "SPM_CONFIGURATION_UNAVAILABLE"
YEARS_DIFFER = "Budget window SPM result years differ from request"


def _receipt(years: tuple[str, ...] = ("2026",)) -> dict:
    return {
        "schema_version": "canonical-spm-provenance-v2",
        "forecast_id": "test-only",
        "forecast_sha256": SELECTION["forecast_content_sha256"],
        "scenario": SELECTION["scenario"],
        "geography_kind": SELECTION["geography_kind"],
        "geography_id": SELECTION["geography_id"],
        "county_vintage": SELECTION["county_vintage"],
        "as_of": SELECTION["as_of"],
        "years": list(years),
        "runtime_versions": {
            "policyengine": "test",
            "policyengine-core": "test",
            "policyengine-us": "test",
            "spm-calculator": "test",
        },
    }


def _annual(year: str = "2026", years: tuple[str, ...] = ("2026",)) -> dict:
    return {
        "year": year,
        "spm_provenance": {
            "schema_version": "canonical-spm-comparison-v2",
            "baseline": {"receipt": _receipt(years), "execution_count": 1},
            "reform": {"receipt": _receipt(years), "execution_count": 1},
        },
    }


def _window(rows: object, *, size: object = None) -> dict:
    return {
        "kind": "budgetWindow",
        "windowSize": len(rows) if size is None else size,
        "annualImpacts": rows,
    }


ACCEPTED = {
    "annual-without-year": (_annual(), {}),
    "annual-covering-year": (_annual(), {"expected_year": "2026"}),
    "annual-covering-int-year": (_annual(), {"expected_year": 2026}),
    "window": (
        _window([_annual("2026"), _annual("2027", ("2027",))]),
        {"expected_years": ["2026", "2027"]},
    ),
    "window-without-years": (_window([_annual("2026")]), {}),
}


@pytest.mark.parametrize("case_name", sorted(ACCEPTED))
def test_matching_results_are_accepted(case_name):
    result, expectations = ACCEPTED[case_name]

    assert validate_worker_result(result, SELECTION, **expectations) is None


@pytest.mark.parametrize("result", [None, {}, "anything", _window([], size=0)])
def test_no_requested_selection_accepts_any_result(result):
    assert validate_worker_result(result, None, expected_year="2026") is None


REJECTED = {
    "not-an-object": (
        ["not", "an", "object"],
        {},
        "Worker SPM result must be an object",
        TypeError,
    ),
    "window-for-annual-request": (
        _window([_annual()]),
        {"expected_year": "2026"},
        "Expected an annual SPM result",
        ValueError,
    ),
    "window-size-zero": (
        _window([], size=0),
        {},
        "Budget window size must be a positive integer",
        ValueError,
    ),
    "window-size-bool": (
        _window([_annual()], size=True),
        {},
        "Budget window size must be a positive integer",
        ValueError,
    ),
    "window-size-text": (
        _window([_annual()], size="1"),
        {},
        "Budget window size must be a positive integer",
        ValueError,
    ),
    "window-rows-not-list": (
        _window({"year": "2026"}, size=1),
        {},
        "Budget window annual impacts must be objects",
        ValueError,
    ),
    "window-row-not-object": (
        _window(["2026"], size=1),
        {},
        "Budget window annual impacts must be objects",
        ValueError,
    ),
    "window-incomplete": (
        _window([_annual()], size=2),
        {},
        "Budget window has incomplete SPM receipts",
        ValueError,
    ),
    "window-year-not-calendar": (
        _window([_annual("26")]),
        {},
        "Budget window annual impacts require calendar years",
        ValueError,
    ),
    "window-year-not-ascii": (
        _window([_annual("\uff12\uff10\uff12\uff16")]),
        {},
        "Budget window annual impacts require calendar years",
        ValueError,
    ),
    "window-duplicate-years": (
        _window([_annual("2026"), _annual("2026")]),
        {},
        YEARS_DIFFER,
        ValueError,
    ),
    "window-other-years": (
        _window([_annual("2026")]),
        {"expected_years": ["2027"]},
        YEARS_DIFFER,
        ValueError,
    ),
    "window-int-expected-years": (
        _window([_annual("2026")]),
        {"expected_years": [2026]},
        None,
        None,
    ),
    "window-row-uncertified": (
        _window([_annual("2026", ("2025",))]),
        {},
        "Worker SPM receipt does not cover requested year",
        SPMValidationError,
    ),
    "annual-for-window-request": (
        _annual(),
        {"expected_years": ["2026"]},
        "Expected a budget window SPM result",
        ValueError,
    ),
    "annual-legacy-config": (
        {**_annual(), "spm_config": SELECTION},
        {},
        "Worker result must not include legacy spm_config",
        ValueError,
    ),
    "annual-missing-receipts": (
        {"year": "2026"},
        {},
        None,
        ValidationError,
    ),
    "annual-uncovered-year": (
        _annual(years=("2025",)),
        {"expected_year": "2026"},
        "Worker SPM receipt does not cover requested year",
        ValueError,
    ),
}


@pytest.mark.parametrize("case_name", sorted(REJECTED))
def test_mismatched_results_raise_typed_errors(case_name):
    result, expectations, message, cause_type = REJECTED[case_name]

    if cause_type is None:
        assert validate_worker_result(result, SELECTION, **expectations) is None
        return
    with pytest.raises(SPMValidationError) as caught:
        validate_worker_result(result, SELECTION, **expectations)

    assert caught.value.code == CODE
    assert type(caught.value.__cause__) is cause_type
    if message is not None:
        assert caught.value.message == message
    else:
        assert caught.value.message
        assert "pydantic.dev" not in caught.value.message


def test_receipt_for_another_selection_is_rejected():
    with pytest.raises(SPMValidationError) as caught:
        validate_worker_result(_annual(), OTHER_SELECTION, expected_year="2026")

    assert caught.value.code == CODE
    assert caught.value.message == "Worker result SPM settings differ from the request"
    assert type(caught.value.__cause__) is ValueError
