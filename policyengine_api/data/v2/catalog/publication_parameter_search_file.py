"""Write the parameter search file of each catalog version being published.

A file is built from the installed packages' catalog, never from rows an
earlier release stored, so publication writes one only for the versions it
publishes: each new version, and the installed version when an earlier
release stored it before search files existed. Writing only inserts. A stored
file of the same format must equal the one built from the installed packages,
because the stored version's other rows already match them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa

from policyengine_api.data.v2.catalog.parameter_search_file import (
    PARAMETER_SEARCH_FILE_FORMAT,
    country_search_file,
    encode_parameter_search_file,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import V2_METADATA

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy import Connection

    from policyengine_api.data.v2.catalog.records import CountryCatalog

MODELS = V2_METADATA.tables["tax_benefit_models"]
MODEL_VERSIONS = V2_METADATA.tables["tax_benefit_model_versions"]
PARAMETER_SEARCH_FILES = V2_METADATA.tables["parameter_search_files"]


def _stored_version_id(connection: Connection, country: CountryCatalog) -> UUID:
    version_id: UUID = connection.execute(
        sa.select(MODEL_VERSIONS.c.id)
        .select_from(
            MODEL_VERSIONS.join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(
            MODELS.c.name == country.model.name,
            MODEL_VERSIONS.c.version == country.model_version.version,
        )
    ).scalar_one()
    return version_id


def _stored_content_sha256(connection: Connection, version_id: UUID) -> str | None:
    content_sha256: str | None = connection.execute(
        sa.select(PARAMETER_SEARCH_FILES.c.content_sha256).where(
            PARAMETER_SEARCH_FILES.c.tax_benefit_model_version_id == version_id,
            PARAMETER_SEARCH_FILES.c.file_format == PARAMETER_SEARCH_FILE_FORMAT,
        )
    ).scalar_one_or_none()
    return content_sha256


def write_parameter_search_files(
    connection: Connection,
    countries: Sequence[CountryCatalog],
) -> tuple[tuple[str, str, int, int], ...]:
    """Write the search file of each published version that has none.

    Returns the model name, version and uncompressed and compressed sizes of
    each file written, in model name order. Runs inside publication's
    transaction and advisory lock, after the versions are stored.
    """
    written = []
    for country in sorted(countries, key=lambda item: item.model.name):
        version_id = _stored_version_id(connection, country)
        encoded = encode_parameter_search_file(country_search_file(country))
        stored_sha256 = _stored_content_sha256(connection, version_id)
        if stored_sha256 is None:
            connection.execute(
                sa.insert(PARAMETER_SEARCH_FILES).values(
                    id=uuid4(),
                    tax_benefit_model_version_id=version_id,
                    file_format=PARAMETER_SEARCH_FILE_FORMAT,
                    compressed_content=encoded.compressed_content,
                    content_sha256=encoded.content_sha256,
                    uncompressed_size=encoded.uncompressed_size,
                    compressed_size=encoded.compressed_size,
                )
            )
            written.append(
                (
                    country.model.name,
                    country.model_version.version,
                    encoded.uncompressed_size,
                    encoded.compressed_size,
                )
            )
        elif stored_sha256 != encoded.content_sha256:
            msg = (
                "the stored parameter search file of catalog version "
                f"{country.model_version.version} of {country.model.name} differs "
                "from the installed packages' catalog"
            )
            raise CatalogPublicationError(msg)
    return tuple(written)


def assert_parameter_search_files_written(
    connection: Connection,
    countries: Sequence[CountryCatalog],
) -> None:
    """Raise CatalogPublicationError if a catalog country's version has no file."""
    for country in countries:
        version_id = _stored_version_id(connection, country)
        if _stored_content_sha256(connection, version_id) is None:
            msg = (
                f"the {country.country_id} catalog version "
                f"{country.model_version.version} has no parameter search file"
            )
            raise CatalogPublicationError(msg)
