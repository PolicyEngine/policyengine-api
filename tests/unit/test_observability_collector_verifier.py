from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import grpc
import pytest

ROOT = Path(__file__).parents[2]
VERIFIER_PATH = ROOT / ".github" / "scripts" / "verify_observability_collector.py"


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

            def Export(self, request, *, metadata, timeout):
                exports[signal] = (request, metadata, timeout)
                if reject:
                    raise _Unimplemented()
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
        access_token="access-token",
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
        "access_token": "access-token",
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

        def Export(self, *_args, **_kwargs):
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
            access_token="access-token",
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
        "access-token",
        1_700_000_000.0,
    )
    assert len(urls) == 2
    assert parse_qs(urlparse(urls[1]).query)["pageToken"] == ["second-page"]
    monitoring_filter = parse_qs(urlparse(urls[0]).query)["filter"][0]
    assert 'resource.labels.location = "us-central1"' in monitoring_filter
    assert 'resource.labels.task_id = "collector-verify-123"' in monitoring_filter


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
