"""Database selection of a catalog version's stored parameter search file."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlmodel import Session, col

from policyengine_api.data.v2.models import ParameterSearchFile
from policyengine_api.services.v2.metadata.database_connectors.reads import read_rows

if TYPE_CHECKING:
    from uuid import UUID


def read_parameter_search_file(
    session: Session,
    *,
    model_version_id: UUID,
    file_format: int,
) -> list[Any]:
    """Return the version's search file of the given format: one row, or none.

    One read of the unique (version, file format) index. The row has the
    file format, the compressed content, the content hash and both sizes.
    """
    return read_rows(
        session,
        sa.select(
            col(ParameterSearchFile.file_format).label("file_format"),
            col(ParameterSearchFile.compressed_content).label("compressed_content"),
            col(ParameterSearchFile.content_sha256).label("content_sha256"),
            col(ParameterSearchFile.uncompressed_size).label("uncompressed_size"),
            col(ParameterSearchFile.compressed_size).label("compressed_size"),
        ).where(
            col(ParameterSearchFile.tax_benefit_model_version_id) == model_version_id,
            col(ParameterSearchFile.file_format) == file_format,
        ),
    )
