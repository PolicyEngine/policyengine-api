"""Tests for .github/scripts/request_ci_server_token.sh.

The script requests the CI server credential, an Auth0 client-credentials
token, from the tested environment's own tenant. A fake ``curl`` first on
``PATH`` records its arguments and the request body it reads from standard
input, and answers as Auth0's ``/oauth/token`` would; ``jq`` is the real one.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/request_ci_server_token.sh"
STAGING_TENANT = "policyengine-api-staging.example.test"
STAGING_AUDIENCE = "https://staging-api.example.test/"
CI_CLIENT_ID = "CiServerClient000000000000000001"
CLIENT_SECRET = "ci-client-secret-value-0001"
ACCESS_TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjaSJ9.c2lnbmF0dXJl"
TOKEN_RESPONSE = json.dumps(
    {"access_token": ACCESS_TOKEN, "token_type": "Bearer", "expires_in": 86400}
)
REQUIRED_NAMES = (
    "CI_SERVER_AUTH0_DOMAIN",
    "CI_SERVER_AUTH0_CLIENT_ID",
    "CI_SERVER_AUTH0_CLIENT_SECRET",
    "CI_SERVER_AUTH0_AUDIENCE",
    "PUBLIC_API_SERVER_AUTH_ISSUER",
    "PUBLIC_API_AUTH_AUDIENCE",
    "PUBLIC_API_SERVER_CLIENT_IDS",
    "GITHUB_OUTPUT",
)


@dataclass(frozen=True)
class ScriptRun:
    """One run of the script: its result, what curl got, and the step output."""

    result: subprocess.CompletedProcess[str]
    curl_calls: list[list[str]]
    request_bodies: list[str]
    step_output: str


def _staging_environment(step_output: Path) -> dict[str, str]:
    """Return a staging job's settings, with the CI client on the allow list."""
    return {
        "CI_SERVER_AUTH0_DOMAIN": STAGING_TENANT,
        "CI_SERVER_AUTH0_CLIENT_ID": CI_CLIENT_ID,
        "CI_SERVER_AUTH0_CLIENT_SECRET": CLIENT_SECRET,
        "CI_SERVER_AUTH0_AUDIENCE": STAGING_AUDIENCE,
        "PUBLIC_API_SERVER_AUTH_ISSUER": f"https://{STAGING_TENANT}/",
        "PUBLIC_API_AUTH_AUDIENCE": STAGING_AUDIENCE,
        "PUBLIC_API_SERVER_CLIENT_IDS": (
            f"WebsitePreviewClient000000000001,{CI_CLIENT_ID}"
        ),
        "GITHUB_OUTPUT": str(step_output),
    }


def _fake_curl(tmp_path: Path, *, response: str, exit_code: int) -> Path:
    """Write a curl that records each call and prints ``response``."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    calls_directory = tmp_path / "curl-calls"
    calls_directory.mkdir()
    response_path = tmp_path / "curl-response.json"
    response_path.write_text(response, encoding="utf-8")
    curl_path = bin_directory / "curl"
    curl_path.write_text(
        "#!/usr/bin/env bash\n"
        f'call_directory="$(mktemp -d "{calls_directory}/call.XXXXXX")"\n'
        'printf "%s\\n" "$@" > "${call_directory}/arguments"\n'
        'cat > "${call_directory}/body"\n'
        f'cat "{response_path}"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    curl_path.chmod(0o755)
    return bin_directory


def _run(
    tmp_path: Path,
    *,
    overrides: dict[str, str] | None = None,
    removed: tuple[str, ...] = (),
    response: str = TOKEN_RESPONSE,
    curl_exit_code: int = 0,
) -> ScriptRun:
    step_output = tmp_path / "github-output"
    step_output.write_text("", encoding="utf-8")
    bin_directory = _fake_curl(tmp_path, response=response, exit_code=curl_exit_code)
    environment = {
        "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        **_staging_environment(step_output),
        **(overrides or {}),
    }
    for name in removed:
        environment.pop(name)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    call_directories = sorted((tmp_path / "curl-calls").iterdir())
    return ScriptRun(
        result=result,
        curl_calls=[
            (call / "arguments").read_text(encoding="utf-8").splitlines()
            for call in call_directories
        ],
        request_bodies=[
            (call / "body").read_text(encoding="utf-8") for call in call_directories
        ],
        step_output=step_output.read_text(encoding="utf-8"),
    )


def _assert_refused_before_any_request(run: ScriptRun, *expected_words: str) -> None:
    assert run.result.returncode != 0
    for expected_word in expected_words:
        assert expected_word in run.result.stderr
    assert run.curl_calls == []
    assert run.step_output == ""
    assert CLIENT_SECRET not in run.result.stdout + run.result.stderr


def test_requests_one_token_from_the_tenant_and_writes_it_to_the_step_output(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.result.stderr
    assert len(run.curl_calls) == 1
    (curl_arguments,) = run.curl_calls
    assert curl_arguments[-1] == f"https://{STAGING_TENANT}/oauth/token"
    assert "--fail-with-body" in curl_arguments
    assert "--data-binary" in curl_arguments
    assert curl_arguments[curl_arguments.index("--data-binary") + 1] == "@-"
    assert json.loads(run.request_bodies[0]) == {
        "grant_type": "client_credentials",
        "client_id": CI_CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "audience": STAGING_AUDIENCE,
    }
    assert run.step_output == f"token={ACCESS_TOKEN}\n"


def test_masks_the_token_and_never_prints_the_secret(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.result.stderr
    # The client secret reaches curl only on standard input.
    assert all(CLIENT_SECRET not in argument for argument in run.curl_calls[0])
    printed = run.result.stdout + run.result.stderr
    assert CLIENT_SECRET not in printed
    # The only printed copy of the token is the mask command, printed first, so
    # GitHub hides the token before anything else could print it.
    first_printed_line = run.result.stdout.splitlines()[0]
    assert first_printed_line == f"::add-mask::{ACCESS_TOKEN}"
    assert printed.count(ACCESS_TOKEN) == 1


@pytest.mark.parametrize(
    "configured_domain",
    [
        f"https://{STAGING_TENANT}",
        f"https://{STAGING_TENANT}/",
        f"{STAGING_TENANT}/",
    ],
)
def test_accepts_the_tenant_host_with_a_scheme_or_trailing_slash(
    tmp_path: Path, configured_domain: str
) -> None:
    run = _run(tmp_path, overrides={"CI_SERVER_AUTH0_DOMAIN": configured_domain})

    assert run.result.returncode == 0, run.result.stderr
    assert run.curl_calls[0][-1] == f"https://{STAGING_TENANT}/oauth/token"


@pytest.mark.parametrize("name", REQUIRED_NAMES)
def test_fails_without_a_required_setting(tmp_path: Path, name: str) -> None:
    run = _run(tmp_path, removed=(name,))

    _assert_refused_before_any_request(run, name)


@pytest.mark.parametrize("name", REQUIRED_NAMES[:-1])
def test_a_blank_setting_counts_as_missing(tmp_path: Path, name: str) -> None:
    run = _run(tmp_path, overrides={name: " \t"})

    _assert_refused_before_any_request(run, name)


def test_refuses_a_tenant_the_tested_deployment_does_not_accept(
    tmp_path: Path,
) -> None:
    # A production client in a staging job: its tokens would be sent to the
    # staging candidate, which accepts only the staging tenant's.
    run = _run(
        tmp_path, overrides={"CI_SERVER_AUTH0_DOMAIN": "policyengine-api.example.test"}
    )

    _assert_refused_before_any_request(
        run, "CI_SERVER_AUTH0_DOMAIN", "PUBLIC_API_SERVER_AUTH_ISSUER"
    )


def test_refuses_an_audience_the_tested_deployment_does_not_accept(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path, overrides={"CI_SERVER_AUTH0_AUDIENCE": "https://api.example.test/"}
    )

    _assert_refused_before_any_request(
        run, "CI_SERVER_AUTH0_AUDIENCE", "PUBLIC_API_AUTH_AUDIENCE"
    )


@pytest.mark.parametrize(
    "allowed_client_ids",
    [
        "WebsitePreviewClient000000000001",
        # Only whole entries match, not part of one.
        f"{CI_CLIENT_ID}X,X{CI_CLIENT_ID}",
    ],
)
def test_refuses_a_client_the_tested_deployment_does_not_allow(
    tmp_path: Path, allowed_client_ids: str
) -> None:
    run = _run(tmp_path, overrides={"PUBLIC_API_SERVER_CLIENT_IDS": allowed_client_ids})

    _assert_refused_before_any_request(
        run, "CI_SERVER_AUTH0_CLIENT_ID", "PUBLIC_API_SERVER_CLIENT_IDS"
    )


@pytest.mark.parametrize(
    "configured_domain",
    [f"{STAGING_TENANT}/oauth", f"{STAGING_TENANT}?x=1", "user@host.example.test"],
)
def test_refuses_a_tenant_that_is_not_a_bare_host(
    tmp_path: Path, configured_domain: str
) -> None:
    run = _run(tmp_path, overrides={"CI_SERVER_AUTH0_DOMAIN": configured_domain})

    _assert_refused_before_any_request(run, "CI_SERVER_AUTH0_DOMAIN")


def test_fails_when_auth0_refuses_the_request(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        response='{"error":"access_denied","error_description":"Unauthorized"}',
        curl_exit_code=22,
    )

    assert run.result.returncode != 0
    assert f"https://{STAGING_TENANT}/oauth/token" in run.result.stderr
    # Auth0's own reason, such as a missing client grant, is shown.
    assert "access_denied: Unauthorized" in run.result.stderr
    assert "--fail-with-body" in run.curl_calls[0]
    assert run.step_output == ""
    assert CLIENT_SECRET not in run.result.stdout + run.result.stderr


@pytest.mark.parametrize(
    "response",
    [
        '{"token_type":"Bearer"}',
        '{"access_token":""}',
        '{"access_token":null}',
        "not json",
        # A token GitHub could not hold in one output line, or read as more.
        json.dumps({"access_token": f"{ACCESS_TOKEN}\nother=value"}),
        json.dumps({"access_token": f"{ACCESS_TOKEN} {ACCESS_TOKEN}"}),
    ],
    ids=["no-token", "empty", "null", "not-json", "newline", "space"],
)
def test_fails_when_auth0_returns_no_usable_token(
    tmp_path: Path, response: str
) -> None:
    run = _run(tmp_path, response=response)

    assert run.result.returncode != 0
    assert "access token" in run.result.stderr
    assert run.step_output == ""
    assert "::add-mask::" not in run.result.stdout
    assert ACCESS_TOKEN not in run.result.stdout + run.result.stderr
