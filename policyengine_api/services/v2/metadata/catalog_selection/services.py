"""Select the catalog version each of a request's metadata reads uses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    validate_policyengine_version,
)
from policyengine_api.services.v2.metadata.database_connectors.reads import (
    read_catalog_values_pruned_at,
    read_metadata_catalog,
)
from policyengine_api.services.v2.metadata.validators import (
    require_current_law_values,
    validate_metadata_page,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.catalog_selection_validation import (
        SelectedCatalog,
    )
    from policyengine_api.services.v2.metadata.database_session import (
        MetadataDatabaseSession,
    )
    from policyengine_api.services.v2.metadata.process_state import (
        SelectedCatalogStore,
    )


class MetadataCatalogSelection:
    """Select the country's catalog for a request's metadata reads.

    A read names a PolicyEngine.py version, or none for the running version.
    With ``selected_catalogs``, a catalog version found once is taken from
    that store instead of being queried again.
    """

    def __init__(
        self,
        database_session: MetadataDatabaseSession,
        *,
        running_policyengine_version: str,
        selected_catalogs: SelectedCatalogStore | None,
    ) -> None:
        """Bind to a request's session and the running PolicyEngine.py version."""
        self._database_session = database_session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )
        self._selected_catalogs = selected_catalogs

    def select(
        self,
        country_id: str,
        policyengine_version: str | None,
        *,
        reads_current_law: bool = False,
    ) -> SelectedCatalog:
        """Return the country's catalog for the version, or the running one.

        ``reads_current_law`` marks a read of the rows catalog pruning deletes
        (current-law values, parameter tree rows, the search file): it raises
        CatalogValuesPrunedError before that read when the version is pruned.
        A selection the process kept while the version was pruned may predate
        a publication that restored it, so the version's
        ``catalog_values_pruned_at`` is read again first, one more query made
        only then; once it is clear, the version is selected again and kept.
        """
        key = (country_id, policyengine_version)
        kept = (
            None
            if self._selected_catalogs is None
            else self._selected_catalogs.get(key)
        )
        if kept is not None:
            if (
                not reads_current_law
                or kept.model_version.catalog_values_pruned_at is None
            ):
                return kept
            require_current_law_values(
                kept,
                pruned_at=read_catalog_values_pruned_at(
                    self._database_session.session,
                    model_version_id=kept.model_version.id,
                ),
            )
        selected = read_metadata_catalog(
            self._database_session.session,
            country_id=country_id,
            running_policyengine_version=self._running_policyengine_version,
            policyengine_version=policyengine_version,
        )
        if self._selected_catalogs is not None:
            self._selected_catalogs.keep(key, selected)
        if reads_current_law:
            require_current_law_values(
                selected, pruned_at=selected.model_version.catalog_values_pruned_at
            )
        return selected

    def require_unpruned(self, selected: SelectedCatalog, *, rows_found: bool) -> None:
        """Raise CatalogValuesPrunedError if pruning removed the version's data."""
        # Raise CatalogValuesPrunedError if pruning removed the version's
        # current-law data. A selection kept for the process may predate the
        # pruning, so a read that found nothing reads the marker again; one
        # that found rows answers with them.
        pruned_at = selected.model_version.catalog_values_pruned_at
        if pruned_at is None and not rows_found:
            pruned_at = read_catalog_values_pruned_at(
                self._database_session.session,
                model_version_id=selected.model_version.id,
            )
        require_current_law_values(selected, pruned_at=pruned_at)

    def select_page(
        self,
        country_id: str,
        policyengine_version: str | None,
        *,
        offset: int,
        limit: int,
        reads_current_law: bool = False,
    ) -> SelectedCatalog:
        """Validate a page's offset and limit, then select as ``select`` does."""
        validate_metadata_page(offset, limit)
        return self.select(
            country_id, policyengine_version, reads_current_law=reads_current_law
        )
