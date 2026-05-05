from dataclasses import dataclass
from typing import Literal

BUDGET_WINDOW_MAX_ACTIVE_YEARS = 20
BUDGET_WINDOW_MAX_YEARS = 75
BUDGET_WINDOW_MAX_END_YEAR = 2099


@dataclass(frozen=True)
class BudgetWindowRequestSetup:
    start_year: str
    window_size: int
    years: list[str]
    time_period: str


def build_budget_window_years(*, start_year: str, window_size: int) -> list[str]:
    start_year_int = int(start_year)
    return [str(start_year_int + index) for index in range(window_size)]


def build_budget_window_time_period(*, start_year: str, window_size: int) -> str:
    return f"budget_window:{start_year}:{window_size}"


def build_budget_window_request_setup(
    *,
    start_year: str,
    window_size: int,
    target: Literal["general", "cliff"],
) -> BudgetWindowRequestSetup:
    if target != "general":
        raise ValueError("Budget-window calculations only support target='general'")

    start_year_int = int(start_year)
    if not 1 <= window_size <= BUDGET_WINDOW_MAX_YEARS:
        raise ValueError(f"window_size must be between 1 and {BUDGET_WINDOW_MAX_YEARS}")

    end_year = start_year_int + window_size - 1
    if end_year > BUDGET_WINDOW_MAX_END_YEAR:
        raise ValueError(
            f"budget-window end_year must be {BUDGET_WINDOW_MAX_END_YEAR} or earlier"
        )

    normalized_start_year = str(start_year_int)
    return BudgetWindowRequestSetup(
        start_year=normalized_start_year,
        window_size=window_size,
        years=build_budget_window_years(
            start_year=normalized_start_year,
            window_size=window_size,
        ),
        time_period=build_budget_window_time_period(
            start_year=normalized_start_year,
            window_size=window_size,
        ),
    )
