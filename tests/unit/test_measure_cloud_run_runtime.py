"""Characterization tests for the Cloud Run closed-loop load generator."""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from scripts import measure_cloud_run_runtime as load_generator

CALCULATE_PAYLOAD = Path(__file__).parents[1] / "data" / "calculate_us_1_data.json"


class _CountingClock:
    """Monotonic and performance counters that advance one second per reading."""

    def __init__(self) -> None:
        self.readings = 0

    def _read(self) -> float:
        self.readings += 1
        return float(self.readings)

    def monotonic(self) -> float:
        return self._read()

    def perf_counter(self) -> float:
        return self._read()


@pytest.mark.parametrize(
    ("status_code", "outcome"),
    [
        (200, "ok"),
        (204, "ok"),
        (399, "ok"),
        (400, "http_4xx"),
        (404, "http_4xx"),
        (428, "http_4xx"),
        (429, "http_429"),
        (430, "http_4xx"),
        (499, "http_4xx"),
        (500, "http_5xx"),
        (503, "http_5xx"),
    ],
)
def test_classify_groups_status_codes(status_code: int, outcome: str) -> None:
    assert load_generator._classify(status_code) == outcome


def test_readiness_wait_polls_until_the_service_answers_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _CountingClock()
    monkeypatch.setattr(load_generator, "time", clock)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(load_generator.asyncio, "sleep", fake_sleep)
    statuses = iter([503, 201, 200])
    requests: list[tuple[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, request.extensions["timeout"]))
        status = next(statuses)
        if status == 201:
            msg = "reset"
            raise httpx.ConnectError(msg, request=request)
        return httpx.Response(status)

    async def wait() -> float:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://api.test"
        ) as client:
            return await load_generator._wait_for_readiness(client, 60.0)

    assert asyncio.run(wait()) == 3.0
    assert [path for path, _timeout in requests] == ["/readiness-check"] * 3
    assert requests[0][1]["read"] == 20.0
    assert sleeps == [5.0, 5.0]


def test_readiness_wait_gives_up_after_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(load_generator, "time", _CountingClock())

    async def wait() -> float:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
            base_url="https://api.test",
        ) as client:
            return await load_generator._wait_for_readiness(client, 0.5)

    with pytest.raises(RuntimeError, match=r"^/readiness-check not ready after 0s$"):
        asyncio.run(wait())


def _load_args(**overrides: object) -> argparse.Namespace:
    values = {
        "base_url": "https://api.test/",
        "cell_label": "cell-a",
        "clients": 2,
        "duration_seconds": 20.0,
        "warmup_seconds": 6.0,
        "calculate_share": 0.5,
        "axes_count": 7,
        "cache_bust": "always",
        "seed": 42,
        "calculate_payload": str(CALCULATE_PAYLOAD),
        "timeout_calculate": 290.0,
        "timeout_metadata": 60.0,
        "readiness_timeout": 420.0,
    }
    return argparse.Namespace(**{**values, **overrides})


def _run_load_cell(
    monkeypatch: pytest.MonkeyPatch, args: argparse.Namespace
) -> tuple[dict[str, Any], list[tuple[Any, ...]]]:
    monkeypatch.setattr(load_generator, "time", _CountingClock())
    monkeypatch.setattr(
        load_generator,
        "uuid",
        SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="0123456789abcdef")),
    )
    timestamps = iter(["2026-01-01T00:00:00Z", "2026-01-01T00:10:00Z"])
    monkeypatch.setattr(load_generator, "_utc_now_iso", lambda: next(timestamps))
    requests: list[tuple[Any, ...]] = []
    responses_and_errors: list[httpx.Response | httpx.HTTPError] = [
        httpx.Response(200),
        httpx.Response(200),
        httpx.Response(429),
        httpx.Response(200),
        httpx.Response(503),
        httpx.Response(404),
        httpx.ReadTimeout("slow"),
        httpx.Response(200),
        httpx.ConnectError("refused"),
    ]
    outcomes = iter(responses_and_errors * 20)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append(
            (
                request.method,
                request.url.path,
                None if body is None else body.get("_loadtest"),
                None if body is None else body["household"]["axes"][0][0]["count"],
                request.extensions["timeout"]["read"],
            )
        )
        if request.url.path == "/readiness-check":
            return httpx.Response(200)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        load_generator.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    base_payload = json.loads(Path(args.calculate_payload).read_text())
    summary = asyncio.run(load_generator._run(args, base_payload))
    return summary, requests


def _endpoint_summary(**fields: object) -> dict[str, object]:
    return {
        "request_count": 0,
        "achieved_rps": 0.0,
        "p50_latency_ms": None,
        "p90_latency_ms": None,
        "p95_latency_ms": None,
        "p99_latency_ms": None,
        "max_latency_ms": None,
        "outcome_counts": {},
        "status_counts": {},
        **fields,
    }


ONE_SECOND_LATENCIES = {
    "p50_latency_ms": 1000.0,
    "p90_latency_ms": 1000.0,
    "p95_latency_ms": 1000.0,
    "p99_latency_ms": 1000.0,
    "max_latency_ms": 1000.0,
}


def test_load_cell_runs_seeded_clients_and_summarizes_each_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, requests = _run_load_cell(monkeypatch, _load_args())

    # The mock transport never yields, so the first client runs to the deadline
    # before the second one starts.
    assert requests == [
        ("GET", "/readiness-check", None, None, 20.0),
        ("POST", "/us/calculate", "01234567-cell-a-throwaway", 7, 290.0),
        ("POST", "/us/calculate", "01234567-cell-a-0-1", 7, 290.0),
        ("GET", "/us/metadata", None, None, 60.0),
        ("GET", "/us/metadata", None, None, 60.0),
        ("GET", "/us/metadata", None, None, 60.0),
        ("POST", "/us/calculate", "01234567-cell-a-0-5", 7, 290.0),
        ("GET", "/us/metadata", None, None, 60.0),
        ("GET", "/us/metadata", None, None, 60.0),
    ]
    assert summary == {
        "cell": "cell-a",
        "base_url": "https://api.test/",
        "clients": 2,
        "duration_seconds": 20.0,
        "warmup_seconds": 6.0,
        "calculate_share": 0.5,
        "axes_count": 7,
        "cache_bust": "always",
        "seed": 42,
        "readiness_wait_seconds": 1.0,
        "started_at_utc": "2026-01-01T00:00:00Z",
        "ended_at_utc": "2026-01-01T00:10:00Z",
        "warmup_request_count": 1,
        "measured_request_count": 6,
        "measured_elapsed_seconds": 25.0,
        "endpoints": {
            "metadata": _endpoint_summary(
                request_count=5,
                achieved_rps=0.2,
                **ONE_SECOND_LATENCIES,
                outcome_counts={"http_429": 1, "ok": 2, "http_5xx": 1, "timeout": 1},
                status_counts={"429": 1, "200": 2, "503": 1, "0": 1},
            ),
            "calculate": _endpoint_summary(
                request_count=1,
                achieved_rps=0.04,
                outcome_counts={"http_4xx": 1},
                status_counts={"404": 1},
            ),
        },
    }
    assert list(summary["endpoints"]["metadata"]["outcome_counts"]) == [
        "http_429",
        "ok",
        "http_5xx",
        "timeout",
    ]


def test_load_cell_without_cache_busting_repeats_the_same_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, requests = _run_load_cell(
        monkeypatch, _load_args(cache_bust="never", clients=1, calculate_share=1.0)
    )

    assert requests == [
        ("GET", "/readiness-check", None, None, 20.0),
        ("POST", "/us/calculate", "01234567-cell-a-throwaway", 7, 290.0),
        *[("POST", "/us/calculate", None, 7, 290.0)] * 7,
    ]
    assert summary["endpoints"] == {
        "metadata": _endpoint_summary(),
        "calculate": _endpoint_summary(
            request_count=6,
            achieved_rps=0.25,
            **ONE_SECOND_LATENCIES,
            outcome_counts={
                "http_429": 1,
                "ok": 2,
                "http_5xx": 1,
                "http_4xx": 1,
                "timeout": 1,
            },
            status_counts={"429": 1, "200": 2, "503": 1, "404": 1, "0": 1},
        ),
    }
