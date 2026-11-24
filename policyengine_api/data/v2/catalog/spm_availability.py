"""Record whether each published catalog version offers SPM settings.

The simulation service's public ``GET /versions`` lists, under
``spm_capabilities``, the certified SPM capability of each PolicyEngine.py
bundle it runs: its contract version and pinned defaults. The Public API
already checks economy requests' SPM selections against it. A US catalog
version offers SPM when the service reports a canonical capability for its
PolicyEngine.py version; other countries never do.

Publication records it after the catalog itself, for the installed
PolicyEngine.py version's catalog versions that have none yet, so a version
published before this existed gets it on the next publication run of that
PolicyEngine.py version; versions of other PolicyEngine.py versions keep none.
A bundle pins its SPM release, so a recorded value never changes. A US version
the service does not serve yet (its ``policyengine`` routes do not name it)
is left unrecorded rather than recorded as unavailable, and the next
publication run tries again; ``/v2/model-catalog`` reports its availability
as unknown meanwhile. So is every version when the service's versions cannot
be read: an unreadable answer never fails the publication, but the
publication evidence lists the versions not recorded, with the reason, and
the command prints it to stderr.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

import httpx
import sqlalchemy as sa
from pydantic import ValidationError
from sqlmodel import col

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
    SPMAvailabilityRecording,
)
from policyengine_api.data.v2.models import TaxBenefitModel, TaxBenefitModelVersion
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.data.v2.catalog.records import NormalizedCatalog

LOGGER = logging.getLogger(__name__)
SIMULATION_ENTRYPOINT_URL = "SIMULATION_ENTRYPOINT_URL"
SPM_COUNTRY_ID = "us"
SPM_CONTRACT_VERSION = "canonical-spm-v1"
VERSIONS_TIMEOUT_SECONDS = 30.0
UNAVAILABLE: dict[str, Any] = {"available": False}


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
    session: Session,
    *,
    model_name: str,
    version: str,
    availability: Mapping[str, Any],
) -> bool:
    """Store a catalog version's SPM availability unless it already has one.

    Return whether the version was changed.
    """
    model_ids = sa.select(col(TaxBenefitModel.id)).where(
        col(TaxBenefitModel.name) == model_name
    )
    result = session.execute(
        sa.update(TaxBenefitModelVersion)
        .where(
            col(TaxBenefitModelVersion.model_id).in_(model_ids),
            col(TaxBenefitModelVersion.version) == version,
            col(TaxBenefitModelVersion.spm_availability).is_(None),
        )
        .values(spm_availability=dict(availability)),
        # No version row is loaded in the Session, so none needs refreshing.
        execution_options={"synchronize_session": False},
    )
    return bool(cast("CursorResult[Any]", result).rowcount)


def read_unrecorded_versions(
    session: Session, versions: Iterable[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Return the (model name, version) pairs whose SPM availability is unrecorded."""
    requested = list(versions)
    if not requested:
        return set()
    rows = session.execute(
        sa.select(col(TaxBenefitModel.name), col(TaxBenefitModelVersion.version))
        .join(
            TaxBenefitModelVersion,
            col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
        )
        .where(
            sa.tuple_(
                col(TaxBenefitModel.name), col(TaxBenefitModelVersion.version)
            ).in_(requested),
            col(TaxBenefitModelVersion.spm_availability).is_(None),
        )
    ).all()
    return {(row.name, row.version) for row in rows}


def _still_unrecorded(
    session: Session, catalog: NormalizedCatalog
) -> tuple[tuple[str, str], ...]:
    """Return the catalog's versions, by country, whose availability is unrecorded."""
    unrecorded = read_unrecorded_versions(
        session,
        [
            (country.model.name, country.model_version.version)
            for country in catalog.countries
        ],
    )
    return tuple(
        (country.country_id, country.model_version.version)
        for country in catalog.countries
        if (country.model.name, country.model_version.version) in unrecorded
    )


def record_published_spm_availability(
    sessions: sessionmaker[Session],
    catalog: NormalizedCatalog,
    environ: Mapping[str, str] | None = None,
    *,
    fetch_versions: Callable[[str], object] = fetch_simulation_versions,
) -> SPMAvailabilityRecording:
    """Record each published country's SPM availability for the catalog version.

    Return what was recorded, and the versions still unrecorded after it. A
    US version the service does not serve yet stays unrecorded, and so does
    every version when the service's versions cannot be read; the next
    publication run tries again. A version an earlier publication recorded
    keeps its value and is in neither list. Raise V2ConfigurationError
    without ``SIMULATION_ENTRYPOINT_URL``.
    """
    url = simulation_entrypoint_url(os.environ if environ is None else environ)
    try:
        versions = fetch_versions(url)
    except CatalogPublicationError as error:
        with sessions.begin() as session:
            not_recorded = _still_unrecorded(session, catalog)
        if not_recorded:
            LOGGER.warning(
                "SPM availability was not recorded; the next publication run "
                "tries again: %s",
                error,
            )
        return SPMAvailabilityRecording(
            not_recorded=not_recorded, versions_unreadable=str(error)
        )
    recorded: list[tuple[str, str, bool]] = []
    with sessions.begin() as session:
        for country in catalog.countries:
            version = country.model_version.version
            availability = spm_availability(
                country.country_id, catalog.policyengine_version, versions
            )
            if availability is not None and record_spm_availability(
                session,
                model_name=country.model.name,
                version=version,
                availability=availability,
            ):
                recorded.append(
                    (country.country_id, version, bool(availability["available"]))
                )
        not_recorded = _still_unrecorded(session, catalog)
    return SPMAvailabilityRecording(recorded=tuple(recorded), not_recorded=not_recorded)
