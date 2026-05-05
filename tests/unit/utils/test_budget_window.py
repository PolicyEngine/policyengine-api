import pytest

from policyengine_api.utils.budget_window import (
    BUDGET_WINDOW_MAX_END_YEAR,
    BUDGET_WINDOW_MAX_YEARS,
    build_budget_window_request_setup,
    build_budget_window_time_period,
    build_budget_window_years,
)


def test_build_budget_window_years():
    assert build_budget_window_years(start_year="2026", window_size=3) == [
        "2026",
        "2027",
        "2028",
    ]


def test_build_budget_window_time_period():
    assert (
        build_budget_window_time_period(start_year="2026", window_size=3)
        == "budget_window:2026:3"
    )


def test_build_budget_window_request_setup_normalizes_start_year():
    setup = build_budget_window_request_setup(
        start_year="02026",
        window_size=2,
        target="general",
    )

    assert setup.start_year == "2026"
    assert setup.window_size == 2
    assert setup.years == ["2026", "2027"]
    assert setup.time_period == "budget_window:2026:2"


def test_build_budget_window_request_setup_rejects_cliff_target():
    with pytest.raises(
        ValueError,
        match="Budget-window calculations only support target='general'",
    ):
        build_budget_window_request_setup(
            start_year="2026",
            window_size=2,
            target="cliff",
        )


def test_build_budget_window_request_setup_rejects_oversized_window():
    with pytest.raises(
        ValueError,
        match=f"window_size must be between 1 and {BUDGET_WINDOW_MAX_YEARS}",
    ):
        build_budget_window_request_setup(
            start_year="2026",
            window_size=BUDGET_WINDOW_MAX_YEARS + 1,
            target="general",
        )


def test_build_budget_window_request_setup_rejects_end_year_after_max():
    with pytest.raises(
        ValueError,
        match=f"budget-window end_year must be {BUDGET_WINDOW_MAX_END_YEAR} or earlier",
    ):
        build_budget_window_request_setup(
            start_year="2090",
            window_size=20,
            target="general",
        )
