"""Framework-independent request data of the v2 economy report routes.

What the Simulation Entrypoint answers, and the protocol through which the
Public API asks it, are in ``policyengine_api.services.v2.simulation_entrypoint``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationChoice,
)

# The bounds and form the Simulation Entrypoint accepts.
ReportYear = Annotated[int, Field(ge=1900, le=2200, description="The report's year")]
CatalogKey = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^\S+$")]


class StrictEconomyReportInput(BaseModel):
    """Reject fields outside the reviewed economy report contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EconomyReportFields(StrictEconomyReportInput):
    """What an economy report compares, apart from its country.

    ``region_code`` is a region of the country's current catalog version
    (``state/ca``, ``country/wales``), and ``dataset_name`` one of its
    datasets; without it the region's default dataset is used.
    """

    kind: Literal["economy"]
    year: ReportYear
    region_code: CatalogKey
    dataset_name: CatalogKey | None = None
    baseline: SimulationChoice
    reform: SimulationChoice


class EconomyReportRunFields(StrictEconomyReportInput):
    """A re-run; ``force`` calculates both simulations again instead of reusing runs."""

    force: StrictBool = False
