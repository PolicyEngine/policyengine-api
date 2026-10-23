"""The rule that a complete v1 simulation or report result is final.

Simulation and report records are shared: identical requests reuse one record,
and anyone can update one by its ID. So once a record holds a complete result,
an update may only repeat it (a retried write, or a second browser finishing
the same calculation) and never change it.
"""

from collections.abc import Mapping


def changes_stored_result(record: object, values: Mapping[str, object]) -> bool:
    """Whether applying ``values`` would change any of those fields on ``record``.

    ``values`` holds decoded JSON, as stored, so a retry in either encoding of the
    same output is a repeat.
    """
    return any(getattr(record, field) != value for field, value in values.items())
