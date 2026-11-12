"""Household job rows' result documents, as the v2 household functions write them.

A succeeded job's ``result`` is the simulation contract's
``HouseholdExecutionResult``. The contract names exactly one policy, so its
``output`` holds that policy's calculated household, warnings and SPM receipt
beside the SPM selection applied. A failed job's is
``HouseholdExecutionFailure``, with a one-line summary in ``error_message``;
a job that failed unexpectedly has a null ``result``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

JOB_ID = UUID("00000000-0000-4000-8000-0000000000c1")
WORKER = {
    "application_name": "policyengine-v2-worker-6-10-0",
    "function_name": "calculate_household_us",
}
BUNDLE = {
    "policyengine_version": "6.10.0",
    "core_package_version": "3.33.0",
    "country_package_name": "policyengine-us",
    "country_package_version": "1.450.0",
    "bundle_manifest_sha256": "a" * 64,
}
SPM_CONFIG = {
    "forecast_content_sha256": "3d" * 32,
    "scenario": "ce_trend",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
SPM_PROVENANCE = {"schema_version": "canonical-spm-provenance-v2", "years": ["2026"]}
# Keys in the order the household function wrote them, which is not sorted:
# the household's people come before its groups, and each person's
# variables in the order the caller sent them.
CALCULATED_HOUSEHOLD = {
    "people": {
        "person-1": {"employment_income": {"2026": 30000}, "age": {"2026": 40}},
    },
    "households": {
        "household-1": {
            "members": ["person-1"],
            "state_name": {"2026": "CA"},
            "household_net_income": {"2026": 27000.5},
        }
    },
    "families": {"family-1": {"members": ["person-1"]}},
    "tax_units": {"tax_unit-1": {"members": ["person-1"]}},
    "spm_units": {"spm_unit-1": {"members": ["person-1"]}},
    "marital_units": {"marital_unit-1": {"members": ["person-1"]}},
}
WARNING = "The input `age_group` is deprecated and was ignored."
INPUT_ERROR = {
    "type": "household_variable",
    "name": "not_a_variable",
    "path": "people.person-1.not_a_variable",
    "message": "not_a_variable is not a variable of policyengine-us.",
}
FAILURE_SUMMARY = "invalid_inputs: The household names a variable the model lacks."


def succeeded_document(**output_changes: object) -> dict[str, Any]:
    """Return a succeeded job's result document; ``None`` changes drop a field."""
    output: dict[str, Any] = {
        "country": "us",
        "bundle": BUNDLE,
        "spm_config": SPM_CONFIG,
        "household": CALCULATED_HOUSEHOLD,
        "warnings": [WARNING],
        "spm_provenance": SPM_PROVENANCE,
    }
    output.update(output_changes)
    output = {name: value for name, value in output.items() if value is not None}
    return {
        "status": "succeeded",
        "schema_version": 1,
        "calculation_id": str(JOB_ID),
        "output": output,
        "worker": WORKER,
    }


def failed_document() -> dict[str, Any]:
    """Return the result document of a job whose household function refused it."""
    return {
        "status": "failed",
        "schema_version": 1,
        "calculation_id": str(JOB_ID),
        "error": {
            "code": "invalid_inputs",
            "message": "The household names a variable the model lacks.",
            "input_errors": [INPUT_ERROR],
        },
        "worker": WORKER,
    }
