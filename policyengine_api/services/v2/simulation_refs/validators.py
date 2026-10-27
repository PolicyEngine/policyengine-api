"""Database-independent validation of v2 report and simulation references."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
)

if TYPE_CHECKING:
    from uuid import UUID


class SimulationReferenceNotFoundError(LookupError):
    """The simulation service has no such report or simulation in the country."""


def require_reference_in_country(
    found_country_id: str | None,
    *,
    kind: str,
    reference_id: UUID,
    country_id: str,
) -> None:
    """Raise ``SimulationReferenceNotFoundError`` unless the record is the country's.

    ``found_country_id`` is the found record's country, or None when the
    simulation service has no such record.
    """
    if found_country_id != country_id:
        msg = f"v2 {kind} {reference_id} was not found for country {country_id}"
        raise SimulationReferenceNotFoundError(msg)


def require_migrated_from(
    found_legacy_report_id: int | None,
    *,
    report_id: UUID,
    legacy_report_id: int,
) -> None:
    """Raise unless the v2 report was migrated from that v1 report output.

    ``found_legacy_report_id`` is the v1 report output the simulation service
    records the report was migrated from, or None for a report created on v2.
    Raise ``AssociationReferenceConflictError`` when they differ, because a
    saved report holding both references records that migration.
    """
    if found_legacy_report_id != legacy_report_id:
        msg = (
            f"v2 report {report_id} was not migrated from v1 report {legacy_report_id}"
        )
        raise AssociationReferenceConflictError(msg)
