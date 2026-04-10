"""
Lightweight OTLP observability helpers for the legacy policyengine-api service.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
import socket
from time import perf_counter
from typing import Any, Mapping

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_NAMESPACE,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


LOW_CARDINALITY_METRIC_KEYS = (
    "country",
    "simulation_kind",
    "country_package_version",
    "policyengine_version",
    "capture_mode",
)
SPAN_ATTRIBUTE_KEYS = (
    "run_id",
    "process_id",
    "request_id",
    "country",
    "simulation_kind",
    "geography_type",
    "geography_code",
    "country_package_name",
    "country_package_version",
    "policyengine_version",
    "data_version",
    "modal_app_name",
    "config_hash",
    "capture_mode",
)
STAGE_DURATION_METRIC_NAME = "policyengine.simulation.stage.duration.seconds"
QUEUE_DURATION_METRIC_NAME = "policyengine.simulation.queue.duration.seconds"
FAILURE_COUNT_METRIC_NAME = "policyengine.simulation.failure.count"


def parse_header_value_pairs(raw: str | None) -> dict[str, str]:
    if raw is None:
        return {}

    stripped = raw.strip()
    if not stripped:
        return {}

    headers: dict[str, str] = {}
    for pair in stripped.replace("\n", ",").split(","):
        candidate = pair.strip()
        if not candidate:
            continue
        key, separator, value = candidate.partition("=")
        if not separator:
            raise ValueError(
                "Expected OTLP headers in key=value format separated by commas"
            )
        headers[key.strip()] = value.strip()
    return headers


def parse_bool(raw: str | bool | None, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _normalize_attribute_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return json.dumps(value, sort_keys=True, default=_json_default)


def normalize_attributes(
    attributes: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if attributes is None:
        return normalized
    for key, value in attributes.items():
        normalized_value = _normalize_attribute_value(value)
        if normalized_value is not None:
            normalized[key] = normalized_value
    return normalized


class JsonPayloadFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.msg, Mapping):
            payload = dict(record.msg)
        elif isinstance(record.msg, str):
            return record.msg
        else:
            payload = {"message": record.getMessage()}
        payload.setdefault("severity", record.levelname)
        payload.setdefault("logger", record.name)
        return json.dumps(payload, sort_keys=True, default=_json_default)


@dataclass(frozen=True)
class RuntimeObservabilityConfig:
    enabled: bool
    shadow_mode: bool
    service_name: str
    environment: str
    otlp_endpoint: str | None
    otlp_headers: dict[str, str]

    @classmethod
    def from_env(
        cls,
        service_name: str,
        environment: str = "production",
    ) -> "RuntimeObservabilityConfig":
        return cls(
            enabled=parse_bool(os.getenv("OBSERVABILITY_ENABLED"), False),
            shadow_mode=parse_bool(
                os.getenv("OBSERVABILITY_SHADOW_MODE"),
                True,
            ),
            service_name=os.getenv("OBSERVABILITY_SERVICE_NAME", service_name),
            environment=os.getenv("OBSERVABILITY_ENVIRONMENT", environment),
            otlp_endpoint=os.getenv("OBSERVABILITY_OTLP_ENDPOINT"),
            otlp_headers=parse_header_value_pairs(
                os.getenv("OBSERVABILITY_OTLP_HEADERS")
            ),
        )


class NoOpSpan(AbstractContextManager["NoOpSpan"]):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(
        self, name: str, attributes: Mapping[str, Any] | None = None
    ) -> None:
        return None

    def get_traceparent(self) -> str | None:
        return None


class OTelSpan(AbstractContextManager["OTelSpan"]):
    def __init__(self, context_manager: AbstractContextManager):
        self._context_manager = context_manager
        self._span = None

    def __enter__(self):
        self._span = self._context_manager.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._context_manager.__exit__(exc_type, exc_value, traceback)

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is not None:
            self._span.set_attribute(key, _normalize_attribute_value(value))

    def add_event(
        self, name: str, attributes: Mapping[str, Any] | None = None
    ) -> None:
        if self._span is not None:
            self._span.add_event(name, normalize_attributes(attributes))

    def get_traceparent(self) -> str | None:
        if self._span is None:
            return None
        return build_traceparent(self._span.get_span_context())


class NoOpObservability:
    def emit_lifecycle_event(self, payload: dict[str, Any]) -> None:
        return None

    def emit_counter(
        self,
        name: str,
        value: int = 1,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        return None

    def emit_histogram(
        self,
        name: str,
        value: float,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        return None

    def span(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        parent_traceparent: str | None = None,
    ) -> NoOpSpan:
        return NoOpSpan()

    def flush(self) -> None:
        return None


class RuntimeObservability:
    def __init__(self, config: RuntimeObservabilityConfig):
        self.config = config
        resource = Resource.create(
            {
                SERVICE_NAME: config.service_name,
                SERVICE_NAMESPACE: "policyengine",
                DEPLOYMENT_ENVIRONMENT: config.environment,
                SERVICE_INSTANCE_ID: socket.gethostname(),
            }
        )

        self.tracer_provider = TracerProvider(resource=resource)
        self.meter_provider = MeterProvider(resource=resource)
        self.logger_provider = None

        if config.otlp_endpoint:
            endpoint = config.otlp_endpoint.rstrip("/")
            headers = config.otlp_headers or None
            self.tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=f"{endpoint}/v1/traces",
                        headers=headers,
                    )
                )
            )
            self.meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(
                            endpoint=f"{endpoint}/v1/metrics",
                            headers=headers,
                        )
                    )
                ],
            )
            from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                OTLPLogExporter,
            )

            self.logger_provider = LoggerProvider(resource=resource)
            self.logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(
                    OTLPLogExporter(
                        endpoint=f"{endpoint}/v1/logs",
                        headers=headers,
                    )
                )
            )

        self.tracer = self.tracer_provider.get_tracer(config.service_name)
        self.meter = self.meter_provider.get_meter(config.service_name)
        self.counter_cache: dict[str, Any] = {}
        self.histogram_cache: dict[str, Any] = {}

        self.lifecycle_logger = logging.getLogger(
            f"policyengine.observability.{config.service_name}"
        )
        self.lifecycle_logger.setLevel(logging.INFO)
        self.lifecycle_logger.propagate = False
        self.lifecycle_logger.handlers = []

        formatter = JsonPayloadFormatter()
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        self.lifecycle_logger.addHandler(stream_handler)

        if self.logger_provider is not None:
            logging_handler = LoggingHandler(
                level=logging.INFO,
                logger_provider=self.logger_provider,
            )
            logging_handler.setFormatter(formatter)
            self.lifecycle_logger.addHandler(logging_handler)

    def emit_lifecycle_event(self, payload: dict[str, Any]) -> None:
        self.lifecycle_logger.info(payload)

    def emit_counter(
        self,
        name: str,
        value: int = 1,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        counter = self.counter_cache.get(name)
        if counter is None:
            counter = self.meter.create_counter(name)
            self.counter_cache[name] = counter
        counter.add(value, attributes=normalize_attributes(attributes))

    def emit_histogram(
        self,
        name: str,
        value: float,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        histogram = self.histogram_cache.get(name)
        if histogram is None:
            histogram = self.meter.create_histogram(name)
            self.histogram_cache[name] = histogram
        histogram.record(value, attributes=normalize_attributes(attributes))

    def span(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        parent_traceparent: str | None = None,
    ) -> OTelSpan:
        context = None
        if parent_traceparent:
            context = TraceContextTextMapPropagator().extract(
                {"traceparent": parent_traceparent}
            )
        return OTelSpan(
            self.tracer.start_as_current_span(
                name,
                attributes=normalize_attributes(attributes),
                context=context,
            )
        )

    def flush(self) -> None:
        self.tracer_provider.force_flush()
        self.meter_provider.force_flush()
        if self.logger_provider is not None:
            self.logger_provider.force_flush()


_CACHE: dict[tuple, RuntimeObservability | NoOpObservability] = {}


def get_observability(
    service_name: str,
    environment: str = "production",
) -> RuntimeObservability | NoOpObservability:
    config = RuntimeObservabilityConfig.from_env(service_name, environment)
    key = (
        config.enabled,
        config.shadow_mode,
        config.service_name,
        config.environment,
        config.otlp_endpoint,
        tuple(sorted(config.otlp_headers.items())),
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    if not config.enabled:
        built: RuntimeObservability | NoOpObservability = NoOpObservability()
    else:
        built = RuntimeObservability(config)
    _CACHE[key] = built
    return built


def build_metric_attributes(
    telemetry: Mapping[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    if telemetry:
        for key in LOW_CARDINALITY_METRIC_KEYS:
            value = telemetry.get(key)
            if value is not None:
                attributes[key] = value
    attributes.update({k: v for k, v in extra.items() if v is not None})
    return attributes


def build_span_attributes(
    telemetry: Mapping[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    if telemetry:
        for key in SPAN_ATTRIBUTE_KEYS:
            value = telemetry.get(key)
            if value is not None:
                attributes[key] = value
    attributes.update({k: v for k, v in extra.items() if v is not None})
    return attributes


def build_lifecycle_event(
    *,
    stage: str,
    status: str,
    service: str,
    telemetry: Mapping[str, Any] | None = None,
    duration_seconds: float | None = None,
    details: Mapping[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_name": "simulation.lifecycle",
        "stage": stage,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "service": service,
        "details": dict(details or {}),
    }
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    if telemetry:
        payload.update({k: v for k, v in telemetry.items() if v is not None})
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def build_traceparent(span_context: Any) -> str | None:
    if not getattr(span_context, "is_valid", False):
        return None

    trace_flags = int(getattr(span_context, "trace_flags", 0))
    return (
        f"00-{span_context.trace_id:032x}-"
        f"{span_context.span_id:016x}-{trace_flags:02x}"
    )


def get_current_traceparent() -> str | None:
    return build_traceparent(trace.get_current_span().get_span_context())


def duration_since_requested_at(
    telemetry: Mapping[str, Any] | None,
) -> float | None:
    requested_at = None if telemetry is None else telemetry.get("requested_at")
    if not requested_at:
        return None
    try:
        requested = datetime.fromisoformat(str(requested_at))
    except ValueError:
        return None
    return (datetime.now(UTC) - requested.astimezone(UTC)).total_seconds()


class StageObservation(AbstractContextManager["StageObservation"]):
    def __init__(
        self,
        observability: RuntimeObservability | NoOpObservability | Any,
        *,
        stage: str,
        service: str,
        telemetry: Mapping[str, Any] | None = None,
        success_status: str = "ok",
        record_failure_counter: bool = False,
        details: Mapping[str, Any] | None = None,
        parent_traceparent: str | None = None,
        timer=perf_counter,
    ):
        self.observability = observability
        self.stage = stage
        self.service = service
        self.telemetry = telemetry
        self.success_status = success_status
        self.record_failure_counter = record_failure_counter
        self.details: dict[str, Any] = dict(details or {})
        self.parent_traceparent = parent_traceparent
        self.timer = timer
        self._start = 0.0
        self._span_context = None
        self.span = None

    def __enter__(self):
        self._start = self.timer()
        self._span_context = self.observability.span(
            self.stage,
            build_span_attributes(
                self.telemetry,
                service=self.service,
                stage=self.stage,
            ),
            parent_traceparent=self.parent_traceparent,
        )
        self.span = self._span_context.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        duration = max(0.0, self.timer() - self._start)
        status = self.success_status if exc_type is None else "failed"
        if exc_value is not None and "error" not in self.details:
            self.details["error"] = str(exc_value)

        self.observability.emit_histogram(
            STAGE_DURATION_METRIC_NAME,
            duration,
            attributes=build_metric_attributes(
                self.telemetry,
                service=self.service,
                stage=self.stage,
                status=status,
            ),
        )
        if exc_type is not None and self.record_failure_counter:
            self.observability.emit_counter(
                FAILURE_COUNT_METRIC_NAME,
                attributes=build_metric_attributes(
                    self.telemetry,
                    service=self.service,
                    stage=self.stage,
                    status="failed",
                ),
            )
        self.observability.emit_lifecycle_event(
            build_lifecycle_event(
                stage=self.stage,
                status=status,
                service=self.service,
                telemetry=self.telemetry,
                duration_seconds=duration,
                details=self.details,
            )
        )
        if self._span_context is None:
            return None
        return self._span_context.__exit__(exc_type, exc_value, traceback)


def observe_stage(
    observability: RuntimeObservability | NoOpObservability | Any,
    *,
    stage: str,
    service: str,
    telemetry: Mapping[str, Any] | None = None,
    success_status: str = "ok",
    record_failure_counter: bool = False,
    details: Mapping[str, Any] | None = None,
    parent_traceparent: str | None = None,
    timer=perf_counter,
) -> StageObservation:
    return StageObservation(
        observability,
        stage=stage,
        service=service,
        telemetry=telemetry,
        success_status=success_status,
        record_failure_counter=record_failure_counter,
        details=details,
        parent_traceparent=parent_traceparent,
        timer=timer,
    )
