"""Households and helpers for the live staging household calculation checks.

They need only httpx and the standard library, because the parallel live test
job installs nothing else.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

CALCULATION_PATH = "/v2/household-calculations"
CALCULATION_TIMEOUT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_CALCULATION_TIMEOUT_SECONDS", "600")
)
POLL_INTERVAL_SECONDS = float(
    os.environ.get("STAGING_API_TEST_POLL_INTERVAL_SECONDS", "5")
)
TRANSIENT_STATUS_CODES = {500, 502, 503, 504}
FINISHED_STATUSES = {"succeeded", "failed"}
YEAR = "2026"
COLLECTIONS = {
    "us": {
        "household": "households",
        "family": "families",
        "tax_unit": "tax_units",
        "spm_unit": "spm_units",
        "marital_unit": "marital_units",
    },
    "uk": {"household": "households", "benunit": "benunits"},
}


@dataclass(frozen=True)
class LiveHousehold:
    """A household whose people all share one group of each kind.

    ``people`` and ``groups`` map variable names to values by period; a null
    value asks for the variable to be calculated. ``axes`` vary inputs across
    points, as in a ``/calculate`` situation.
    """

    name: str
    country_id: str
    people: dict[str, dict[str, Any]]
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    axes: list[list[dict[str, Any]]] | None = None

    def document(self) -> dict[str, Any]:
        """Return the household as ``/v2/households`` stores it."""
        collections = COLLECTIONS[self.country_id]
        document: dict[str, Any] = {
            "people": [
                {
                    "id": person_id,
                    "values": values,
                    "memberships": {
                        collection: f"{collection}-1" for collection in collections
                    },
                }
                for person_id, values in self.people.items()
            ]
        }
        for collection in collections:
            document[collection] = [
                {"id": f"{collection}-1", "values": self.groups.get(collection, {})}
            ]
        return document

    def situation(self) -> dict[str, Any]:
        """Return the same household as a ``/calculate`` situation."""
        situation: dict[str, Any] = {"people": self.people}
        for collection, plural in COLLECTIONS[self.country_id].items():
            situation[plural] = {
                f"{collection}-1": {
                    "members": list(self.people),
                    **self.groups.get(collection, {}),
                }
            }
        if self.axes is not None:
            situation["axes"] = self.axes
        return situation


@dataclass(frozen=True)
class FinishedCalculation:
    """A calculation's final answer and how long each step took."""

    item: dict[str, Any]
    submit_seconds: float
    total_seconds: float


def store_household(client: httpx.Client, household: LiveHousehold) -> str:
    """Store the household through ``/v2/households`` and return its ID."""
    response = client.post(
        "/v2/households",
        params={"country_id": household.country_id},
        json={
            "country_id": household.country_id,
            "default_year": int(YEAR),
            "household_data": household.document(),
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["result"]["item"]["id"]


def calculate(
    client: httpx.Client,
    household: LiveHousehold,
    household_id: str,
) -> FinishedCalculation:
    """Submit the stored household's calculation and poll until it finishes."""
    started = time.monotonic()
    body: dict[str, Any] = {
        "country_id": household.country_id,
        "household_id": household_id,
    }
    if household.axes is not None:
        body["axes"] = household.axes
    response = client.post(CALCULATION_PATH, json=body)
    submit_seconds = time.monotonic() - started
    assert response.status_code == 202, response.text
    item = response.json()["result"]
    deadline = started + CALCULATION_TIMEOUT_SECONDS
    while item["status"] not in FINISHED_STATUSES:
        if time.monotonic() >= deadline:
            msg = (
                f"Calculation {item['calculation_id']} did not finish within "
                f"{CALCULATION_TIMEOUT_SECONDS:.0f} s; last status {item['status']}"
            )
            raise AssertionError(msg)
        time.sleep(POLL_INTERVAL_SECONDS)
        polled = client.get(f"{CALCULATION_PATH}/{item['calculation_id']}")
        if polled.status_code in TRANSIENT_STATUS_CODES:
            continue
        assert polled.status_code == 200, polled.text
        item = polled.json()["result"]
    return FinishedCalculation(
        item=item,
        submit_seconds=submit_seconds,
        total_seconds=time.monotonic() - started,
    )


def calculate_with_v1(client: httpx.Client, household: LiveHousehold) -> dict:
    """Return API v1's ``/calculate`` answer for the same household."""
    response = client.post(
        f"/{household.country_id}/calculate",
        json={"household": household.situation()},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok", payload
    return payload


def _same_value(v1_value: object, v2_value: object) -> bool:
    if isinstance(v1_value, list) and isinstance(v2_value, list):
        return len(v1_value) == len(v2_value) and all(
            _same_value(v1_item, v2_item)
            for v1_item, v2_item in zip(v1_value, v2_value, strict=True)
        )
    # API v1 writes an undefined number as a bare NaN; v2 writes "NaN".
    if isinstance(v1_value, float) and math.isnan(v1_value):
        return v2_value == "NaN"
    if isinstance(v1_value, bool) or isinstance(v2_value, bool):
        return v1_value == v2_value
    if isinstance(v1_value, int | float) and isinstance(v2_value, int | float):
        return math.isclose(v1_value, v2_value, rel_tol=1e-9, abs_tol=1e-6)
    return v1_value == v2_value


def household_differences(
    v1_household: dict[str, Any], v2_household: dict[str, Any]
) -> list[str]:
    """Return every value that differs between the two calculated households.

    Each entity, variable and period in either household is compared, so a
    value only one of them has is a difference too.
    """
    differences: list[str] = []
    for plural in sorted(set(v1_household) | set(v2_household)):
        v1_entities = v1_household.get(plural)
        v2_entities = v2_household.get(plural)
        if not isinstance(v1_entities, dict) or not isinstance(v2_entities, dict):
            if v1_entities != v2_entities:
                differences.append(f"{plural}: {v1_entities!r} != {v2_entities!r}")
            continue
        for entity_id in sorted(set(v1_entities) | set(v2_entities)):
            v1_variables = v1_entities.get(entity_id) or {}
            v2_variables = v2_entities.get(entity_id) or {}
            for variable in sorted(set(v1_variables) | set(v2_variables)):
                v1_value = v1_variables.get(variable)
                v2_value = v2_variables.get(variable)
                if variable == "members" or not (
                    isinstance(v1_value, dict) and isinstance(v2_value, dict)
                ):
                    if not _same_value(v1_value, v2_value):
                        differences.append(
                            f"{plural}.{entity_id}.{variable}: "
                            f"{v1_value!r} != {v2_value!r}"
                        )
                    continue
                differences.extend(
                    f"{plural}.{entity_id}.{variable}.{period}: "
                    f"{v1_value.get(period)!r} != {v2_value.get(period)!r}"
                    for period in sorted(set(v1_value) | set(v2_value))
                    if not _same_value(v1_value.get(period), v2_value.get(period))
                )
    return differences
