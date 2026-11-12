"""Database selections of household jobs, which the simulation service writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import HouseholdJob

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session


def read_household_job(session: Session, job_id: UUID) -> HouseholdJob | None:
    """Return the household job with this ID, or None."""
    return session.get(HouseholdJob, job_id)
