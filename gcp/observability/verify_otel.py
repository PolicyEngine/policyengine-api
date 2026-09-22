"""Send and verify synthetic OTLP signals through the Cloud Run collector."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import grpc
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (
    LogsServiceStub,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import (
    LogRecord,
    ResourceLogs,
    ScopeLogs,
)
from opentelemetry.proto.resource.v1.resource_pb2 import (
    Resource as ProtoResource,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

PROJECT = os.environ.get("OBSERVABILITY_PROJECT_ID", "")
METRIC_NAME = "policyengine.verification.counter"
METRIC_TYPE = f"prometheus.googleapis.com/{METRIC_NAME}/counter"


def _gcloud_output(*arguments: str) -> str:
    return subprocess.check_output(
        ["gcloud", *arguments],
        text=True,
    ).strip()


def _identity_token(service_account: str, audience: str) -> str:
    return _gcloud_output(
        "auth",
        "print-identity-token",
        f"--impersonate-service-account={service_account}",
        f"--audiences={audience}",
    )


def _access_token() -> str:
    return _gcloud_output("auth", "print-access-token")


def _authorized_get(url: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def _send_signals(endpoint: str, service_account: str) -> dict[str, object]:
    identity_token = _identity_token(service_account, endpoint)
    headers = (("authorization", f"Bearer {identity_token}"),)
    credentials = grpc.ssl_channel_credentials()
    resource = Resource.create(
        {
            "service.name": "policyengine-observability-verification",
            "service.namespace": "policyengine.api-v1",
            "service.version": "2.0.0-verification",
            "service.role": "verification",
            "deployment.environment.name": "staging",
            "cloud.platform": "gcp_cloud_run",
            "cloud.region": "us-central1",
        }
    )

    trace_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        credentials=credentials,
        headers=headers,
        timeout=10,
    )
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(SimpleSpanProcessor(trace_exporter))
    tracer = trace_provider.get_tracer("policyengine.observability.verification")
    with tracer.start_as_current_span("policyengine.observability.verify") as span:
        span.set_attribute("policyengine.verification", True)
        trace_id = f"{span.get_span_context().trace_id:032x}"
    trace_provider.force_flush(timeout_millis=15_000)
    trace_provider.shutdown()

    metric_exporter = OTLPMetricExporter(
        endpoint=endpoint,
        credentials=credentials,
        headers=headers,
        timeout=10,
    )
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=60_000,
        export_timeout_millis=10_000,
    )
    metric_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    meter = metric_provider.get_meter("policyengine.observability.verification")
    counter = meter.create_counter(METRIC_NAME)
    counter.add(1, {"outcome": "success"})
    metric_provider.shutdown()

    host = urllib.parse.urlparse(endpoint).netloc
    channel = grpc.secure_channel(host, credentials)
    logs_stub = LogsServiceStub(channel)
    log_request = ExportLogsServiceRequest(
        resource_logs=[
            ResourceLogs(
                resource=ProtoResource(
                    attributes=[
                        KeyValue(
                            key="service.name",
                            value=AnyValue(
                                string_value="policyengine-observability-verification"
                            ),
                        )
                    ]
                ),
                scope_logs=[
                    ScopeLogs(
                        log_records=[
                            LogRecord(
                                time_unix_nano=time.time_ns(),
                                severity_text="INFO",
                                body=AnyValue(
                                    string_value="collector log rejection verification"
                                ),
                            )
                        ]
                    )
                ],
            )
        ]
    )
    log_status = "accepted"
    try:
        logs_stub.Export(log_request, timeout=10, metadata=headers)
    except grpc.RpcError as error:
        log_status = error.code().name
    finally:
        channel.close()

    return {
        "trace_id": trace_id,
        "metric_type": METRIC_TYPE,
        "log_export_status": log_status,
    }


def _wait_for_storage(
    *, trace_id: str, metric_type: str, timeout_seconds: int
) -> dict[str, object]:
    access_token = _access_token()
    deadline = time.monotonic() + timeout_seconds
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))
    end = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + timeout_seconds + 60)
    )
    metric_filter = urllib.parse.quote(f'metric.type = "{metric_type}"')
    metric_url = (
        f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries"
        f"?filter={metric_filter}&interval.startTime={start}"
        f"&interval.endTime={end}&view=HEADERS"
    )
    trace_url = (
        f"https://cloudtrace.googleapis.com/v1/projects/{PROJECT}/traces/{trace_id}"
    )
    trace_found = False
    metric_found = False
    while time.monotonic() < deadline and not (trace_found and metric_found):
        if not trace_found:
            try:
                trace_payload = _authorized_get(trace_url, access_token)
                trace_found = bool(trace_payload.get("spans"))
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
        if not metric_found:
            try:
                metric_payload = _authorized_get(metric_url, access_token)
                metric_found = bool(metric_payload.get("timeSeries"))
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
        if not (trace_found and metric_found):
            time.sleep(5)
    return {
        "trace_stored": trace_found,
        "metric_stored": metric_found,
    }


def main() -> int:
    if not PROJECT:
        raise SystemExit("Missing deployment variable: OBSERVABILITY_PROJECT_ID")
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--service-account", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    arguments = parser.parse_args()

    # Add a run identifier without placing high-cardinality values on the metric.
    run_id = secrets.token_hex(4)
    result = _send_signals(arguments.endpoint, arguments.service_account)
    result.update(
        _wait_for_storage(
            trace_id=str(result["trace_id"]),
            metric_type=str(result["metric_type"]),
            timeout_seconds=arguments.timeout_seconds,
        )
    )
    result["run_id"] = run_id
    print(json.dumps(result, sort_keys=True))

    return (
        0
        if (
            result["trace_stored"]
            and result["metric_stored"]
            and result["log_export_status"] != "accepted"
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
