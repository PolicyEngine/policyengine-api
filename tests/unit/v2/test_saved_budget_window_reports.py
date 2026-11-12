"""A saved report's budget_window_years agrees with the report it names.

A detailed-save report stores its own window (``reports.budget_window_size``),
so a saved report naming one gives the same number of years, or none for a
report without a window of two or more years: a saved report stores a
one-year window as no window.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.user_reports.validators import (
    AssociationBudgetWindowConflictError,
    require_matching_budget_window,
)


@pytest.mark.parametrize(
    ("budget_window_size", "budget_window_years"),
    [(10, 10), (2, 2), (75, 75), (None, None), (1, None)],
    ids=["ten-years", "two-years", "75-years", "no-window", "one-year"],
)
def test_a_saved_window_agreeing_with_the_reports_is_accepted(
    budget_window_size: int | None, budget_window_years: int | None
) -> None:
    accepted = require_matching_budget_window(
        report_id=uuid4(),
        budget_window_size=budget_window_size,
        budget_window_years=budget_window_years,
    )

    assert accepted is None


@pytest.mark.parametrize(
    ("budget_window_size", "budget_window_years", "reason"),
    [
        (10, 5, "must be 10, the budget window of report"),
        (10, None, "must be 10, the budget window of report"),
        (None, 10, "must be null: report .* has no budget window of two or more"),
        (1, 2, "must be null: report .* has no budget window of two or more"),
    ],
    ids=["other-size", "no-years-for-a-window", "years-for-no-window", "one-year"],
)
def test_a_saved_window_disagreeing_with_the_reports_is_a_conflict(
    budget_window_size: int | None, budget_window_years: int | None, reason: str
) -> None:
    with pytest.raises(AssociationBudgetWindowConflictError, match=reason) as raised:
        require_matching_budget_window(
            report_id=uuid4(),
            budget_window_size=budget_window_size,
            budget_window_years=budget_window_years,
        )

    # Answered 400, as other contradicting references are.
    assert isinstance(raised.value, AssociationReferenceConflictError)
