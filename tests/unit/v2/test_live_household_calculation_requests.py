"""Which answers the live household calculation checks send again.

A submission is sent again only after a 503 or a failed connection: a 502
means the simulation service accepted it, so the job exists. A read is sent
again after a 502, 503 or 504 or a failed connection, since reading creates
nothing.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from tests.fixtures.integration import live_household_calculations
from tests.fixtures.integration.live_household_calculations import (
    LiveHousehold,
    calculate,
)

HOUSEHOLD_ID = str(uuid4())
CALCULATION_ID = str(uuid4())
HOUSEHOLD = LiveHousehold(name="retries", country_id="us", people={"adult": {}})


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(
        live_household_calculations.time, "sleep", lambda _seconds: None
    )


class ScriptedPublicApi:
    """The Public API's household calculation routes, answering from a script.

    Each script entry is an HTTP status, or an exception class to raise.
    """

    def __init__(self, submissions: list, reads: list) -> None:
        self.submissions = list(submissions)
        self.reads = list(reads)
        self.sent: list[str] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request.method)
        script = self.submissions if request.method == "POST" else self.reads
        outcome = script.pop(0)
        if isinstance(outcome, type):
            msg = "connection refused"
            raise outcome(msg, request=request)
        if outcome == 202:
            item = {
                "calculation_id": CALCULATION_ID,
                "status": "pending",
                "household_id": HOUSEHOLD_ID,
            }
            return httpx.Response(202, json={"result": {"item": item}})
        if outcome == 200:
            item = {"calculation_id": CALCULATION_ID, "status": "succeeded"}
            return httpx.Response(200, json={"result": {"item": item}})
        return httpx.Response(outcome, content=json.dumps({"status": "error"}))

    def calculate(self):
        with httpx.Client(
            base_url="https://public-api.example",
            transport=httpx.MockTransport(self.answer),
        ) as client:
            return calculate(client, HOUSEHOLD, HOUSEHOLD_ID)


def test_a_submission_is_sent_again_after_a_503() -> None:
    public_api = ScriptedPublicApi(submissions=[503, 202], reads=[200])

    finished = public_api.calculate()

    assert finished.item["status"] == "succeeded"
    assert public_api.sent == ["POST", "POST", "GET"]


def test_a_submission_is_sent_again_after_a_failed_connection() -> None:
    public_api = ScriptedPublicApi(submissions=[httpx.ConnectError, 202], reads=[200])

    finished = public_api.calculate()

    assert finished.item["status"] == "succeeded"
    assert public_api.sent == ["POST", "POST", "GET"]


@pytest.mark.parametrize("status_code", [502, 504, 500])
def test_a_submission_is_never_sent_again_after_another_failure(status_code) -> None:
    public_api = ScriptedPublicApi(submissions=[status_code, 202], reads=[200])

    with pytest.raises(AssertionError):
        public_api.calculate()

    assert public_api.sent == ["POST"]


@pytest.mark.parametrize("outcome", [502, 503, 504, httpx.ReadError])
def test_a_read_is_sent_again_after_a_short_outage(outcome) -> None:
    public_api = ScriptedPublicApi(submissions=[202], reads=[outcome, 200])

    finished = public_api.calculate()

    assert finished.item["status"] == "succeeded"
    assert public_api.sent == ["POST", "GET", "GET"]


def test_a_lasting_outage_fails_the_check(monkeypatch) -> None:
    monkeypatch.setattr(live_household_calculations, "TRANSIENT_LIMIT_SECONDS", 0)
    public_api = ScriptedPublicApi(submissions=[503, 202], reads=[200])

    with pytest.raises(AssertionError, match="HTTP 503"):
        public_api.calculate()

    assert public_api.sent == ["POST"]
