"""Explicit command boundary for one-time v2 catalog initialization."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.certified_data_inspection import (
    HuggingFaceDataInspector,
)
from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_installed_catalog,
)
from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    PublicationEvidence,
    publish_catalog,
    unpublished_countries,
)
from policyengine_api.data.v2.catalog.region_data_verification import (
    RegionDataVerificationError,
    verify_region_data,
)
from policyengine_api.data.v2.catalog.spm_availability import (
    record_published_spm_availability,
    simulation_entrypoint_url,
)
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_data_write_database_settings,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from contextlib import AbstractContextManager

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.data.v2.catalog.publication_types import (
        SPMAvailabilityRecording,
    )
    from policyengine_api.data.v2.catalog.records import NormalizedCatalog


# The environment variable holding the Hugging Face read token; PolicyEngine
# Core's data downloads read the same variable.
HUGGING_FACE_CREDENTIAL_VARIABLE = "HUGGING_FACE_TOKEN"
# Countries whose certified data repository needs the read token.
PRIVATE_DATA_COUNTRIES = frozenset({"uk"})


def data_write_sessions(
    settings: V2DatabaseSettings,
) -> AbstractContextManager[sessionmaker[Session]]:
    """Return the Session factories of one initialization attempt, as a context.

    Their engine keeps no connection pool and is disposed of on exit.
    """
    from policyengine_api.data.v2.database import unpooled_v2_sessions

    return unpooled_v2_sessions(settings.connection.url)


def verify_installed_region_data(
    catalog: NormalizedCatalog,
    countries: Sequence[str],
    environ: Mapping[str, str] | None = None,
) -> None:
    """Check the named countries' regions against their certified artifacts.

    The artifacts are read from Hugging Face with ``HUGGING_FACE_TOKEN``.
    Countries whose certified data repository is private need it, so their
    check fails with a configuration error before any read when it is unset.
    """
    token = (os.environ if environ is None else environ).get(
        HUGGING_FACE_CREDENTIAL_VARIABLE
    )
    needing_token = [
        country for country in countries if country in PRIVATE_DATA_COUNTRIES
    ]
    if needing_token and not token:
        msg = (
            f"{HUGGING_FACE_CREDENTIAL_VARIABLE} must be set to read the certified "
            f"{', '.join(needing_token)} data, whose repository is private"
        )
        raise V2ConfigurationError(msg)
    verify_region_data(
        catalog,
        HuggingFaceDataInspector(token=token or None),
        countries=countries,
    )


def verify_unpublished_region_data(
    sessions: sessionmaker[Session],
    catalog: NormalizedCatalog,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Check the regions of countries whose catalog version is not stored yet.

    Publication writes nothing for the other countries and only compares them
    with what is stored, so their artifacts are not read.
    """
    verify_installed_region_data(
        catalog, unpublished_countries(sessions, catalog), environ
    )


@dataclass(frozen=True)
class PublicationSteps:
    """What initialization does with the database, in order, after extraction.

    ``verify_region_data`` checks the regions' certified data before anything
    is written, ``publish`` writes the catalog, and ``record_spm_availability``
    then records each version's SPM availability from the simulation service
    (``spm_availability``).
    """

    verify_region_data: Callable[
        [sessionmaker[Session], NormalizedCatalog, Mapping[str, str] | None], None
    ] = verify_unpublished_region_data
    publish: Callable[
        [sessionmaker[Session], NormalizedCatalog], PublicationEvidence
    ] = publish_catalog
    record_spm_availability: Callable[
        [sessionmaker[Session], NormalizedCatalog, Mapping[str, str] | None],
        SPMAvailabilityRecording,
    ] = record_published_spm_availability


def initialize_catalog(
    environ: Mapping[str, str] | None = None,
    *,
    extractor: Callable[[], NormalizedCatalog] = extract_installed_catalog,
    sessions_builder: Callable[
        [V2DatabaseSettings], AbstractContextManager[sessionmaker[Session]]
    ] = data_write_sessions,
    steps: PublicationSteps | None = None,
) -> PublicationEvidence:
    """Load only row-write settings, extract fully, verify, then publish explicitly.

    After publishing, record each version's SPM availability, which the
    evidence returned reports. The simulation service's URL, which that
    needs, is checked before anything else. Every step uses the Session
    factories ``sessions_builder`` opens, which it closes when they end.
    """
    selected_steps = steps or PublicationSteps()
    settings = load_v2_data_write_database_settings(environ)
    simulation_entrypoint_url(os.environ if environ is None else environ)
    catalog = extractor()
    with sessions_builder(settings) as sessions:
        selected_steps.verify_region_data(sessions, catalog, environ)
        evidence = selected_steps.publish(sessions, catalog)
        recording = selected_steps.record_spm_availability(sessions, catalog, environ)
        return replace(evidence, spm_availability=recording)


def _error_payload(error: Exception) -> dict[str, object]:
    safe_errors = (
        V2ConfigurationError,
        CatalogExtractionError,
        RegionDataVerificationError,
        CatalogPublicationError,
    )
    message = (
        str(error)
        if isinstance(error, safe_errors)
        else "catalog initialization failed unexpectedly"
    )
    return {
        "outcome": "error",
        "error": {
            "type": type(error).__name__,
            "message": message,
        },
    }


def main() -> int:
    """Run explicit initialization and return a shell-compatible status.

    A failure to prune an older catalog version, to analyze the catalog
    tables, or to read the simulation service's versions to record SPM
    availability, leaves the status successful, since the publication had
    committed; each one is in the evidence and is also printed to stderr.
    """
    try:
        evidence = initialize_catalog()
    except Exception as error:  # noqa: BLE001  # command must return safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    for failure in evidence.catalog_pruning_failures:
        country_and_version = " ".join(
            part
            for part in (failure.country_id, failure.policyengine_version)
            if part is not None
        )
        print(
            f"catalog pruning failed for {country_and_version}: "
            f"{failure.error_type}: {failure.message}",
            file=sys.stderr,
        )
    if evidence.catalog_statistics_failure is not None:
        print(
            "catalog table statistics were not refreshed: "
            f"{evidence.catalog_statistics_failure}; the next publication "
            "analyzes the catalog tables again",
            file=sys.stderr,
        )
    spm_recording = evidence.spm_availability
    if (
        spm_recording is not None
        and spm_recording.versions_unreadable is not None
        and spm_recording.not_recorded
    ):
        print(
            "SPM availability was not recorded: "
            f"{spm_recording.versions_unreadable}; /v2/model-catalog reports a "
            "version without a recorded availability as unknown until a "
            "publication records it",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
