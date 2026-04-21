"""Api-local types for the Modal simulation-worker request payload.

Historically these lived on the pre-v4 ``policyengine`` package and
were imported via ``from policyengine.simulation import
SimulationOptions``. The v4 rearchitecture dropped that module
(``policyengine.core.simulation.Simulation`` has a different shape),
but the wire contract between the api and the Modal simulation
worker has not changed: the worker still deserializes a dict with
the fields below, regardless of which pe.py version assembles it.

Owning the type api-side removes the coupling to pe.py's internal
class layout. The worker's own pe.py version can evolve
independently as long as it accepts this JSON shape.

Field semantics match the pre-v4 ``SimulationOptions``:
    country         Country id ("us", "uk", "canada", "ng", "il").
    scope           "macro" (society-wide) or "household".
    reform          Reform policy JSON dict.
    baseline        Baseline policy JSON dict.
    time_period     Simulation year as a string.
    include_cliffs  Whether the worker should compute cliff-impact.
    region          Region identifier — "us", "state/CA", etc.
    data            Dataset URI or keyword ("default", "enhanced_cps",
                    a GCS URI, or a passthrough keyword understood
                    directly by the worker).
    model_version   Optional pin for the country model package version.
    data_version    Optional pin for the country data package version.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class SimulationOptions(BaseModel):
    """Payload for a Modal simulation worker job.

    Schema is kept deliberately permissive on ``reform`` / ``baseline``
    so the worker receives whatever policy JSON the api policy service
    produced without shape enforcement at this boundary.
    """

    country: str
    scope: Literal["macro", "household"]
    reform: dict[str, Any]
    baseline: dict[str, Any]
    time_period: str
    include_cliffs: bool = False
    region: str
    data: str
    model_version: Optional[str] = None
    data_version: Optional[str] = None


# Default GCS-hosted artifact paths per (country, region). Previously
# resolved by ``policyengine.utils.data.datasets.get_default_dataset``
# in the v0.x orchestrator. Moving it api-side lets the api evolve
# independently of pe.py's v4 dataset-resolution surface (which
# returns ``Dataset`` objects, not strings, so does not fit this
# caller's need for a Modal-worker URI).
_DEFAULT_DATASETS_BY_COUNTRY_REGION: dict[str, dict[str, str]] = {
    "us": {
        "us": "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5",
        # State and congressional-district regions reuse the national
        # h5; the worker filters by region_code at simulation time.
    },
    "uk": {
        "uk": "hf://policyengine/policyengine-uk-data/enhanced_frs_2022_23.h5",
    },
}


def get_default_dataset(country_id: str, region: str) -> str:
    """Resolve the default dataset URI for a country + region pair.

    Args:
        country_id: Country id ("us" or "uk" today).
        region: Region identifier. State-scoped regions fall back to
            the national default; this matches the pre-v4 behavior.

    Raises:
        ValueError: country has no default dataset configured.
    """
    by_region = _DEFAULT_DATASETS_BY_COUNTRY_REGION.get(country_id)
    if by_region is None:
        raise ValueError(
            f"No default dataset configured for country_id={country_id!r}."
        )
    if region in by_region:
        return by_region[region]
    # State and district regions fall back to the national default.
    national_key = country_id
    if national_key in by_region:
        return by_region[national_key]
    raise ValueError(
        f"No default dataset for country_id={country_id!r}, region={region!r}."
    )
