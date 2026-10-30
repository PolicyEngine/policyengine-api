"""The installed PolicyEngine.py catalog, extracted once per test process.

Extraction takes minutes on a CI runner, so the two tests that need the
complete catalog share one copy when pytest runs them together, as the
full-catalog-integration job in .github/workflows/v2-integration-check.yml
does. The catalog's records are frozen dataclasses held in tuples, so neither
test can change what the other reads.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.extraction import extract_installed_catalog

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.records import NormalizedCatalog


@cache
def installed_catalog() -> NormalizedCatalog:
    """Return the installed catalog, extracting it on the first call only."""
    return extract_installed_catalog()
