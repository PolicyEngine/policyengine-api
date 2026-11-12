"""Unit tests for :mod:`policyengine_api.libs.rate_limit_wait_budget`."""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pytest

from policyengine_api.libs.rate_limit_wait_budget import (
    MAXIMUM_RATE_LIMIT_WAIT_SECONDS,
    RateLimitWaitBudget,
)

REPO = Path(__file__).resolve().parents[3]


def _application_modules_loaded_by(module: str) -> set[str]:
    """Import ``module`` in a fresh interpreter; return the application modules."""
    script = (
        "import sys\n"
        f"import {module}\n"
        "print(' '.join(name for name in sys.modules "
        "if name.startswith('policyengine_api')))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


def test_the_wait_budget_module_loads_no_other_application_module() -> None:
    assert _application_modules_loaded_by(
        "policyengine_api.libs.rate_limit_wait_budget"
    ) == {
        "policyengine_api",
        "policyengine_api.libs",
        "policyengine_api.libs.rate_limit_wait_budget",
    }


def test_the_admin_service_loads_the_wait_budget_but_not_the_auth0_module() -> None:
    loaded = _application_modules_loaded_by(
        "policyengine_api.services.v2.user_types.services"
    )

    assert "policyengine_api.libs.rate_limit_wait_budget" in loaded
    assert "policyengine_api.libs.auth0_management" not in loaded


def test_a_wait_budget_spends_waits_that_fit_in_what_is_left() -> None:
    budget = RateLimitWaitBudget()

    assert budget.remaining_seconds == MAXIMUM_RATE_LIMIT_WAIT_SECONDS == 2.0
    assert budget.take(1.5) is True
    assert budget.take(0.6) is False
    assert budget.remaining_seconds == 0.5
    assert budget.take(0.5) is True
    assert budget.take(0.0) is True
    assert budget.remaining_seconds == 0.0


@pytest.mark.parametrize("wait", [-5.0, -0.1, math.nan, math.inf, -math.inf])
def test_a_wait_budget_refuses_negative_or_non_finite_waits(wait: float) -> None:
    """Such a wait spends nothing, so the 429 counts as unavailable.

    Taken, nan would leave nan seconds, which every later wait fits, and a
    negative wait would add seconds.
    """
    budget = RateLimitWaitBudget()

    assert budget.take(wait) is False
    assert budget.remaining_seconds == 2.0
    assert budget.take(2.0) is True
    assert budget.take(0.1) is False
