"""Record whether each published catalog version offers SPM settings.

The simulation service's public ``GET /versions`` lists, under
``spm_capabilities``, the certified SPM capability of each PolicyEngine.py
bundle it runs: its contract version and pinned defaults. The Public API
already checks economy requests' SPM selections against it. A US catalog
version offers SPM when the service reports a canonical capability for its
PolicyEngine.py version; other countries never do.

Publication records it after the catalog itself, on each version that has
none yet, so versions published before it existed get it on the next run. A
bundle pins its SPM release, so a recorded value never changes. A US version
the service does not serve yet (its ``policyengine`` routes do not name it)
is left unrecorded rather than recorded as unavailable, and the next
publication run tries again; ``/v2/model-catalog`` offers no SPM settings for
it meanwhile.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
import sqlalchemy as sa
from pydantic import ValidationError

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import TaxBenefitModel, TaxBenefitModelVersion
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sqlalchemy import Connection, Engine

    from policyengine_api.data.v2.catalog.records import NormalizedCatalog

SIMULATION_ENTRYPOINT_URL = "SIMULATION_ENTRYPOINT_URL"
SPM_COUNTRY_ID = "us"
SPM_CONTRACT_VERSION = "canonical-spm-v1"
VERSIONS_TIMEOUT_SECONDS = 30.0
UNAVAILABLE: dict[str, Any] = {"available": False}
MODELS = TaxBenefitModel.__table__
MODEL_VERSIONS = TaxBenefitModelVersion.__table__


def _served(policyengine_version: str, versions: dict[str, Any]) -> bool:
    """Return whether the service's ``policyengine`` routes name the version."""
    routes = versions.get("policyengine")
    if not isinstance(routes, dict):
        return False
    return policyengine_version != "latest" and (
        policyengine_version in routes or routes.get("latest") == policyengine_version
    )


def spm_availability(
    country_id: str, policyengine_version: str, versions: object
) -> dict[str, Any] | None:
    """Return ``{available, settings_schema, defaults}`` for one catalog version.

    Only a US version whose PolicyEngine.py version has a canonical capability
    with pinned defaults (forecast artifact and scenario) offers SPM; any other
    country, and a US version the service serves without one, is
    ``{"available": False}``. A US version the service does not serve yet is
    None: not known.
    """
    if country_id != SPM_COUNTRY_ID:
        return dict(UNAVAILABLE)
    if not isinstance(versions, dict) or not _served(policyengine_version, versions):
        return None
    capabilities = versions.get("spm_capabilities")
    capability = (
        capabilities.get(policyengine_version)
        if isinstance(capabilities, dict)
        else None
    )
    if (
        not isinstance(capability, dict)
        or set(capability) != {"contract_version", "defaults"}
        or capability["contract_version"] != SPM_CONTRACT_VERSION
    ):
        return dict(UNAVAILABLE)
    try:
        defaults = SPMSelection.model_validate(capability["defaults"])
    except ValidationError:
        return dict(UNAVAILABLE)
    if not defaults.forecast_content_sha256 or not defaults.scenario:
        return dict(UNAVAILABLE)
    return {
        "available": True,
        "settings_schema": SPMSelection.model_json_schema(),
        "defaults": {
            name: getattr(defaults, name) for name in SPMSelection.model_fields
        },
    }


def simulation_entrypoint_url(environ: Mapping[str, str]) -> str:
    """Return the simulation service's base URL; raise when it is not set."""
    url = environ.get(SIMULATION_ENTRYPOINT_URL, "").strip().rstrip("/")
    if not url:
        msg = f"{SIMULATION_ENTRYPOINT_URL} is required to record SPM availability"
        raise V2ConfigurationError(msg)
    return url


def fetch_simulation_versions(
    base_url: str, *, client: httpx.Client | None = None
) -> object:
    """Read the simulation service's public ``GET /versions`` answer."""
    url = f"{base_url.rstrip('/')}/versions"
    try:
        if client is None:
            response = httpx.get(url, timeout=VERSIONS_TIMEOUT_SECONDS)
        else:
            response = client.get(url, timeout=VERSIONS_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        msg = "the simulation service's versions could not be read"
        raise CatalogPublicationError(msg) from error


def record_spm_availability(
    connection: Connection,
    *,
    model_name: str,
    version: str,
    availability: Mapping[str, Any],
) -> bool:
    """Store a catalog version's SPM availability unless it already has one.

    Return whether the version was changed.
    """
    model_ids = sa.select(MODELS.c.id).where(MODELS.c.name == model_name)
    result = connection.execute(
        sa.update(MODEL_VERSIONS)
        .where(
            MODEL_VERSIONS.c.model_id.in_(model_ids),
            MODEL_VERSIONS.c.version == version,
            MODEL_VERSIONS.c.spm_availability.is_(None),
        )
        .values(spm_availability=dict(availability))
    )
    return bool(result.rowcount)


def record_published_spm_availability(
    engine: Engine,
    catalog: NormalizedCatalog,
    environ: Mapping[str, str] | None = None,
    *,
    fetch_versions: Callable[[str], object] = fetch_simulation_versions,
) -> None:
    """Record each published country's SPM availability for the catalog version.

    A US version the service does not serve yet stays unrecorded.

    Raise V2ConfigurationError without ``SIMULATION_ENTRYPOINT_URL``, and
    CatalogPublicationError when the service's versions cannot be read.
    """
    versions = fetch_versions(
        simulation_entrypoint_url(os.environ if environ is None else environ)
    )
    with engine.begin() as connection:
        for country in catalog.countries:
            availability = spm_availability(
                country.country_id, catalog.policyengine_version, versions
            )
            if availability is not None:
                record_spm_availability(
                    connection,
                    model_name=country.model.name,
                    version=country.model_version.version,
                    availability=availability,
                )
