"""Send empty trace and metric exports to an authenticated OTLP endpoint."""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

import grpc
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2_grpc import (
    MetricsServiceStub,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (
    LogsServiceStub,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import (
    TraceServiceStub,
)


def _authority(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("collector endpoint must be an HTTPS URL")
    return f"{parsed.hostname}:{parsed.port or 443}"


def verify(endpoint: str, token: str, timeout_seconds: float = 15.0) -> None:
    """Verify trace and metric export and the absence of a logs receiver."""

    metadata = (("authorization", f"Bearer {token}"),)
    with grpc.secure_channel(
        _authority(endpoint), grpc.ssl_channel_credentials()
    ) as channel:
        TraceServiceStub(channel).Export(
            ExportTraceServiceRequest(),
            metadata=metadata,
            timeout=timeout_seconds,
        )
        MetricsServiceStub(channel).Export(
            ExportMetricsServiceRequest(),
            metadata=metadata,
            timeout=timeout_seconds,
        )
        try:
            LogsServiceStub(channel).Export(
                ExportLogsServiceRequest(),
                metadata=metadata,
                timeout=timeout_seconds,
            )
        except grpc.RpcError as error:
            if error.code() is grpc.StatusCode.UNIMPLEMENTED:
                return
            raise
        raise RuntimeError("collector unexpectedly accepted application logs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    verify(args.endpoint, args.token)


if __name__ == "__main__":
    main()
