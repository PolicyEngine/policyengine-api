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

from policyengine_api.libs.runtime_bundle import resolve_runtime_bundle


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


# GCS-hosted artifact bucket names per country. The Modal simulation
# worker reads these paths directly; this is an infrastructure
# contract distinct from the HuggingFace-hosted canonical release
# manifest that ``policyengine.py`` resolves (see
# ``policyengine.provenance.manifest.resolve_managed_dataset_reference``).
# State and congressional-district regions each have their own h5
# artifact under ``states/`` and ``districts/`` respectively;
# ``place/`` regions reuse the parent state's h5.
_US_DATA_BUCKET = "gs://policyengine-us-data"
_UK_DATA_BUCKET = "gs://policyengine-uk-data-private"


def _resolve_us_region_dataset(region: str) -> str:
    if region == "us":
        return f"{_US_DATA_BUCKET}/enhanced_cps_2024.h5"
    if region.startswith("state/"):
        state_code = region.split("/", 1)[1].upper()
        return f"{_US_DATA_BUCKET}/states/{state_code}.h5"
    if region.startswith("congressional_district/"):
        district_id = region.split("/", 1)[1].upper()
        return f"{_US_DATA_BUCKET}/districts/{district_id}.h5"
    if region.startswith("place/"):
        # A ``place/NJ-57000`` region reuses the parent state's h5.
        place_id = region.split("/", 1)[1]
        parent_state = place_id.split("-", 1)[0].upper()
        return f"{_US_DATA_BUCKET}/states/{parent_state}.h5"
    raise ValueError(f"Unknown US region for dataset resolution: {region!r}")


def _resolve_uk_region_dataset(region: str) -> str:
    if region == "uk":
        return f"{_UK_DATA_BUCKET}/enhanced_frs_2023_24.h5"
    raise ValueError(f"Unknown UK region for dataset resolution: {region!r}")


def get_default_dataset(country_id: str, region: str) -> str:
    """Resolve the default dataset URI for a country + region pair.

    Returns a ``gs://...`` URI that the Modal simulation worker reads
    directly. Naming conventions preserved from the pre-v4
    ``policyengine.utils.data.datasets.get_default_dataset`` helper:

        us + "us"                           -> enhanced_cps_2024.h5
        us + "state/CA"                     -> states/CA.h5
        us + "congressional_district/CA-37" -> districts/CA-37.h5
        us + "place/NJ-57000"               -> states/NJ.h5
        uk + "uk"                           -> enhanced_frs_2023_24.h5

    Args:
        country_id: Country id.
        region: Region identifier.

    Raises:
        ValueError: country has no configured resolver, or region is
            not recognized.
    """
    resolved = resolve_runtime_bundle(
        country_id=country_id,
        region=region,
        dataset="default",
    )
    if resolved.canonical_dataset_uri is not None:
        return resolved.worker_dataset_uri

    if country_id == "us":
        return _resolve_us_region_dataset(region)
    if country_id == "uk":
        return _resolve_uk_region_dataset(region)
    raise ValueError(f"No default dataset configured for country_id={country_id!r}.")
