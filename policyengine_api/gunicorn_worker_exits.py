"""Write an ERROR record when a signal ends a gunicorn worker (issue #4242).

When a signal ends a worker, as the kernel's out-of-memory killer's SIGKILL
does, gunicorn's main process logs "Worker (pid:N) was sent SIGKILL!" as plain
text on standard error, which the daily telemetry error report never reads.
These hooks, which ``policyengine_api.gunicorn_config`` gives gunicorn, write
an ERROR record through policyengine-observability instead, naming the signal
and the worker's process ID, so the report groups worker kills like any other
error.

gunicorn calls its ``child_exit`` hook after reaping a worker but doesn't pass
the worker's wait status, so ``on_starting`` wraps ``os.waitpid`` in the main
process to keep the status of each child it reaps.

A worker that exits with an exit code writes no record, such as one that
exits after serving gunicorn's ``max_requests``, nor does one that a signal
ends normally:

- SIGTERM, SIGINT or SIGQUIT: the signals gunicorn's main process sends to
  stop a worker, gracefully or at once. Cloud Run stops an instance by sending
  SIGTERM to the main process, which sends it on to the workers.
- SIGKILL once the main process has started shutting down, which it does by
  closing its listening sockets: it kills the workers still running when its
  graceful timeout ends.

Any other signal writes an ERROR record: SIGKILL at any other time, and
signals such as SIGSEGV or SIGABRT that a crash raises.

The hooks run in gunicorn's main process, which forks the workers that import
the API. This module never imports ``policyengine_api.observability``, whose
import builds the API's runtime, because a worker forked afterwards would
reuse that runtime instead of building its own. Each record gets a runtime of
its own, with OpenTelemetry off and only the standard-output destination,
which writes inline: building one starts no thread and opens no connection,
so nothing is left for a later worker to inherit. Shutting it down would start
threads, and there is nothing to flush, so it is left to the garbage collector.

The hooks never raise: gunicorn's main loop stops every worker and exits when
a hook raises.
"""

from __future__ import annotations

import contextlib
import os
import signal
from typing import TYPE_CHECKING, Protocol

from policyengine_observability import (
    LoggingConfig,
    ObservabilityConfig,
    OTelConfig,
    configure,
)

from policyengine_api.observability_identity import (
    deployment_identity,
    service_identity,
    standard_output_destination,
)

if TYPE_CHECKING:
    from collections.abc import Callable

STOP_SIGNALS = frozenset({signal.SIGTERM, signal.SIGINT, signal.SIGQUIT})
# Statuses wait until child_exit reports their worker, which removes them.
# gunicorn calls child_exit for every worker it reaps, so only other children,
# such as the new main process after a SIGUSR2 upgrade, stay. The limit keeps
# those from adding up.
MAX_KEPT_STATUSES = 64


class GunicornLog(Protocol):
    """The part of gunicorn's error log the hooks use."""

    def exception(self, msg: str, *args: object) -> None:
        """Write an ERROR message with the exception being handled."""


class MainProcess(Protocol):
    """The part of gunicorn's ``Arbiter`` the hooks read."""

    pid: int
    LISTENERS: list[object]
    log: GunicornLog


class Worker(Protocol):
    """The part of gunicorn's ``Worker`` the hooks read."""

    pid: int


class _ReapedStatuses:
    """Keeps the wait status of each child gunicorn's main process reaps."""

    def __init__(self) -> None:
        self._statuses: dict[int, int] = {}
        self._waitpid: Callable[[int, int], tuple[int, int]] | None = None

    def watch(self, main_process_pid: int) -> None:
        """Wrap ``os.waitpid`` so that the main process keeps what it reaps.

        The wrapper returns what ``os.waitpid`` returns and keeps nothing in
        another process, such as a worker, which inherits it when forked.
        """
        if os.waitpid is self._waitpid:
            return
        waitpid = os.waitpid
        statuses = self._statuses

        def keeping_waitpid(pid: int, options: int, /) -> tuple[int, int]:
            reaped = waitpid(pid, options)
            reaped_pid, status = reaped
            if reaped_pid > 0 and os.getpid() == main_process_pid:
                while len(statuses) >= MAX_KEPT_STATUSES:
                    del statuses[next(iter(statuses))]
                statuses[reaped_pid] = status
            return reaped

        self._waitpid = keeping_waitpid
        os.waitpid = keeping_waitpid

    def pop(self, pid: int) -> int | None:
        """Return and forget the status kept for ``pid``, if any."""
        return self._statuses.pop(pid, None)


_REAPED = _ReapedStatuses()


def unexpected_signal(status: int | None, *, main_process_stopping: bool) -> int | None:
    """Return the signal that ended a worker, unless it ended normally."""
    if status is None or not os.WIFSIGNALED(status):
        return None
    signal_number = os.WTERMSIG(status)
    if signal_number in STOP_SIGNALS:
        return None
    if signal_number == signal.SIGKILL and main_process_stopping:
        return None
    return signal_number


def signal_label(signal_number: int) -> str:
    """Return a signal's name, such as SIGKILL, or its number if it has none."""
    try:
        return signal.Signals(signal_number).name
    except ValueError:
        return str(signal_number)


def worker_exit_config() -> ObservabilityConfig:
    """Return the configuration of a runtime that writes one record inline."""
    return ObservabilityConfig(
        service=service_identity(),
        deployment=deployment_identity(),
        logging=LoggingConfig(destinations=(standard_output_destination(),)),
        otel=OTelConfig(enabled=False),
    )


def record_signal_exit(worker_pid: int, signal_number: int) -> None:
    """Write the ERROR record for a worker that a signal ended."""
    label = signal_label(signal_number)
    configure(worker_exit_config()).log(
        f"Signal {label} ended gunicorn worker process {worker_pid}",
        severity="ERROR",
        attributes={
            "signal": label,
            "signal_number": signal_number,
            "worker_pid": worker_pid,
        },
    )


def on_starting(server: MainProcess) -> None:
    """Gunicorn hook: keep the status of each worker the main process reaps."""
    try:
        _REAPED.watch(server.pid)
    except Exception:
        with contextlib.suppress(Exception):
            server.log.exception("Could not watch how gunicorn workers end")


def child_exit(server: MainProcess, worker: Worker) -> None:
    """Gunicorn hook: record a worker that a signal ended unexpectedly."""
    try:
        signal_number = unexpected_signal(
            _REAPED.pop(worker.pid),
            main_process_stopping=not server.LISTENERS,
        )
        if signal_number is not None:
            record_signal_exit(worker.pid, signal_number)
    except Exception:
        with contextlib.suppress(Exception):
            server.log.exception(
                "Could not record how gunicorn worker process %s ended",
                worker.pid,
            )
