"""Explicit command boundary for one-time v2 catalog initialization."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

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
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_data_write_database_settings,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from policyengine_api.data.v2.catalog.records import NormalizedCatalog


# The environment variable holding the Hugging Face read token; PolicyEngine
# Core's data downloads read the same variable.
HUGGING_FACE_CREDENTIAL_VARIABLE = "HUGGING_FACE_TOKEN"
# Countries whose certified data repository needs the read token.
PRIVATE_DATA_COUNTRIES = frozenset({"uk"})


def build_data_write_engine(settings: V2DatabaseSettings) -> Engine:
    """Build an isolated, unpooled engine for one initialization attempt."""
    return create_engine(settings.connection.url, poolclass=NullPool)


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
    engine: Engine,
    catalog: NormalizedCatalog,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Check the regions of countries whose catalog version is not stored yet.

    Publication writes nothing for the other countries and only compares them
    with what is stored, so their artifacts are not read.
    """
    verify_installed_region_data(
        catalog, unpublished_countries(engine, catalog), environ
    )


def initialize_catalog(
    environ: Mapping[str, str] | None = None,
    *,
    extractor: Callable[[], NormalizedCatalog] = extract_installed_catalog,
    engine_builder: Callable[[V2DatabaseSettings], Engine] = build_data_write_engine,
    publisher: Callable[[Engine, NormalizedCatalog], PublicationEvidence] = (
        publish_catalog
    ),
    region_data_verifier: Callable[
        [Engine, NormalizedCatalog, Mapping[str, str] | None], None
    ] = verify_unpublished_region_data,
) -> PublicationEvidence:
    """Load only row-write settings, extract fully, verify, then publish explicitly."""
    settings = load_v2_data_write_database_settings(environ)
    catalog = extractor()
    engine = engine_builder(settings)
    try:
        region_data_verifier(engine, catalog, environ)
        return publisher(engine, catalog)
    finally:
        engine.dispose()


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
    """Run explicit initialization and return a shell-compatible status."""
    try:
        evidence = initialize_catalog()
    except Exception as error:  # noqa: BLE001  # command must return safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
