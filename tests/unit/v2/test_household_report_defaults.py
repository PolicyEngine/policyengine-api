"""The default household report adapter, when the generated client cannot serve it."""

from __future__ import annotations

import sys
import types

import pytest

from policyengine_api.fastapi_routes.dependencies import (
    _default_household_report_simulation,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationServiceUnavailableError,
)

pytest.importorskip("policyengine_api_simulation_client")


def test_a_client_without_the_household_report_routes_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client generated before the household report routes existed lacks them.

    Importing the adapter then fails with ``ImportError`` ("cannot import
    name"), not ``ModuleNotFoundError``; it must still mean the simulation
    service is unavailable, not an unexpected failure.
    """
    monkeypatch.delitem(
        sys.modules, "policyengine_api.libs.simulation_household_reports", raising=False
    )
    monkeypatch.setitem(
        sys.modules,
        "policyengine_api_simulation_client.api.default",
        types.ModuleType("policyengine_api_simulation_client.api.default"),
    )

    with pytest.raises(SimulationServiceUnavailableError, match="household report"):
        _default_household_report_simulation()
