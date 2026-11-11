"""The seconds one admin request may spend waiting for Auth0's rate limit.

It imports no other application module, so both the Auth0 Management client,
which spends a budget's seconds on rate-limited requests, and the admin
service, which starts one budget for each admin request, can import it at
module level.
"""

from __future__ import annotations

import math

# An admin request's Auth0 calls wait at most this many seconds in total.
MAXIMUM_RATE_LIMIT_WAIT_SECONDS = 2.0


class RateLimitWaitBudget:
    """The seconds of rate-limit waiting one operation may still spend.

    An admin request gives every Auth0 call it makes the same budget, so
    their waits together stay within 2 seconds. A rate-limited request waits
    only when its whole wait fits in what is left.
    """

    def __init__(self, seconds: float = MAXIMUM_RATE_LIMIT_WAIT_SECONDS) -> None:
        """Start with ``seconds`` to spend."""
        self.remaining_seconds = seconds

    def take(self, seconds: float) -> bool:
        """Spend ``seconds`` and return True, or return False and spend nothing.

        A wait longer than what is left is refused, and so is one that is
        negative or not a finite number: taken, nan would leave nan seconds,
        which every later wait fits, and a negative wait would add seconds.
        """
        if (
            not math.isfinite(seconds)
            or seconds < 0
            or seconds > self.remaining_seconds
        ):
            return False
        self.remaining_seconds -= seconds
        return True
