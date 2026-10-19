"""A bounded, process-wide store of serialized v2 metadata catalog documents."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.services.v2.metadata.types import MetadataCatalogDocument

CatalogKey = tuple[str, str]
"""A country ID and the exact PolicyEngine.py version of its catalog."""

DEFAULT_CATALOG_CAPACITY = 4


class MetadataCatalogCache:
    """Keep the most recently used catalog documents, built at most once each.

    A published catalog version never changes, so its document is kept until
    newer documents push it out (least recently used first). Requests for a
    document that is being built wait for that build instead of starting
    another; a failed build keeps nothing, so the next request tries again.
    """

    def __init__(self, *, capacity: int = DEFAULT_CATALOG_CAPACITY) -> None:
        """Keep at most ``capacity`` documents (at least one)."""
        if capacity < 1:
            msg = "capacity must be positive"
            raise ValueError(msg)
        self._capacity = capacity
        self._documents: OrderedDict[CatalogKey, MetadataCatalogDocument] = (
            OrderedDict()
        )
        self._lock = threading.Lock()
        self._build_locks: dict[CatalogKey, threading.Lock] = {}

    def _stored(self, key: CatalogKey) -> MetadataCatalogDocument | None:
        with self._lock:
            document = self._documents.get(key)
            if document is not None:
                self._documents.move_to_end(key)
            return document

    def get_or_build(
        self,
        key: CatalogKey,
        build: Callable[[], MetadataCatalogDocument],
    ) -> MetadataCatalogDocument:
        """Return the document for ``key``, calling ``build`` only when none is kept."""
        document = self._stored(key)
        if document is not None:
            return document
        with self._lock:
            build_lock = self._build_locks.setdefault(key, threading.Lock())
        with build_lock:
            document = self._stored(key)
            if document is not None:
                return document
            document = build()
            with self._lock:
                self._documents[key] = document
                self._documents.move_to_end(key)
                while len(self._documents) > self._capacity:
                    self._documents.popitem(last=False)
                self._build_locks.pop(key, None)
            return document
