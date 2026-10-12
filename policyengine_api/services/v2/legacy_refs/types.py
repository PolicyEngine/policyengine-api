"""Framework-independent v1 artifact reference types."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, Strict


MAXIMUM_LEGACY_RECORD_ID = 2**63 - 1

LegacyRecordId = Annotated[
    int,
    Strict(),
    Field(
        ge=1,
        le=MAXIMUM_LEGACY_RECORD_ID,
        description="Exact v1 database identifier (a JSON integer)",
    ),
]


class LegacyRecordKind(StrEnum):
    POLICY = "policy"
    HOUSEHOLD = "household"
    SIMULATION = "simulation"
    REPORT = "report"
