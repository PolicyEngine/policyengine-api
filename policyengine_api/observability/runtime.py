"""Explicit API v1 observability runtime ownership."""

from __future__ import annotations

import contextlib
from dataclasses import replace

from policyengine_observability import (
    LoggingConfig,
    ObservabilityConfig,
    ObservabilityRuntime,
    configure,
)

from policyengine_api.observability_identity import (
    deployment_identity,
    service_identity,
    standard_output_destination,
)

DISPATCH_ATTRIBUTE_KEYS = frozenset({"observability_id"})


def _build_runtime() -> ObservabilityRuntime:
    config = ObservabilityConfig.from_env(
        service=service_identity(),
        deployment=deployment_identity(),
        logging=LoggingConfig(
            destinations=(standard_output_destination(),),
            capture_standard_library=True,
        ),
        dispatch_attribute_keys=DISPATCH_ATTRIBUTE_KEYS,
    )
    config = replace(
        config,
        otel=replace(config.otel, sampling_ratio=1.0),
    )
    return configure(config)


runtime = _build_runtime()


def get_runtime() -> ObservabilityRuntime:
    """Return the process-wide runtime that was configured when this module loaded."""
    return runtime


def set_runtime_context(**attributes: object) -> None:
    """Bind local telemetry attributes without affecting application behavior."""
    # Telemetry must never affect application behavior.
    with contextlib.suppress(Exception):
        runtime.set_context(**attributes)


def record_unhandled_exception(error: Exception, *, status_code: int = 500) -> None:
    """Record an exception that reached a catch-all error handler."""
    # Telemetry must never affect application behavior.
    with contextlib.suppress(Exception):
        runtime.record_exception(error, handled=False, status_code=status_code)
