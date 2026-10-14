import json

import httpx

from scripts import capture_migration_baseline


def test_baseline_summary_computes_error_rate_and_latency():
    results = [
        capture_migration_baseline.ProbeResult(
            name="health",
            method="GET",
            path="/readiness-check",
            status_code=200,
            latency_ms=10.0,
            ok=True,
        ),
        capture_migration_baseline.ProbeResult(
            name="metadata",
            method="GET",
            path="/us/metadata",
            status_code=500,
            latency_ms=30.0,
            ok=False,
            error="boom",
        ),
        capture_migration_baseline.ProbeResult(
            name="simulation_gateway_completion",
            method="GET",
            path="/jobs/job-1",
            status_code=200,
            latency_ms=5.0,
            ok=True,
            completion_ms=100.0,
            completed=True,
        ),
    ]

    summary = capture_migration_baseline.summarize(results)

    assert summary["request_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["error_rate"] == 0.5
    assert summary["p50_latency_ms"] == 10.0
    assert summary["p95_latency_ms"] == 10.0
    assert summary["completion_count"] == 1
    assert summary["completion_failure_count"] == 0
    assert summary["p50_completion_ms"] == 100.0
    assert summary["p95_completion_ms"] == 100.0
    assert summary["status_counts"] == {"200": 1, "500": 1}


def test_baseline_script_skips_without_base_url(capsys, monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    exit_code = capture_migration_baseline.main([])

    assert exit_code == 0
    assert "No baseline probes ran" in capsys.readouterr().out


def test_run_probes_uses_lightweight_baseline_routes(monkeypatch):
    requests = []
    real_client = httpx.Client

    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(
        capture_migration_baseline.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler),
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout"],
        ),
    )

    results = capture_migration_baseline.run_probes("https://api.test", 1)

    assert [(result.method, result.path) for result in results] == requests
    assert requests == [
        ("GET", "/liveness-check"),
        ("GET", "/readiness-check"),
        ("GET", "/specification"),
        ("GET", "/us/metadata"),
        ("GET", "/uk/metadata"),
    ]
    assert all(
        isinstance(probe, capture_migration_baseline.RouteProbe)
        for probe in capture_migration_baseline.DEFAULT_PROBES
    )
    assert json.loads(json.dumps(capture_migration_baseline.summarize(results)))


def test_run_probes_treats_unexpected_4xx_as_failure(monkeypatch):
    real_client = httpx.Client

    monkeypatch.setattr(
        capture_migration_baseline.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(404, json={"status": "missing"})
            ),
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout"],
        ),
    )

    summary = capture_migration_baseline.summarize(
        capture_migration_baseline.run_probes("https://api.test", 1)
    )

    assert summary["request_count"] == 5
    assert summary["failure_count"] == 5
    assert summary["status_counts"] == {"404": 5}


def test_run_simulation_gateway_probe_records_completion(monkeypatch):
    requests = []
    real_client = httpx.Client

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1", "status": "submitted"})
        return httpx.Response(
            200,
            json={"job_id": "job-1", "status": "complete", "result": {"ok": True}},
        )

    monkeypatch.setattr(
        capture_migration_baseline.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler),
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout"],
        ),
    )

    results = capture_migration_baseline.run_simulation_gateway_probe(
        "https://simulation.test",
        {"country": "us"},
        poll_timeout_seconds=1,
        poll_interval_seconds=0,
    )
    summary = capture_migration_baseline.summarize(results)

    assert requests == [
        ("POST", "/simulate/economy/comparison"),
        ("GET", "/jobs/job-1"),
    ]
    assert [result.name for result in results] == [
        "simulation_gateway_submit",
        "simulation_gateway_poll",
        "simulation_gateway_completion",
    ]
    assert summary["completion_count"] == 1
    assert summary["completion_failure_count"] == 0


def _client_with_transport(monkeypatch, transport):
    real_client = httpx.Client
    monkeypatch.setattr(
        capture_migration_baseline.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout"],
        ),
    )


def _without_latency(result):
    return {**result.__dict__, "latency_ms": None}


def test_run_probes_records_transport_errors_as_failed_probes(monkeypatch):
    def refuse(request):
        msg = "connection refused"
        raise httpx.ConnectError(msg, request=request)

    _client_with_transport(monkeypatch, httpx.MockTransport(refuse))

    results = capture_migration_baseline.run_probes("https://api.test", 1)

    assert [_without_latency(result) for result in results] == [
        {
            "name": probe.name,
            "method": "GET",
            "path": probe.path,
            "status_code": 0,
            "latency_ms": None,
            "ok": False,
            "error": "connection refused",
            "completion_ms": None,
            "completed": None,
        }
        for probe in capture_migration_baseline.DEFAULT_PROBES
    ]
    assert all(result.latency_ms >= 0 for result in results)


def test_gateway_probe_sends_the_payload_and_records_each_request(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(request.content)
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "job-1"})
        return httpx.Response(200, json={"status": "failed", "error": "boom"})

    _client_with_transport(monkeypatch, httpx.MockTransport(handler))

    results = capture_migration_baseline.run_simulation_gateway_probe(
        "https://simulation.test",
        {"country": "us"},
        poll_timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert bodies == [b'{"country":"us"}', b""]
    assert [
        {**_without_latency(result), "completion_ms": None} for result in results
    ] == [
        {
            "name": "simulation_gateway_submit",
            "method": "POST",
            "path": "/simulate/economy/comparison",
            "status_code": 202,
            "latency_ms": None,
            "ok": True,
            "error": None,
            "completion_ms": None,
            "completed": None,
        },
        {
            "name": "simulation_gateway_poll",
            "method": "GET",
            "path": "/jobs/job-1",
            "status_code": 200,
            "latency_ms": None,
            "ok": True,
            "error": None,
            "completion_ms": None,
            "completed": None,
        },
        {
            "name": "simulation_gateway_completion",
            "method": "GET",
            "path": "/jobs/job-1",
            "status_code": 200,
            "latency_ms": None,
            "ok": False,
            "error": "boom",
            "completion_ms": None,
            "completed": False,
        },
    ]
    assert results[2].latency_ms == results[1].latency_ms


def test_gateway_probe_stops_when_the_submission_is_rejected(monkeypatch):
    _client_with_transport(
        monkeypatch,
        httpx.MockTransport(lambda _request: httpx.Response(400, json={})),
    )

    results = capture_migration_baseline.run_simulation_gateway_probe(
        "https://simulation.test",
        {"country": "us"},
        poll_timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert [_without_latency(result) for result in results] == [
        {
            "name": "simulation_gateway_submit",
            "method": "POST",
            "path": "/simulate/economy/comparison",
            "status_code": 400,
            "latency_ms": None,
            "ok": False,
            "error": None,
            "completion_ms": None,
            "completed": None,
        }
    ]
