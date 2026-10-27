"""Error records, the one record chosen per failure, and their fingerprints."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from telemetry_error_issues.normalization import (
    MISSING,
    environment_class,
    fingerprint_frames,
    service_family,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

REQUEST_COMPLETED_EVENT = "request.completed"
# Changing how fingerprints are computed changes every fingerprint, and the
# job matches existing issues only by the current algorithm. A change to it
# must say how existing issues are carried over.
FINGERPRINT_ALGORITHM = 1
FINGERPRINT_LENGTH = 16
MIN_FINGERPRINT_KEY_LENGTH = 32


@dataclass(frozen=True)
class ErrorRecord:
    """One ERROR record from the central log bucket, as the query returns it.

    The query returns identifiers only as SHA-256 hashes, stacks only as frame
    headers, and messages only as their first few words.
    """

    timestamp: datetime
    service_name: str
    environment_name: str | None
    event_name: str | None
    error_type: str | None
    error_handled: bool | None
    frames: tuple[str, ...]
    stack_truncated: bool
    message_template: str | None
    attribute_error_type: str | None
    failure_category: str | None
    route: str | None
    status_code: int | None
    operation_name: str | None
    request_key: str | None
    observability_key: str | None
    trace_key: str | None

    @property
    def family(self) -> str:
        """Return the service family that produced the record."""
        return service_family(self.service_name)

    @property
    def environment(self) -> str:
        """Return production, staging or other."""
        return environment_class(self.environment_name)

    @property
    def kind(self) -> str:
        """Return exception, message or failed_request.

        A record with an exception type is an exception, even a
        ``request.completed`` record. Any other ``request.completed`` record is
        a request that failed without a recorded exception.
        """
        if self.error_type:
            return "exception"
        if self.event_name == REQUEST_COMPLETED_EVENT:
            return "failed_request"
        return "message"


def _primary_preference(record: ErrorRecord) -> tuple[int, int, datetime]:
    """Sort key: exceptions before messages before request completions.

    Among exceptions, an unhandled one (the cause of an error response) comes
    first; otherwise the earliest record does.
    """
    if record.event_name == REQUEST_COMPLETED_EVENT:
        source_rank = 2
    elif record.error_type:
        source_rank = 0
    else:
        source_rank = 1
    handled_rank = 0 if record.error_handled is False else 1
    return source_rank, handled_rank, record.timestamp


def primary_records(records: Iterable[ErrorRecord]) -> list[ErrorRecord]:
    """Return one record per failure, in time order.

    Records of one service that share a request ID, or a trace when there is no
    request ID, describe one failure. A record with neither is its own failure.
    """
    failures: dict[tuple[str, str], list[ErrorRecord]] = {}
    standalone: list[ErrorRecord] = []
    for record in records:
        correlation = record.request_key or record.trace_key
        if correlation is None:
            standalone.append(record)
        else:
            failures.setdefault((record.family, correlation), []).append(record)
    chosen = [min(group, key=_primary_preference) for group in failures.values()]
    return sorted([*chosen, *standalone], key=lambda record: record.timestamp)


def fingerprint_parts(record: ErrorRecord) -> tuple[str, ...]:
    """Return the kind and the values that identify the record's error group.

    An exception's route is left out, so one shared failure doesn't open an
    issue for every route that reaches it.
    """
    kind = record.kind
    if kind == "exception":
        return (
            kind,
            record.family,
            record.error_type or MISSING,
            *fingerprint_frames(record.frames),
        )
    if kind == "message":
        return (
            kind,
            record.family,
            record.route or record.operation_name or MISSING,
            record.message_template or MISSING,
            record.attribute_error_type or MISSING,
            record.failure_category or MISSING,
        )
    status = MISSING if record.status_code is None else str(record.status_code)
    return (kind, record.family, record.route or MISSING, status)


def fingerprint_key(secret: str) -> bytes:
    """Return the HMAC key, rejecting a secret too short to be random."""
    if len(secret) < MIN_FINGERPRINT_KEY_LENGTH:
        msg = (
            "the fingerprint key must be at least "
            f"{MIN_FINGERPRINT_KEY_LENGTH} characters"
        )
        raise ValueError(msg)
    return secret.encode()


def fingerprint(record: ErrorRecord, key: bytes) -> str:
    """Return the record's error group as 16 hex characters of HMAC-SHA256.

    The key keeps anyone from confirming a guessed message or stack frame by
    hashing it and comparing the result with a public fingerprint.
    """
    payload = json.dumps(
        [FINGERPRINT_ALGORITHM, *fingerprint_parts(record)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return digest[:FINGERPRINT_LENGTH]
