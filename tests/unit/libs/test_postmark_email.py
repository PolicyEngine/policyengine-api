"""Unit tests for :mod:`policyengine_api.libs.postmark_email`."""

from __future__ import annotations

import json

import httpx
import pytest

from policyengine_api.libs.postmark_email import (
    POSTMARK_TEMPLATE_URL,
    SEND_ATTEMPTS,
    EmailSendError,
    PostmarkConfigurationError,
    PostmarkEmailSender,
    PostmarkSettings,
    build_postmark_email_sender,
    load_postmark_settings,
)

SECRET_RESOURCE = "projects/p/secrets/postmark-server-token/versions/latest"
SENDER = "PolicyEngine <no-reply@policyengine.org>"
APP_URL = "https://app.policyengine.org"
COMPLETE_SETTINGS = {
    "POSTMARK_SERVER_TOKEN_SECRET_RESOURCE": SECRET_RESOURCE,
    "POSTMARK_SENDER_ADDRESS": SENDER,
    "POLICYENGINE_APP_URL": APP_URL,
}


def _sender(
    responses: list[httpx.Response | Exception],
    **settings: str,
) -> tuple[PostmarkEmailSender, list[httpx.Request], list[float]]:
    """Build a sender whose requests get ``responses`` in order."""
    requests: list[httpx.Request] = []
    waits: list[float] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    values = {
        "sender_address": SENDER,
        "app_url": APP_URL,
        "server_token": "server-token",
    }
    values.update(settings)
    return (
        PostmarkEmailSender(
            PostmarkSettings(**values),
            http_client=httpx.Client(transport=httpx.MockTransport(answer)),
            secret_loader=lambda _resource: "loaded-token\n",
            sleep=waits.append,
        ),
        requests,
        waits,
    )


def _send(sender: PostmarkEmailSender) -> None:
    sender.send_template(
        to="ada@example.org",
        template_alias="user-type-changed",
        template_model={"user_type": "author"},
    )


def test_settings_are_optional_and_all_or_none() -> None:
    assert load_postmark_settings({}) is None
    assert build_postmark_email_sender({}) is None
    for left_out in COMPLETE_SETTINGS:
        partial = {
            name: value for name, value in COMPLETE_SETTINGS.items() if name != left_out
        }
        with pytest.raises(PostmarkConfigurationError, match="partially configured"):
            load_postmark_settings(partial)
    with pytest.raises(PostmarkConfigurationError, match="exactly one"):
        load_postmark_settings(
            COMPLETE_SETTINGS | {"POSTMARK_SERVER_TOKEN": "server-token"}
        )


def test_complete_settings_keep_the_token_out_of_their_repr() -> None:
    settings = load_postmark_settings(
        {
            "POSTMARK_SERVER_TOKEN": " server-token ",
            "POSTMARK_SENDER_ADDRESS": f" {SENDER} ",
            "POLICYENGINE_APP_URL": f"{APP_URL}/",
        }
    )

    assert settings == PostmarkSettings(
        sender_address=SENDER, app_url=APP_URL, server_token="server-token"
    )
    assert "server-token" not in repr(settings)
    assert load_postmark_settings(COMPLETE_SETTINGS) == PostmarkSettings(
        sender_address=SENDER,
        app_url=APP_URL,
        server_token_resource=SECRET_RESOURCE,
    )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("POSTMARK_SERVER_TOKEN_SECRET_RESOURCE", "postmark-token", "is invalid"),
        ("POSTMARK_SENDER_ADDRESS", "no-reply", "an email address"),
        ("POSTMARK_SENDER_ADDRESS", "a@b.org\nBcc: c@d.org", "an email address"),
        ("POLICYENGINE_APP_URL", "app.policyengine.org", "https"),
        ("POLICYENGINE_APP_URL", "http://app.policyengine.org", "https"),
        ("POLICYENGINE_APP_URL", f"{APP_URL}/?next=1", "query or fragment"),
        ("POLICYENGINE_APP_URL", f"{APP_URL}/#top", "query or fragment"),
    ],
)
def test_invalid_settings_are_refused_without_their_values(
    name: str, value: str, message: str
) -> None:
    with pytest.raises(PostmarkConfigurationError, match=message) as refused:
        load_postmark_settings(COMPLETE_SETTINGS | {name: value})

    assert value not in str(refused.value)


def test_a_local_app_url_may_use_http() -> None:
    settings = load_postmark_settings(
        COMPLETE_SETTINGS | {"POLICYENGINE_APP_URL": "http://localhost:5173"}
    )

    assert settings is not None
    assert settings.app_url == "http://localhost:5173"


def test_a_template_email_is_posted_once_on_the_transactional_stream() -> None:
    sender, requests, waits = _sender(
        [httpx.Response(200, json={"ErrorCode": 0, "Message": "OK"})]
    )

    _send(sender)

    (request,) = requests
    assert str(request.url) == POSTMARK_TEMPLATE_URL
    assert request.method == "POST"
    assert request.headers["X-Postmark-Server-Token"] == "server-token"
    assert request.headers["Accept"] == "application/json"
    assert json.loads(request.content) == {
        "From": SENDER,
        "To": "ada@example.org",
        "TemplateAlias": "user-type-changed",
        "TemplateModel": {"user_type": "author"},
        "MessageStream": "outbound",
    }
    assert waits == []
    assert sender.app_url == APP_URL


def test_the_token_is_read_from_its_secret_manager_resource() -> None:
    sender, requests, _waits = _sender(
        [httpx.Response(200, json={"ErrorCode": 0})],
        server_token="",
        server_token_resource=SECRET_RESOURCE,
    )

    _send(sender)

    assert requests[0].headers["X-Postmark-Server-Token"] == "loaded-token"


def test_an_unreadable_token_fails_without_a_request() -> None:
    def refuse(_resource: str) -> str:
        msg = "permission denied"
        raise RuntimeError(msg)

    requests: list[httpx.Request] = []
    sender = PostmarkEmailSender(
        PostmarkSettings(
            sender_address=SENDER,
            app_url=APP_URL,
            server_token_resource=SECRET_RESOURCE,
        ),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200)
            )
        ),
        secret_loader=refuse,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(EmailSendError) as failed:
        _send(sender)

    assert failed.value.cause == "secret_unavailable"
    assert requests == []


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(503),
        httpx.Response(429),
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
)
def test_a_retryable_failure_is_retried_after_short_waits(
    failure: httpx.Response | Exception,
) -> None:
    sender, requests, waits = _sender(
        [failure, failure, httpx.Response(200, json={"ErrorCode": 0})]
    )

    _send(sender)

    assert len(requests) == SEND_ATTEMPTS
    assert waits == [0.5, 1.0]


@pytest.mark.parametrize(
    ("failure", "cause"),
    [
        (httpx.Response(500), "http_500"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connection_error"),
    ],
)
def test_a_send_failing_every_attempt_names_its_last_cause(
    failure: httpx.Response | Exception, cause: str
) -> None:
    sender, requests, waits = _sender([failure] * SEND_ATTEMPTS)

    with pytest.raises(EmailSendError) as failed:
        _send(sender)

    assert failed.value.cause == cause
    assert str(failed.value) == f"Postmark did not accept the email: {cause}"
    assert len(requests) == SEND_ATTEMPTS
    assert waits == [0.5, 1.0]


@pytest.mark.parametrize(
    ("response", "cause"),
    [
        (
            httpx.Response(401, json={"ErrorCode": 10, "Message": "Bad token"}),
            "http_401",
        ),
        # Postmark answers 422 with its own error code, such as 406 for an
        # address it suppresses after a bounce or spam complaint.
        (
            httpx.Response(
                422, json={"ErrorCode": 406, "Message": "ada@example.org inactive"}
            ),
            "postmark_406",
        ),
        (httpx.Response(422, text="not json"), "http_422"),
        (
            httpx.Response(200, json={"ErrorCode": 300, "Message": "Invalid"}),
            "postmark_300",
        ),
    ],
)
def test_a_refused_email_is_not_retried_and_names_no_address(
    response: httpx.Response, cause: str
) -> None:
    sender, requests, waits = _sender([response])

    with pytest.raises(EmailSendError) as failed:
        _send(sender)

    assert failed.value.cause == cause
    assert "ada@example.org" not in str(failed.value)
    assert len(requests) == 1
    assert waits == []


def test_build_returns_a_sender_for_complete_settings() -> None:
    sender = build_postmark_email_sender(COMPLETE_SETTINGS)

    assert isinstance(sender, PostmarkEmailSender)
    assert sender.app_url == APP_URL
