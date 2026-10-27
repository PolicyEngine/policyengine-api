"""Households and helpers for the live staging household calculation checks.

They need only httpx and the standard library, because the parallel live test
job installs nothing else.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

CALCULATION_PATH = "/v2/household-calculations"
CALCULATION_TIMEOUT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_CALCULATION_TIMEOUT_SECONDS", "600")
)
POLL_INTERVAL_SECONDS = float(
    os.environ.get("STAGING_API_TEST_POLL_INTERVAL_SECONDS", "5")
)
# A 502, 503 or 504 can be a short outage, such as the simulation service
# failing to read its database or version manifest for a moment; each request
# is sent again while such answers last at most TRANSIENT_LIMIT_SECONDS in a
# row. Any other failure, and a longer outage, fails the check at once with
# the answer's body.
TRANSIENT_STATUS_CODES = {502, 503, 504}
TRANSIENT_LIMIT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_TRANSIENT_LIMIT_SECONDS", "90")
)
FINISHED_STATUSES = {"succeeded", "failed"}
YEAR = "2026"
REFORM_START = f"{YEAR}-01-01"
OPEN_END = "2100-12-31"
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
    points, as in a ``/calculate`` situation. ``reform`` sets each named
    parameter to a value from the start of ``YEAR`` with no end, through a
    policy stored with ``/v2/policies``. ``add_missing_variables`` calculates
    every variable the household lacks, as ``/calculate-full`` does.
    ``expects_warnings`` says the household has an input the country model
    ignores with a warning.
    """

    name: str
    country_id: str
    people: dict[str, dict[str, Any]]
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    axes: list[list[dict[str, Any]]] | None = None
    reform: dict[str, int | float] | None = None
    add_missing_variables: bool = False
    expects_warnings: bool = False

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


def probe_amount(integration_probe_id: str) -> int:
    """Return a small run-specific amount that makes each household new."""
    return int(integration_probe_id.rsplit("-", 1)[-1], 16) % 997


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


def _one_catalog_item(
    client: httpx.Client, resource: str, country_id: str, **filters: str
) -> dict[str, Any]:
    response = client.get(
        f"/v2/{resource}", params={"country_id": country_id, "limit": 1, **filters}
    )
    assert response.status_code == 200, response.text[:500]
    (item,) = response.json()["result"]["items"]
    return item


def store_reform(client: httpx.Client, household: LiveHousehold) -> str | None:
    """Store the household's reform through ``/v2/policies``; return its ID."""
    if household.reform is None:
        return None
    country_id = household.country_id
    model = _one_catalog_item(client, "tax-benefit-models", country_id)
    parameter_values = [
        {
            "parameter_id": _one_catalog_item(
                client, "parameters", country_id, name=parameter_name
            )["id"],
            "value": value,
            "start_date": f"{REFORM_START}T00:00:00Z",
        }
        for parameter_name, value in household.reform.items()
    ]
    response = client.post(
        "/v2/policies",
        params={"country_id": country_id},
        json={
            "country_id": country_id,
            "tax_benefit_model_id": model["id"],
            "parameter_values": parameter_values,
        },
    )
    assert response.status_code in {200, 201}, response.text[:500]
    return response.json()["result"]["item"]["id"]


def _send_through_short_outages(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Send the request again while it gets 502, 503 or 504 for a short time."""
    outage_started: float | None = None
    while True:
        response = send()
        if response.status_code not in TRANSIENT_STATUS_CODES:
            return response
        outage_started = outage_started or time.monotonic()
        if time.monotonic() - outage_started >= TRANSIENT_LIMIT_SECONDS:
            msg = (
                f"HTTP {response.status_code} for {TRANSIENT_LIMIT_SECONDS:.0f} s: "
                f"{response.text[:500]}"
            )
            raise AssertionError(msg)
        time.sleep(POLL_INTERVAL_SECONDS)


def calculate(
    client: httpx.Client,
    household: LiveHousehold,
    household_id: str,
    policy_id: str | None = None,
) -> FinishedCalculation:
    """Submit the stored household's calculation and poll until it finishes."""
    started = time.monotonic()
    body: dict[str, Any] = {
        "country_id": household.country_id,
        "household_id": household_id,
        "policy_id": policy_id,
        "add_missing_variables": household.add_missing_variables,
    }
    if household.axes is not None:
        body["axes"] = household.axes
    deadline = started + CALCULATION_TIMEOUT_SECONDS
    response = _send_through_short_outages(
        lambda: client.post(CALCULATION_PATH, json=body)
    )
    submit_seconds = time.monotonic() - started
    assert response.status_code == 202, response.text
    item = response.json()["result"]
    while item["status"] not in FINISHED_STATUSES:
        if time.monotonic() >= deadline:
            msg = (
                f"Calculation {item['calculation_id']} did not finish within "
                f"{CALCULATION_TIMEOUT_SECONDS:.0f} s; last status {item['status']}"
            )
            raise AssertionError(msg)
        time.sleep(POLL_INTERVAL_SECONDS)
        polled = _send_through_short_outages(
            partial(client.get, f"{CALCULATION_PATH}/{item['calculation_id']}")
        )
        assert polled.status_code == 200, polled.text
        item = polled.json()["result"]
    return FinishedCalculation(
        item=item,
        submit_seconds=submit_seconds,
        total_seconds=time.monotonic() - started,
    )


def calculate_with_v1(client: httpx.Client, household: LiveHousehold) -> dict:
    """Return API v1's answer for the same household and reform.

    ``/calculate-full`` answers when the household adds missing variables,
    ``/calculate`` otherwise.
    """
    route = "calculate-full" if household.add_missing_variables else "calculate"
    request: dict[str, Any] = {"household": household.situation()}
    if household.reform is not None:
        request["policy"] = {
            parameter_name: {f"{REFORM_START}.{OPEN_END}": value}
            for parameter_name, value in household.reform.items()
        }
    response = client.post(f"/{household.country_id}/{route}", json=request)
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
