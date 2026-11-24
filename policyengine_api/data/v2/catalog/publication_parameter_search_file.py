"""Write the parameter search file of each catalog version being published.

A file is built from the installed packages' catalog, never from rows an
earlier release stored, so publication writes one only for the versions it
publishes: each new version, and the installed version when an earlier
release stored it before search files existed. Writing only inserts. A stored
file of the same format must equal the one built from the installed packages,
because the stored version's other rows already match them.

A version stored before catalog format 2 (``catalog_format`` null) has no
stored economy or household flags, so a file built from the installed
catalog's flags would contradict its own parameter rows: it gets no file and
is not required to have one, and the route reports it as a version without a
file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import col

from policyengine_api.data.v2.catalog.parameter_search_file import (
    PARAMETER_SEARCH_FILE_FORMAT,
    country_search_file,
    encode_parameter_search_file,
)
from policyengine_api.data.v2.catalog.publication_reconciliation import (
    StoredVersion,
    stored_version,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import ParameterSearchFile

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.catalog.records import CountryCatalog


def _version_for_search_file(
    session: Session, country: CountryCatalog
) -> StoredVersion:
    stored = stored_version(session, country)
    if stored is None:
        msg = (
            f"the {country.country_id} catalog version "
            f"{country.model_version.version} is not stored"
        )
        raise CatalogPublicationError(msg)
    return stored


def _stored_content_sha256(session: Session, version_id: UUID) -> str | None:
    content_sha256: str | None = session.execute(
        sa.select(col(ParameterSearchFile.content_sha256)).where(
            col(ParameterSearchFile.tax_benefit_model_version_id) == version_id,
            col(ParameterSearchFile.file_format) == PARAMETER_SEARCH_FILE_FORMAT,
        )
    ).scalar_one_or_none()
    return content_sha256


def write_parameter_search_files(
    session: Session,
    countries: Sequence[CountryCatalog],
) -> tuple[tuple[str, str, int, int], ...]:
    """Write the search file of each published format 2 version that has none.

    Returns the model name, version and uncompressed and compressed sizes of
    each file written, in model name order. Runs inside publication's
    transaction and advisory lock, after the versions are stored.
    """
    written = []
    for country in sorted(countries, key=lambda item: item.model.name):
        stored = _version_for_search_file(session, country)
        if stored.catalog_format is None:
            continue
        encoded = encode_parameter_search_file(country_search_file(country))
        stored_sha256 = _stored_content_sha256(session, stored.id)
        if stored_sha256 is None:
            session.execute(
                sa.insert(ParameterSearchFile).values(
                    id=uuid4(),
                    tax_benefit_model_version_id=stored.id,
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
    session: Session,
    countries: Sequence[CountryCatalog],
) -> None:
    """Raise CatalogPublicationError if a catalog country's version has no file.

    A version stored before catalog format 2 is exempt: it gets no file.
    """
    for country in countries:
        stored = _version_for_search_file(session, country)
        if stored.catalog_format is None:
            continue
        if _stored_content_sha256(session, stored.id) is None:
            msg = (
                f"the {country.country_id} catalog version "
                f"{country.model_version.version} has no parameter search file"
            )
            raise CatalogPublicationError(msg)
