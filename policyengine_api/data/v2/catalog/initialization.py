"""Explicit command boundary for one-time v2 catalog initialization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import sys

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_installed_catalog,
)
from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    PublicationEvidence,
    publish_catalog,
)
from policyengine_api.data.v2.catalog.records import NormalizedCatalog
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_data_write_database_settings,
)


def build_data_write_engine(settings: V2DatabaseSettings) -> Engine:
    """Build an isolated, unpooled engine for one initialization attempt."""

    return create_engine(settings.connection.url, poolclass=NullPool)


def initialize_catalog(
    environ: Mapping[str, str] | None = None,
    *,
    extractor: Callable[[], NormalizedCatalog] = extract_installed_catalog,
    engine_builder: Callable[[V2DatabaseSettings], Engine] = build_data_write_engine,
    publisher: Callable[[Engine, NormalizedCatalog], PublicationEvidence] = (
        publish_catalog
    ),
) -> PublicationEvidence:
    """Load only row-write settings, extract fully, then publish explicitly."""

    settings = load_v2_data_write_database_settings(environ)
    catalog = extractor()
    engine = engine_builder(settings)
    try:
        return publisher(engine, catalog)
    finally:
        engine.dispose()


def _error_payload(error: Exception) -> dict[str, object]:
    safe_errors = (
        V2ConfigurationError,
        CatalogExtractionError,
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
    except Exception as error:  # noqa: BLE001 - command must return safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
