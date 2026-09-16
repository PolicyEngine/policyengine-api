#!/usr/bin/env python3
"""Export the versioned Stage 12 contracts for the companion service."""

from pathlib import Path

from policyengine_api.services.v2.stage12_contract_export import (
    write_contract_document,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "docs/generated/stage12_worker_contracts.json"


if __name__ == "__main__":
    write_contract_document(OUTPUT_PATH)
