"""Check v1 artifact references before a v2 association transaction opens.

The read uses the v1 mapped models through the v1 session factory in a short
transaction that is rolled back and closed before the caller opens its v2
transaction. It never writes, so it deliberately avoids
``resolve_report_output``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping

from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
from policyengine_api.services.v2.legacy_refs.database_connectors.reads import (
    read_existing_legacy_ids,
)
from policyengine_api.services.v2.legacy_refs.database_session import (
    LegacyReferenceDatabaseSession,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.legacy_refs.validators import (
    require_legacy_references,
)


class V1LegacyReferenceService:
    """Batched, read-only v1 existence checks."""

    def __init__(self, database_session: LegacyReferenceDatabaseSession) -> None:
        self._database_session = database_session

    def existing_ids(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> dict[LegacyRecordKind, frozenset[int]]:
        """Return existing IDs per kind using one short v1 transaction."""

        selected = {kind: ids for kind, ids in requested.items() if ids}
        if not selected:
            return {kind: frozenset() for kind in requested}
        with self._database_session.read() as session:
            existing = {
                kind: read_existing_legacy_ids(
                    session,
                    kind=kind,
                    country_id=country_id,
                    legacy_ids=ids,
                )
                for kind, ids in selected.items()
            }
        return {kind: existing.get(kind, frozenset()) for kind in requested}

    def require_existing(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> None:
        """Raise ``LegacyReferenceNotFoundError`` for any missing reference."""

        existing = self.existing_ids(country_id=country_id, requested=requested)
        for kind, ids in requested.items():
            require_legacy_references(
                kind,
                country_id=country_id,
                requested=ids,
                existing=existing[kind],
            )


class DeferredLegacyReferenceService:
    """Build the v1 reference service only when a reference is checked.

    Reads, lists, deletes, and most account routes never check v1
    references, so they must not depend on the v1 database configuration.
    """

    def __init__(self, build: Callable[[], LegacyReferenceChecker]) -> None:
        self._build = build
        self._service: LegacyReferenceChecker | None = None

    def _resolved(self) -> LegacyReferenceChecker:
        if self._service is None:
            self._service = self._build()
        return self._service

    def existing_ids(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> dict[LegacyRecordKind, frozenset[int]]:
        return self._resolved().existing_ids(country_id=country_id, requested=requested)

    def require_existing(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> None:
        self._resolved().require_existing(country_id=country_id, requested=requested)
