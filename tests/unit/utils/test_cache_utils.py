"""Regression tests for issue #3450.

make_cache_key previously used `str(hash(...))`, whose value depends
on PYTHONHASHSEED. Two workers (or even two processes) produced
different keys for identical inputs, defeating the cache.
Switch to SHA-256 so the digest is deterministic across processes.
"""

import hashlib
import subprocess
import sys
import textwrap

from flask import Flask

from policyengine_api.utils.cache_utils import make_cache_key


def test_make_cache_key_deterministic_within_process():
    app = Flask(__name__)

    with app.test_request_context(
        "/us/economy/1/over/2?foo=bar",
        method="POST",
        json={"alpha": 1, "beta": [2, 3]},
    ):
        first = make_cache_key()
    with app.test_request_context(
        "/us/economy/1/over/2?foo=bar",
        method="POST",
        json={"alpha": 1, "beta": [2, 3]},
    ):
        second = make_cache_key()

    assert first == second


def test_make_cache_key_is_sha256_hex():
    app = Flask(__name__)
    with app.test_request_context(
        "/us/economy/1/over/2",
        method="POST",
        json={"hello": "world"},
    ):
        key = make_cache_key()

    # 64-character lowercase hex string with no non-hex characters.
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)

    # Exact digest value computed directly must match.
    # full_path is "/us/economy/1/over/2?" (Flask appends '?' when no query string)
    # and json.dumps(..., separators=("", "")) produces no separators.
    import json

    expected = hashlib.sha256(
        (
            "/us/economy/1/over/2?"
            + json.dumps({"hello": "world"}, separators=("", ""))
        ).encode("utf-8")
    ).hexdigest()
    assert key == expected


def test_make_cache_key_stable_across_processes():
    """Two independent Python processes must produce the same cache
    key for the same inputs, even though they use different
    PYTHONHASHSEED values."""
    script = textwrap.dedent(
        """
        from flask import Flask
        from policyengine_api.utils.cache_utils import make_cache_key

        app = Flask(__name__)
        with app.test_request_context(
            "/us/economy/1/over/2?foo=bar",
            method="POST",
            json={"alpha": 1},
        ):
            print(make_cache_key())
        """
    )

    def run_with_seed(seed: str) -> str:
        env_cmd = [sys.executable, "-c", script]
        result = subprocess.run(
            env_cmd,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "PYTHONHASHSEED": seed,
            },
            check=True,
        )
        return result.stdout.strip()

    # Using PYTHONHASHSEED=0 (deterministic) vs random seed must match.
    key_seed_0 = run_with_seed("0")
    key_seed_1 = run_with_seed("1")
    assert key_seed_0 == key_seed_1
