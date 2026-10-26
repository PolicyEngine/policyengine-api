"""A process-wide store of the catalog versions metadata reads have selected."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog

CatalogSelectionKey = tuple[str, str | None]
"""A country ID and the requested PolicyEngine.py version.

A version of None means the running version, which is fixed for the process.
"""


class SelectedCatalogStore:
    """Keep each catalog version a request has selected, for the process's life.

    A published catalog version never changes, so once a request has found it,
    later requests for the same country and version need not query for it
    again. Only successful selections are kept: an unsupported country, an
    invalid version or an absent catalog is looked up, and fails, each time.
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
