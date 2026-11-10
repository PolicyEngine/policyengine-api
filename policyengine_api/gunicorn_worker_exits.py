"""Write an ERROR record when a signal ends a gunicorn worker (issue #4242).

When a signal ends a worker, as the kernel's out-of-memory killer's SIGKILL
does, gunicorn's main process logs "Worker (pid:N) was sent SIGKILL!" as plain
text on standard error, which the daily telemetry error report never reads.
These hooks, which ``policyengine_api.gunicorn_config`` gives gunicorn, write
an ERROR record through policyengine-observability instead, naming the signal
and the worker's process ID, in the operation ``gunicorn.worker_exit`` so the
report's issue names where it comes from. The report groups worker kills like
any other error, one group per signal.

gunicorn calls its ``child_exit`` hook after reaping a worker but doesn't pass
the worker's wait status, so ``on_starting`` wraps ``os.waitpid`` in the main
process to keep the status of each child it reaps. It also wraps the main
process's ``kill_worker`` method to note each worker the main process itself
sends SIGKILL.

A worker that exits with an exit code writes no record, such as one that
exits after serving gunicorn's ``max_requests``, nor does one that a signal
ends normally:

- SIGTERM or SIGQUIT: the signals gunicorn's main process sends to stop a
  worker, gracefully or at once. Cloud Run stops an instance by sending
  SIGTERM to the main process, which sends it on to the workers.
- SIGINT, which an interrupt from a shell (Ctrl-C) sends to every process in
  the group, workers included.
- SIGKILL that the main process sent, except after the worker's timeout: when
  it shuts down, the main process kills the workers still running once its
  graceful timeout ends.

Any other signal writes an ERROR record: SIGKILL from anything else, such as
the kernel's out-of-memory killer, also while the main process shuts down;
SIGKILL that the main process sent a worker that missed its timeout (none
does in production, which runs with ``--timeout 0``); and signals such as
SIGSEGV or SIGABRT that a crash raises.

The hooks run in gunicorn's main process, which forks the workers that import
the API. This module never imports ``policyengine_api.observability``, whose
import builds the API's runtime, because a worker forked afterwards would
reuse that runtime instead of building its own. For the same reason the
operation name isn't taken from ``policyengine_api.observability.stages``.
Each record gets a runtime of its own, with OpenTelemetry off and only the
standard-output destination, which writes inline: building one starts no
thread and opens no connection, so nothing is left for a later worker to
inherit. Shutting it down would start threads, and there is nothing to flush,
so it is left to the garbage collector.

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
WORKER_EXIT_OPERATION = "gunicorn.worker_exit"
# Statuses and kills wait until child_exit reports their worker, which removes
# them. gunicorn calls child_exit for every worker it reaps, so only other
# children, such as the new main process after a SIGUSR2 upgrade, and workers
# that had already exited when killed, stay. The limit keeps those from adding
# up.
MAX_KEPT_PROCESSES = 64


class GunicornLog(Protocol):
    """The part of gunicorn's error log the hooks use."""

    def exception(self, msg: str, *args: object) -> None:
        """Write an ERROR message with the exception being handled."""


class MainProcess(Protocol):
    """The part of gunicorn's ``Arbiter`` the hooks use."""

    pid: int
    log: GunicornLog

    def kill_worker(self, pid: int, sig: int) -> None:
        """Send a signal to one worker."""


class Worker(Protocol):
    """The part of gunicorn's ``Worker`` the hooks read."""

    pid: int
    aborted: bool


def _keep(kept: dict[int, int], pid: int, value: int) -> None:
    while len(kept) >= MAX_KEPT_PROCESSES:
        del kept[next(iter(kept))]
    kept[pid] = value


class _WorkerExits:
    """Keeps what gunicorn's main process reaps, and the workers it kills."""

    def __init__(self) -> None:
        self._statuses: dict[int, int] = {}
        self._killed: dict[int, int] = {}
        self._waitpid: Callable[[int, int], tuple[int, int]] | None = None

    def keep_reaped_statuses(self, main_process_pid: int) -> None:
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
                _keep(statuses, reaped_pid, status)
            return reaped

        self._waitpid = keeping_waitpid
        os.waitpid = keeping_waitpid

    def note_kills(self, server: MainProcess) -> None:
        """Wrap ``server.kill_worker`` to note each worker sent SIGKILL."""
        kill_worker = server.kill_worker
        killed = self._killed

        def noting_kill_worker(pid: int, sig: int) -> None:
            if sig == signal.SIGKILL:
                _keep(killed, pid, sig)
            kill_worker(pid, sig)

        # gunicorn calls self.kill_worker, so this Arbiter's instance attribute
        # takes the place of the method.
        server.kill_worker = noting_kill_worker

    def pop(self, pid: int) -> tuple[int | None, bool]:
        """Return and forget ``pid``'s status, and if the main process killed it."""
        return self._statuses.pop(pid, None), self._killed.pop(pid, None) is not None


_EXITS = _WorkerExits()


def unexpected_signal(
    status: int | None, *, killed_by_main_process: bool
) -> int | None:
    """Return the signal that ended a worker, unless it ended normally.

    ``killed_by_main_process`` says whether gunicorn's main process sent the
    worker SIGKILL other than after the worker's timeout.
    """
    if status is None or not os.WIFSIGNALED(status):
        return None
    signal_number = os.WTERMSIG(status)
    if signal_number in STOP_SIGNALS:
        return None
    if signal_number == signal.SIGKILL and killed_by_main_process:
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
    runtime = configure(worker_exit_config())
    with runtime.operation(WORKER_EXIT_OPERATION):
        runtime.log(
            f"Signal {label} ended gunicorn worker process {worker_pid}",
            severity="ERROR",
            attributes={
                "signal": label,
                "signal_number": signal_number,
                "worker_pid": worker_pid,
            },
        )


def on_starting(server: MainProcess) -> None:
    """Gunicorn hook: keep how each worker ends, and which ones it kills."""
    for start_watching in (
        lambda: _EXITS.keep_reaped_statuses(server.pid),
        lambda: _EXITS.note_kills(server),
    ):
        try:
            start_watching()
        except Exception:
            with contextlib.suppress(Exception):
                server.log.exception("Could not watch how gunicorn workers end")


def child_exit(server: MainProcess, worker: Worker) -> None:
    """Gunicorn hook: record a worker that a signal ended unexpectedly."""
    try:
        status, killed = _EXITS.pop(worker.pid)
        signal_number = unexpected_signal(
            status,
            killed_by_main_process=killed and not getattr(worker, "aborted", False),
        )
        if signal_number is not None:
            record_signal_exit(worker.pid, signal_number)
    except Exception:
        with contextlib.suppress(Exception):
            server.log.exception(
                "Could not record how gunicorn worker process %s ended",
                worker.pid,
            )
