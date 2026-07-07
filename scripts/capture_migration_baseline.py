"""Capture opt-in baseline metrics for migration cutover planning.

This script is intentionally not part of normal CI. It requires API_BASE_URL and
only performs lightweight smoke requests unless callers provide a deployed API
that can run the existing integration probes.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx


@dataclass(frozen=True)
class ProbeResult:
    name: str
    method: str
    path: str
    status_code: int
    latency_ms: float
    ok: bool
    error: str | None = None
    completion_ms: float | None = None
    completed: bool | None = None


DEFAULT_PROBES = (
    ("liveness", "GET", "/liveness-check", (200,)),
    ("readiness", "GET", "/readiness-check", (200,)),
    ("us_metadata", "GET", "/us/metadata", (200,)),
)

SIMULATION_SUCCESS_STATUSES = frozenset({"complete", "completed", "success", "ok"})
SIMULATION_FAILURE_STATUSES = frozenset({"failed", "failure", "error", "errored"})


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    # Round half up rather than Python's round-half-to-even: banker's rounding
    # biases small even-sized samples low (p50 of two values picks the min).
    index = int((len(values) - 1) * percentile + 0.5)
    return round(sorted(values)[index], 2)


def _request_probe(
    client: httpx.Client,
    *,
    name: str,
    method: str,
    path: str,
    expected_statuses: tuple[int, ...],
    json_payload: dict | None = None,
) -> tuple[ProbeResult, httpx.Response | None]:
    started_at = time.perf_counter()
    try:
        response = client.request(method, path, json=json_payload)
        latency_ms = (time.perf_counter() - started_at) * 1000
        return (
            ProbeResult(
                name=name,
                method=method,
                path=path,
                status_code=response.status_code,
                latency_ms=round(latency_ms, 2),
                ok=response.status_code in expected_statuses,
            ),
            response,
        )
    except httpx.HTTPError as error:
        latency_ms = (time.perf_counter() - started_at) * 1000
        return (
            ProbeResult(
                name=name,
                method=method,
                path=path,
                status_code=0,
                latency_ms=round(latency_ms, 2),
                ok=False,
                error=str(error),
            ),
            None,
        )


def run_probes(base_url: str, repetitions: int) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=90.0) as client:
        for _ in range(repetitions):
            for name, method, path, expected_statuses in DEFAULT_PROBES:
                result, _ = _request_probe(
                    client,
                    name=name,
                    method=method,
                    path=path,
                    expected_statuses=expected_statuses,
                )
                results.append(result)
    return results


def run_simulation_gateway_probe(
    gateway_url: str,
    payload: dict,
    *,
    poll_timeout_seconds: float,
    poll_interval_seconds: float,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    started_at = time.perf_counter()

    with httpx.Client(base_url=gateway_url.rstrip("/"), timeout=90.0) as client:
        submit_result, submit_response = _request_probe(
            client,
            name="simulation_gateway_submit",
            method="POST",
            path="/simulate/economy/comparison",
            expected_statuses=(202,),
            json_payload=payload,
        )
        results.append(submit_result)
        if submit_response is None or not submit_result.ok:
            return results

        try:
            job_id = submit_response.json()["job_id"]
        except (KeyError, ValueError, TypeError) as error:
            results.append(
                ProbeResult(
                    name="simulation_gateway_completion",
                    method="GET",
                    path="/jobs/<unknown>",
                    status_code=0,
                    latency_ms=0,
                    ok=False,
                    error=f"Could not parse simulation job_id: {error}",
                    completed=False,
                )
            )
            return results

        deadline = started_at + poll_timeout_seconds
        last_result: ProbeResult | None = None
        last_payload: dict | None = None
        while time.perf_counter() < deadline:
            poll_result, poll_response = _request_probe(
                client,
                name="simulation_gateway_poll",
                method="GET",
                path=f"/jobs/{job_id}",
                expected_statuses=(200, 202),
            )
            last_result = poll_result
            results.append(poll_result)

            if poll_response is None:
                return results

            try:
                last_payload = poll_response.json()
            except ValueError:
                last_payload = {}

            status = str(last_payload.get("status", "")).lower()
            if status in SIMULATION_SUCCESS_STATUSES | SIMULATION_FAILURE_STATUSES:
                completion_ms = (time.perf_counter() - started_at) * 1000
                results.append(
                    ProbeResult(
                        name="simulation_gateway_completion",
                        method="GET",
                        path=f"/jobs/{job_id}",
                        status_code=poll_response.status_code,
                        latency_ms=poll_result.latency_ms,
                        ok=status in SIMULATION_SUCCESS_STATUSES,
                        completion_ms=round(completion_ms, 2),
                        completed=status in SIMULATION_SUCCESS_STATUSES,
                        error=last_payload.get("error"),
                    )
                )
                return results

            time.sleep(poll_interval_seconds)

    completion_ms = (time.perf_counter() - started_at) * 1000
    results.append(
        ProbeResult(
            name="simulation_gateway_completion",
            method="GET",
            path=last_result.path if last_result else "/jobs/<unknown>",
            status_code=last_result.status_code if last_result else 0,
            latency_ms=last_result.latency_ms if last_result else 0,
            ok=False,
            completion_ms=round(completion_ms, 2),
            completed=False,
            error=f"Simulation did not complete within {poll_timeout_seconds}s",
        )
    )
    return results


def summarize(results: Iterable[ProbeResult]) -> dict:
    rows = list(results)
    request_rows = [row for row in rows if row.completed is None]
    latencies = [row.latency_ms for row in request_rows if row.ok]
    failures = [row for row in request_rows if not row.ok]
    completions = [
        row.completion_ms
        for row in rows
        if row.completed is True and row.completion_ms is not None
    ]
    completion_failures = [row for row in rows if row.completed is False]
    status_counts: dict[str, int] = {}
    for row in request_rows:
        key = str(row.status_code)
        status_counts[key] = status_counts.get(key, 0) + 1

    return {
        "request_count": len(request_rows),
        "failure_count": len(failures),
        "error_rate": round(len(failures) / len(request_rows), 4)
        if request_rows
        else None,
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "completion_count": len(completions),
        "completion_failure_count": len(completion_failures),
        "p50_completion_ms": round(statistics.median(completions), 2)
        if completions
        else None,
        "p95_completion_ms": _percentile(completions, 0.95),
        "status_counts": status_counts,
        "probes": [row.__dict__ for row in rows],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("API_BASE_URL"))
    parser.add_argument(
        "--simulation-gateway-url",
        default=os.environ.get("SIMULATION_API_URL"),
    )
    parser.add_argument(
        "--simulation-payload-file",
        default=os.environ.get("SIMULATION_PAYLOAD_FILE"),
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--poll-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)

    results: list[ProbeResult] = []
    if not args.base_url:
        print("API_BASE_URL is not set; skipping API route baseline capture.")
    else:
        results.extend(run_probes(args.base_url, args.repetitions))

    if args.simulation_gateway_url and args.simulation_payload_file:
        payload = json.loads(Path(args.simulation_payload_file).read_text())
        results.extend(
            run_simulation_gateway_probe(
                args.simulation_gateway_url,
                payload,
                poll_timeout_seconds=args.poll_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        )
    elif args.simulation_gateway_url or args.simulation_payload_file:
        print(
            "SIMULATION_API_URL and SIMULATION_PAYLOAD_FILE are both required; "
            "skipping simulation gateway baseline capture."
        )

    if not results:
        print("No baseline probes ran.")
        return 0

    print(json.dumps(summarize(results), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
