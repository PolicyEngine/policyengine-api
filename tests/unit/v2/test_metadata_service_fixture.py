"""Tests of the metadata service tests' catalog database fixture.

The fixture is in tests/fixtures/v2_metadata_service.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlmodel import col

from policyengine_api.data.v2.models import TaxBenefitModelVersion
from tests.fixtures.v2_metadata_service_helpers import (
    catalog_service,
    stored_model_version,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

pytest_plugins = ("tests.fixtures.v2_metadata_service",)

CHANGED_DESCRIPTION = "Changed by another session after the commit"


def test_the_catalog_session_reads_a_row_changed_after_its_commit(
    catalog_sessions: sessionmaker[Session], catalog_session: Session
) -> None:
    """A commit expires the session's rows, so its next read sees stored values.

    The test keeps the loaded model version, so the session's identity map
    still holds it when the service reads the version again.
    """
    model_version = stored_model_version(catalog_session, "policyengine-us")
    model_version_id = model_version.id
    catalog_session.commit()
    with catalog_sessions.begin() as other_session:
        other_session.execute(
            update(TaxBenefitModelVersion)
            .where(col(TaxBenefitModelVersion.id) == model_version_id)
            .values(description=CHANGED_DESCRIPTION)
        )

    read = catalog_service(catalog_session).get_model_version("us", model_version_id)

    assert read.item.description == CHANGED_DESCRIPTION
