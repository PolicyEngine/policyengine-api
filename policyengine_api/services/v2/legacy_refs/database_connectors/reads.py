"""Batched v1 artifact existence reads through the v1 mapped models."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from policyengine_api.data.v1_models import (
    Household,
    Policy,
    ReportOutput,
    Simulation,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind


READ_BATCH_SIZE = 500


def _identity_columns(
    kind: LegacyRecordKind,
) -> tuple[InstrumentedAttribute[int], InstrumentedAttribute[str]]:
    if kind is LegacyRecordKind.POLICY:
        return Policy.id, Policy.country_id
    if kind is LegacyRecordKind.HOUSEHOLD:
        return Household.id, Household.country_id
    if kind is LegacyRecordKind.SIMULATION:
        return Simulation.id, Simulation.country_id
    return ReportOutput.id, ReportOutput.country_id


def read_existing_legacy_ids(
    session: Session,
    *,
    kind: LegacyRecordKind,
    country_id: str,
    legacy_ids: Collection[int],
) -> frozenset[int]:
    """Return the requested IDs that exist for the country, in bounded batches."""

    id_column, country_column = _identity_columns(kind)
    requested = sorted(set(legacy_ids))
    existing: set[int] = set()
    for start in range(0, len(requested), READ_BATCH_SIZE):
        batch = requested[start : start + READ_BATCH_SIZE]
        existing.update(
            int(legacy_id)
            for legacy_id in session.execute(
                select(id_column)
                .where(country_column == country_id, id_column.in_(batch))
                .distinct()
            ).scalars()
        )
    return frozenset(existing)
