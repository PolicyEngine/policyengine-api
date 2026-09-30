"""Verify authenticated collector ingestion in Google Cloud."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import NamedTuple
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import grpc
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (
    LogsServiceStub,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2_grpc import (
    MetricsServiceStub,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import (
    TraceServiceStub,
)
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    InstrumentationScope,
    KeyValue,
)
from opentelemetry.proto.logs.v1.logs_pb2 import (
    LogRecord,
    ResourceLogs,
    ScopeLogs,
)
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    Gauge,
    Metric,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span,
)

METRIC_NAME = "policyengine.collector.verification"
METRIC_TYPE = f"prometheus.googleapis.com/{METRIC_NAME}/gauge"
SPAN_NAME = "policyengine.collector.verification"
SERVICE_NAME = "policyengine-observability-verifier"
SERVICE_NAMESPACE = "policyengine.api-v1"


class VerificationProbe(NamedTuple):
    verification_id: str
    trace_id: str
    started_at: float


def _authority(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("collector endpoint must be an HTTPS URL")
    return f"{parsed.hostname}:{parsed.port or 443}"


def _attribute(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _resource(verification_id: str) -> Resource:
    return Resource(
        attributes=[
            _attribute("service.name", SERVICE_NAME),
            _attribute("service.namespace", SERVICE_NAMESPACE),
            _attribute("service.instance.id", verification_id),
            _attribute("deployment.environment.name", "production"),
        ]
    )


def _probe_requests(
    verification_id: str,
    timestamp_ns: int,
) -> tuple[
    ExportTraceServiceRequest,
    ExportMetricsServiceRequest,
    ExportLogsServiceRequest,
    str,
]:
    resource = _resource(verification_id)
    scope = InstrumentationScope(name="policyengine.collector.verifier")
    trace_id_bytes = uuid.uuid4().bytes
    span = Span(
        trace_id=trace_id_bytes,
        span_id=uuid.uuid4().bytes[:8],
        name=SPAN_NAME,
        kind=Span.SPAN_KIND_INTERNAL,
        start_time_unix_nano=timestamp_ns - 1_000_000,
        end_time_unix_nano=timestamp_ns,
        attributes=[_attribute("verification.id", verification_id)],
    )
    trace_request = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=resource,
                scope_spans=[ScopeSpans(scope=scope, spans=[span])],
            )
        ]
    )
    metric_request = ExportMetricsServiceRequest(
        resource_metrics=[
            ResourceMetrics(
                resource=resource,
                scope_metrics=[
                    ScopeMetrics(
                        scope=scope,
                        metrics=[
                            Metric(
                                name=METRIC_NAME,
                                description=("Collector deployment verification value"),
                                unit="1",
                                gauge=Gauge(
                                    data_points=[
                                        NumberDataPoint(
                                            time_unix_nano=timestamp_ns,
                                            as_int=1,
                                            attributes=[
                                                _attribute(
                                                    "verification.id",
                                                    verification_id,
                                                )
                                            ],
                                        )
                                    ]
                                ),
                            )
                        ],
                    )
                ],
            )
        ]
    )
    log_request = ExportLogsServiceRequest(
        resource_logs=[
            ResourceLogs(
                resource=resource,
                scope_logs=[
                    ScopeLogs(
                        scope=scope,
                        log_records=[
                            LogRecord(
                                time_unix_nano=timestamp_ns,
                                body=AnyValue(
                                    string_value=(
                                        "collector log rejection verification"
                                    )
                                ),
                                attributes=[
                                    _attribute("verification.id", verification_id)
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    return trace_request, metric_request, log_request, trace_id_bytes.hex()


def _raise_for_partial_rejection(
    response: object,
    *,
    signal: str,
    rejected_field: str,
) -> None:
    partial = getattr(response, "partial_success", None)
    rejected = getattr(partial, rejected_field, 0)
    if rejected:
        message = getattr(partial, "error_message", "")
        raise RuntimeError(f"collector rejected {rejected} {signal}: {message}")


def _get_json(url: str, access_token: str) -> dict[str, object] | None:
    request = Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Google Cloud verification request failed ({error.code}): {detail}"
        ) from error


def _trace_available(
    project_id: str,
    trace_id: str,
    access_token: str,
) -> bool:
    project = quote(project_id, safe="")
    trace = quote(trace_id, safe="")
    url = f"https://cloudtrace.googleapis.com/v1/projects/{project}/traces/{trace}"
    payload = _get_json(url, access_token)
    return payload is not None and payload.get("traceId") == trace_id


def _metric_available(
    project_id: str,
    verification_id: str,
    metric_location: str,
    access_token: str,
    started_at: float,
) -> bool:
    project = quote(project_id, safe="")
    monitoring_filter = " AND ".join(
        (
            f'metric.type = "{METRIC_TYPE}"',
            'resource.type = "prometheus_target"',
            f'resource.labels.location = "{metric_location}"',
            f'resource.labels.instance = "{verification_id}"',
        )
    )
    start = datetime.fromtimestamp(started_at - 60, UTC).isoformat()
    end = datetime.now(UTC).isoformat()
    parameters = {
        "filter": monitoring_filter,
        "interval.startTime": start,
        "interval.endTime": end,
        "view": "FULL",
        "pageSize": "1000",
    }
    base_url = f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries"
    page_token: str | None = None
    while True:
        if page_token:
            parameters["pageToken"] = page_token
        url = f"{base_url}?{urlencode(parameters)}"
        payload = _get_json(url, access_token) or {}
        if payload.get("timeSeries"):
            return True
        raw_page_token = payload.get("nextPageToken")
        page_token = raw_page_token if isinstance(raw_page_token, str) else None
        if not page_token:
            return False


def _wait_for_delivery(
    *,
    project_id: str,
    trace_id: str,
    verification_id: str,
    metric_location: str,
    access_token: str,
    started_at: float,
    timeout_seconds: float,
    poll_seconds: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    trace_found = False
    metric_found = False
    while True:
        if not trace_found:
            trace_found = _trace_available(project_id, trace_id, access_token)
        if not metric_found:
            metric_found = _metric_available(
                project_id,
                verification_id,
                metric_location,
                access_token,
                started_at,
            )
        if trace_found and metric_found:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            missing = ", ".join(
                signal
                for signal, found in (
                    ("trace", trace_found),
                    ("metric", metric_found),
                )
                if not found
            )
            raise RuntimeError(f"collector verification data was not stored: {missing}")
        time.sleep(min(poll_seconds, remaining))


def verify(
    endpoint: str,
    token: str,
    *,
    project_id: str,
    metric_location: str,
    access_token: str,
    timeout_seconds: float = 15.0,
    delivery_timeout_seconds: float = 600.0,
) -> VerificationProbe:
    """Export real telemetry, verify storage, and require log rejection."""

    started_at = time.time()
    verification_id = f"collector-verify-{uuid.uuid4().hex}"
    trace_request, metric_request, log_request, trace_id = _probe_requests(
        verification_id,
        time.time_ns(),
    )
    metadata = (("authorization", f"Bearer {token}"),)
    with grpc.secure_channel(
        _authority(endpoint), grpc.ssl_channel_credentials()
    ) as channel:
        trace_response = TraceServiceStub(channel).Export(
            trace_request,
            metadata=metadata,
            timeout=timeout_seconds,
        )
        _raise_for_partial_rejection(
            trace_response,
            signal="spans",
            rejected_field="rejected_spans",
        )
        metric_response = MetricsServiceStub(channel).Export(
            metric_request,
            metadata=metadata,
            timeout=timeout_seconds,
        )
        _raise_for_partial_rejection(
            metric_response,
            signal="metric points",
            rejected_field="rejected_data_points",
        )
        try:
            LogsServiceStub(channel).Export(
                log_request,
                metadata=metadata,
                timeout=timeout_seconds,
            )
        except grpc.RpcError as error:
            if error.code() is not grpc.StatusCode.UNIMPLEMENTED:
                raise
        else:
            raise RuntimeError("collector unexpectedly accepted application logs")
    _wait_for_delivery(
        project_id=project_id,
        trace_id=trace_id,
        verification_id=verification_id,
        metric_location=metric_location,
        access_token=access_token,
        started_at=started_at,
        timeout_seconds=delivery_timeout_seconds,
    )
    return VerificationProbe(verification_id, trace_id, started_at)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--metric-location", required=True)
    args = parser.parse_args()
    probe = verify(
        args.endpoint,
        os.environ["COLLECTOR_ID_TOKEN"],
        project_id=args.project_id,
        metric_location=args.metric_location,
        access_token=os.environ["GOOGLE_OAUTH_ACCESS_TOKEN"],
    )
    print(
        "Verified collector ingestion "
        f"(verification_id={probe.verification_id}, trace_id={probe.trace_id})"
    )


if __name__ == "__main__":
    main()
