"""A process-wide store of the catalog versions metadata reads have selected."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.catalog_selection_validation import (
        SelectedCatalog,
    )

CatalogSelectionKey = tuple[str, str | None]
"""A country ID and the requested PolicyEngine.py version.

A version of None means the running version, which is fixed for the process.
"""


class SelectedCatalogStore:
    """Keep each catalog version a request has selected, for the process's life.

    After publication a catalog version's row changes only in its
    time-period options, which a release's publication replaces before that
    release's processes start, its ``catalog_last_published_at``, which each
    publication of it sets and no read uses, and its
    ``catalog_values_pruned_at``, which pruning sets and restoration clears,
    and its ``spm_availability``, which publication records once after
    publishing it. So once a request has found the version, later requests
    for the same country and version need not query for it again; a process
    of the previous release keeps the time-period options it read, and a
    process that found a version before its SPM availability was recorded
    offers no SPM settings for it until it restarts.

    A kept ``catalog_values_pruned_at`` can be out of date in either
    direction, so ``MetadataCatalogSelection`` checks it for the reads of the
    rows pruning deletes. When the kept selection has it clear and the read
    finds no rows, the version may have been pruned since: the column is read
    again. When the kept selection has it set, the version may have been
    restored since: the column is read again before the read, and once it is
    clear the version is selected again and the new selection kept. Only
    successful selections are kept: an unsupported country, an invalid
    version or an absent catalog is looked up, and fails, each time.
    The kept records are detached, fully loaded rows that are only read.
    """

    def __init__(self) -> None:
        """Start with no selections kept."""
        self._selections: dict[CatalogSelectionKey, SelectedCatalog] = {}
        self._lock = threading.Lock()

    def get(self, key: CatalogSelectionKey) -> SelectedCatalog | None:
        """Return the selection kept for ``key``, or None."""
        with self._lock:
            return self._selections.get(key)

    def keep(self, key: CatalogSelectionKey, selected: SelectedCatalog) -> None:
        """Keep ``selected`` as the selection for ``key``."""
        with self._lock:
            self._selections[key] = selected
