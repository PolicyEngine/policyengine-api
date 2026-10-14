from __future__ import annotations

import importlib.util
import io
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import grpc
import pytest

ROOT = Path(__file__).parents[2]
VERIFIER_PATH = ROOT / ".github" / "scripts" / "verify_observability_collector.py"
ACCESS_TOKEN = "access-token"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("collector_verifier", VERIFIER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Unimplemented(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNIMPLEMENTED


def _accepted_response():
    return SimpleNamespace(
        partial_success=SimpleNamespace(
            rejected_spans=0,
            rejected_data_points=0,
            error_message="",
        )
    )


def _attributes(items) -> dict[str, str]:
    return {item.key: item.value.string_value for item in items}


def test_verify_exports_real_telemetry_reads_it_back_and_rejects_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    exports: dict[str, object] = {}
    delivery: dict[str, object] = {}

    def stub(signal: str, *, reject: bool = False):
        class Stub:
            def __init__(self, _channel):
                pass

            def Export(self, request, *, metadata, timeout):  # noqa: N802  # mirrors the gRPC stub method name
                exports[signal] = (request, metadata, timeout)
                if reject:
                    raise _Unimplemented
                return _accepted_response()

        return Stub

    monkeypatch.setattr(
        verifier.grpc,
        "secure_channel",
        lambda *_args, **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(verifier, "TraceServiceStub", stub("traces"))
    monkeypatch.setattr(verifier, "MetricsServiceStub", stub("metrics"))
    monkeypatch.setattr(verifier, "LogsServiceStub", stub("logs", reject=True))
    monkeypatch.setattr(
        verifier,
        "_wait_for_delivery",
        lambda **kwargs: delivery.update(kwargs),
    )

    probe = verifier.verify(
        "https://collector.example",
        "identity-token",
        project_id="observability-project",
        metric_location="us-central1",
        access_token=ACCESS_TOKEN,
        timeout_seconds=3.0,
        delivery_timeout_seconds=9.0,
    )

    trace_request, metadata, timeout = exports["traces"]
    trace_resource = trace_request.resource_spans[0]
    span = trace_resource.scope_spans[0].spans[0]
    assert span.name == verifier.SPAN_NAME
    assert len(span.trace_id) == 16
    assert (
        _attributes(trace_resource.resource.attributes)["service.instance.id"]
        == probe.verification_id
    )
    assert metadata == (("authorization", "Bearer identity-token"),)
    assert timeout == 3.0

    metric_request, _, _ = exports["metrics"]
    metric_resource = metric_request.resource_metrics[0]
    metric = metric_resource.scope_metrics[0].metrics[0]
    assert metric.name == verifier.METRIC_NAME
    assert metric.gauge.data_points[0].as_int == 1
    assert (
        _attributes(metric_resource.resource.attributes)["service.instance.id"]
        == probe.verification_id
    )

    log_request, _, _ = exports["logs"]
    assert (
        log_request.resource_logs[0].scope_logs[0].log_records[0].body.string_value
        == "collector log rejection verification"
    )
    assert delivery == {
        "project_id": "observability-project",
        "trace_id": probe.trace_id,
        "verification_id": probe.verification_id,
        "metric_location": "us-central1",
        "access_token": ACCESS_TOKEN,
        "started_at": probe.started_at,
        "timeout_seconds": 9.0,
    }


def test_verify_fails_when_the_collector_accepts_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()

    class AcceptingStub:
        def __init__(self, _channel):
            pass

        def Export(self, *_args, **_kwargs):  # noqa: N802  # mirrors the gRPC stub method name
            return _accepted_response()

    monkeypatch.setattr(
        verifier.grpc,
        "secure_channel",
        lambda *_args, **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(verifier, "TraceServiceStub", AcceptingStub)
    monkeypatch.setattr(verifier, "MetricsServiceStub", AcceptingStub)
    monkeypatch.setattr(verifier, "LogsServiceStub", AcceptingStub)

    with pytest.raises(RuntimeError, match="unexpectedly accepted application logs"):
        verifier.verify(
            "https://collector.example",
            "identity-token",
            project_id="observability-project",
            metric_location="us-central1",
            access_token=ACCESS_TOKEN,
        )


def test_metric_lookup_follows_all_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    urls: list[str] = []

    def get_json(url: str, _access_token: str):
        urls.append(url)
        query = parse_qs(urlparse(url).query)
        if "pageToken" not in query:
            return {"nextPageToken": "second-page"}
        return {"timeSeries": [{"points": [{"value": {"int64Value": "1"}}]}]}

    monkeypatch.setattr(verifier, "_get_json", get_json)

    assert verifier._metric_available(
        "observability-project",
        "collector-verify-123",
        "us-central1",
        ACCESS_TOKEN,
        1_700_000_000.0,
    )
    assert len(urls) == 2
    assert parse_qs(urlparse(urls[1]).query)["pageToken"] == ["second-page"]
    monitoring_filter = parse_qs(urlparse(urls[0]).query)["filter"][0]
    assert (
        'metric.type = "prometheus.googleapis.com/'
        'policyengine.collector.verification/gauge"' in monitoring_filter
    )
    assert 'resource.type = "prometheus_target"' in monitoring_filter
    assert 'resource.labels.location = "us-central1"' in monitoring_filter
    assert 'resource.labels.instance = "collector-verify-123"' in monitoring_filter


def test_partial_metric_rejection_fails_verification() -> None:
    verifier = _load_verifier()
    response = SimpleNamespace(
        partial_success=SimpleNamespace(
            rejected_data_points=1,
            error_message="invalid location",
        )
    )

    with pytest.raises(RuntimeError, match="invalid location"):
        verifier._raise_for_partial_rejection(
            response,
            signal="metric points",
            rejected_field="rejected_data_points",
        )


@pytest.mark.parametrize(
    "endpoint",
    ["http://collector.example", "collector.example", "https:///missing-host"],
)
def test_authority_rejects_non_https_or_hostless_endpoints(endpoint: str) -> None:
    verifier = _load_verifier()

    with pytest.raises(ValueError, match="HTTPS URL"):
        verifier._authority(endpoint)


class _JsonResponse:
    def __init__(self, body: bytes):
        self._body = io.BytesIO(body)

    def __enter__(self):
        return self._body

    def __exit__(self, *_exc_info):
        return False


def test_get_json_sends_the_access_token_and_decodes_the_body(monkeypatch) -> None:
    verifier = _load_verifier()
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, request.headers, timeout))
        return _JsonResponse(b'{"traceId": "abc"}')

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)

    assert verifier._get_json("https://cloud.example/x", ACCESS_TOKEN) == {
        "traceId": "abc"
    }
    assert requests == [
        ("https://cloud.example/x", {"Authorization": f"Bearer {ACCESS_TOKEN}"}, 15)
    ]


def test_get_json_treats_not_found_as_missing(monkeypatch) -> None:
    verifier = _load_verifier()

    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 404, "Not Found", None, io.BytesIO(b""))

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)

    assert verifier._get_json("https://cloud.example/x", ACCESS_TOKEN) is None


def test_get_json_reports_other_http_errors_with_their_body(monkeypatch) -> None:
    verifier = _load_verifier()

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url, 403, "Forbidden", None, io.BytesIO(b"permission denied")
        )

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as error:
        verifier._get_json("https://cloud.example/x", ACCESS_TOKEN)

    assert str(error.value) == (
        "Google Cloud verification request failed (403): permission denied"
    )
    assert isinstance(error.value.__cause__, HTTPError)


class _FakeClock:
    """Monotonic time that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _stub_delivery_checks(monkeypatch, verifier, *, trace_results, metric_results):
    calls: dict[str, list[tuple]] = {"trace": [], "metric": []}
    trace_answers = iter(trace_results)
    metric_answers = iter(metric_results)

    def trace_available(*args):
        calls["trace"].append(args)
        return next(trace_answers)

    def metric_available(*args):
        calls["metric"].append(args)
        return next(metric_answers)

    monkeypatch.setattr(verifier, "_trace_available", trace_available)
    monkeypatch.setattr(verifier, "_metric_available", metric_available)
    clock = _FakeClock()
    monkeypatch.setattr(verifier, "time", clock)
    return calls, clock


def _wait_for_test_delivery(verifier, *, timeout_seconds: float) -> None:
    verifier._wait_for_delivery(
        project_id="observability-project",
        trace_id="trace-123",
        verification_id="collector-verify-123",
        metric_location="us-central1",
        access_token=ACCESS_TOKEN,
        started_at=1_700_000_000.0,
        timeout_seconds=timeout_seconds,
    )


TRACE_CHECK = ("observability-project", "trace-123", ACCESS_TOKEN)
METRIC_CHECK = (
    "observability-project",
    "collector-verify-123",
    "us-central1",
    ACCESS_TOKEN,
    1_700_000_000.0,
)


def test_delivery_wait_returns_once_both_signals_are_stored(monkeypatch) -> None:
    verifier = _load_verifier()
    calls, clock = _stub_delivery_checks(
        monkeypatch,
        verifier,
        trace_results=[True],
        metric_results=[False, False, True],
    )

    _wait_for_test_delivery(verifier, timeout_seconds=12.0)

    assert calls == {"trace": [TRACE_CHECK], "metric": [METRIC_CHECK] * 3}
    assert clock.sleeps == [5.0, 5.0]


def test_delivery_wait_names_the_signals_still_missing_at_the_deadline(
    monkeypatch,
) -> None:
    verifier = _load_verifier()
    calls, clock = _stub_delivery_checks(
        monkeypatch,
        verifier,
        trace_results=[False, False, False, True],
        metric_results=[False] * 4,
    )

    with pytest.raises(
        RuntimeError,
        match=r"^collector verification data was not stored: metric$",
    ):
        _wait_for_test_delivery(verifier, timeout_seconds=12.0)

    assert calls == {"trace": [TRACE_CHECK] * 4, "metric": [METRIC_CHECK] * 4}
    assert clock.sleeps == [5.0, 5.0, 2.0]


def test_delivery_wait_lists_both_missing_signals(monkeypatch) -> None:
    verifier = _load_verifier()
    _stub_delivery_checks(
        monkeypatch, verifier, trace_results=[False], metric_results=[False]
    )

    with pytest.raises(
        RuntimeError,
        match=r"^collector verification data was not stored: trace, metric$",
    ):
        _wait_for_test_delivery(verifier, timeout_seconds=0.0)
