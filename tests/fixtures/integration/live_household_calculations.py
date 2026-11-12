"""Households and helpers for the live staging household calculation checks.

The checks call the simulation service's household calculation route through
the staging candidate, so they pass only once that route (``POST
/household-calculations``, answering ``job_id`` and accepting ``axes``) is
deployed to staging. Every staging promotion waits on them, so the change that
adds them merges only after that deployment.

Every request sends the CI server credential: through the ``api_client``
fixture, or through ``deployed_api_client`` from
``tests/integration/deployed_api_credentials.py``, which builds that fixture's
client, for a check that needs a client of its own.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

CALCULATION_PATH = "/v2/household-calculations"
CALCULATION_TIMEOUT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_CALCULATION_TIMEOUT_SECONDS", "600")
)
POLL_INTERVAL_SECONDS = float(
    os.environ.get("STAGING_API_TEST_POLL_INTERVAL_SECONDS", "5")
)
# A short outage, such as the simulation service failing to read its database
# or version manifest for a moment, or the Public API failing to read
# household_jobs, is sent through again while it lasts at most
# TRANSIENT_LIMIT_SECONDS in a row. A submission is sent again only after a
# 503 or a connection that was never made (httpx.ConnectError): the Public API
# answers 502 when the simulation service may have created the job, and after
# a read timeout or a dropped response the job may exist too, so sending it
# again could create another. A read is sent again after a 502, 503 or 504 or
# any transport error, since reading creates nothing. Any other failure, and a
# longer outage, fails the check with the answer's body or the error.
SUBMISSION_RETRY_STATUS_CODES = frozenset({503})
SUBMISSION_RETRY_ERRORS: tuple[type[httpx.TransportError], ...] = (httpx.ConnectError,)
READ_RETRY_STATUS_CODES = frozenset({502, 503, 504})
READ_RETRY_ERRORS: tuple[type[httpx.TransportError], ...] = (httpx.TransportError,)
TRANSIENT_LIMIT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_TRANSIENT_LIMIT_SECONDS", "90")
)
# How long the check waits for the Public API's own /calculate or
# /calculate-full answer: longer than the candidate's Cloud Run request timeout
# (CLOUD_RUN_TIMEOUT in .github/scripts/cloud_run_env.sh, 300 s), so the check
# gets the candidate's own answer, a 504 included. /calculate-full calculates
# every variable the household leaves out and can take most of that: 224 s on
# staging, and up to 300 s in production.
V1_CALCULATION_TIMEOUT_SECONDS = 320.0
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
    ``expects_warnings`` says the household has a deprecated input, which the
    calculation drops with a warning before the country model runs.
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


def _send_through_short_outages(
    send: Callable[[], httpx.Response],
    retry_status_codes: frozenset[int],
    retry_errors: tuple[type[httpx.TransportError], ...],
) -> httpx.Response:
    """Send the request again while it raises one of the errors or gets a code.

    Any other error is raised. Raise AssertionError once the outage has
    lasted TRANSIENT_LIMIT_SECONDS.
    """
    outage_started: float | None = None
    while True:
        try:
            response = send()
        except retry_errors as error:
            failure = f"{type(error).__name__}: {error}"
        else:
            if response.status_code not in retry_status_codes:
                return response
            failure = f"HTTP {response.status_code}: {response.text[:500]}"
        if outage_started is None:
            outage_started = time.monotonic()
        if time.monotonic() - outage_started >= TRANSIENT_LIMIT_SECONDS:
            msg = f"{failure}, for {TRANSIENT_LIMIT_SECONDS:.0f} s"
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
        lambda: client.post(CALCULATION_PATH, json=body),
        SUBMISSION_RETRY_STATUS_CODES,
        SUBMISSION_RETRY_ERRORS,
    )
    submit_seconds = time.monotonic() - started
    assert response.status_code == 202, response.text
    accepted = response.json()["result"]["item"]
    assert accepted["household_id"] == household_id, accepted
    calculation_path = f"{CALCULATION_PATH}/{accepted['calculation_id']}"
    # The submission answers with the new job only; its result is read from
    # household_jobs, so the calculation is read at least once.
    while True:
        polled = _send_through_short_outages(
            partial(client.get, calculation_path),
            READ_RETRY_STATUS_CODES,
            READ_RETRY_ERRORS,
        )
        assert polled.status_code == 200, polled.text
        item = polled.json()["result"]["item"]
        if item["status"] in FINISHED_STATUSES:
            break
        if time.monotonic() >= deadline:
            msg = (
                f"Calculation {item['calculation_id']} did not finish within "
                f"{CALCULATION_TIMEOUT_SECONDS:.0f} s; last status {item['status']}"
            )
            raise AssertionError(msg)
        time.sleep(POLL_INTERVAL_SECONDS)
    return FinishedCalculation(
        item=item,
        submit_seconds=submit_seconds,
        total_seconds=time.monotonic() - started,
    )


def calculate_with_v1(client: httpx.Client, household: LiveHousehold) -> dict:
    """Return the Public API's own answer for the same household and reform.

    ``/calculate-full`` answers when the household adds missing variables,
    ``/calculate`` otherwise. The answer is awaited for
    ``V1_CALCULATION_TIMEOUT_SECONDS``.
    """
    route = "calculate-full" if household.add_missing_variables else "calculate"
    request: dict[str, Any] = {"household": household.situation()}
    if household.reform is not None:
        request["policy"] = {
            parameter_name: {f"{REFORM_START}.{OPEN_END}": value}
            for parameter_name, value in household.reform.items()
        }
    response = client.post(
        f"/{household.country_id}/{route}",
        json=request,
        timeout=V1_CALCULATION_TIMEOUT_SECONDS,
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
    # The Public API's /calculate writes an undefined number as a bare NaN;
    # the v2 household function writes "NaN".
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
