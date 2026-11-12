"""The messages for a simulation service answer that may follow a created record.

The route tests and the simulation service client's tests both import these.
This module imports nothing from the app, so the client's tests don't build
the app to read them.
"""

from __future__ import annotations


def submit_again(record: str) -> str:
    """Return the sentence asking the caller to submit the ``record`` again."""
    return (
        f"Submit the {record} again; if the first request went through, this "
        f"creates a second {record}."
    )


def answer_lost_message(error: str, record: str) -> str:
    """Return the message for an answer lost after the request may have arrived.

    ``error`` is the transport error's type or what a proxy answered.
    """
    return (
        "The simulation service may have received the request, but its answer "
        f"was lost ({error}). {submit_again(record)}"
    )


def possibly_created_message(status_and_code: str, record: str) -> str:
    """Return the message for a failure that may follow a created ``record``.

    ``status_and_code`` is the service's status and, when it gave one, its
    code, such as ``503 modal_call_refused``.
    """
    return (
        f"The simulation service may have created the {record}, but it failed "
        f"({status_and_code}). {submit_again(record)}"
    )
