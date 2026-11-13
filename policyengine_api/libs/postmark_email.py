"""Optional email through Postmark's HTTP API, for invitations and type changes.

The Public API sends only template emails: ``POST /email/withTemplate`` with a
template alias and the data the template fills in, on the default
transactional message stream. Postmark keeps the templates, their layout and
HTML, delivery to the recipient's mail server, DKIM signing, suppression of
addresses that bounced or complained, and the activity log, so none of that
is done here.

One settings group configures it, all or none:

- the server token, from exactly one source: ``POSTMARK_SERVER_TOKEN``, the
  token itself, for local use, or ``POSTMARK_SERVER_TOKEN_SECRET_RESOURCE``,
  the Secret Manager version that holds it, as deployments set it;
- ``POSTMARK_SENDER_ADDRESS``, the From address, which may carry a display
  name (``PolicyEngine <no-reply@policyengine.org>``);
- ``POLICYENGINE_APP_URL``, the app's address the emails link to.

Without them nothing is sent, and callers record that. This module never
logs, or puts in an error message, an email address, the token or a template
model.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from functools import cache
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

POSTMARK_SERVER_TOKEN_ENV = "POSTMARK_SERVER_TOKEN"  # noqa: S105  # an environment variable name, not a secret
POSTMARK_SERVER_TOKEN_SECRET_RESOURCE_ENV = "POSTMARK_SERVER_TOKEN_SECRET_RESOURCE"  # noqa: S105  # an environment variable name, not a secret
POSTMARK_SENDER_ADDRESS_ENV = "POSTMARK_SENDER_ADDRESS"
POLICYENGINE_APP_URL_ENV = "POLICYENGINE_APP_URL"
POSTMARK_ENV_VARS = (
    POSTMARK_SERVER_TOKEN_ENV,
    POSTMARK_SERVER_TOKEN_SECRET_RESOURCE_ENV,
    POSTMARK_SENDER_ADDRESS_ENV,
    POLICYENGINE_APP_URL_ENV,
)
POSTMARK_TEMPLATE_URL = "https://api.postmarkapp.com/email/withTemplate"
# The statuses whose answer names Postmark's own error code for the email.
POSTMARK_REFUSAL_STATUSES = frozenset({HTTPStatus.OK, HTTPStatus.UNPROCESSABLE_ENTITY})
# Postmark's default transactional message stream.
MESSAGE_STREAM = "outbound"
HTTP_TIMEOUT_SECONDS = 5.0
# A failed request is tried this many times in all, waiting before each retry.
SEND_ATTEMPTS = 3
RETRY_WAIT_SECONDS = (0.5, 1.0)
SECRET_RESOURCE_PATTERN = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")
MAXIMUM_SENDER_LENGTH = 320
# One address, optionally after a display name, with no line breaks: Postmark
# reads the From field as one header value.
SENDER_PATTERN = re.compile(r"^[^\r\n]*?<?[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+>?$")
LOCAL_APP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class PostmarkConfigurationError(RuntimeError):
    """Raised when the optional Postmark settings are incomplete or invalid."""


class EmailSendError(RuntimeError):
    """Raised when Postmark did not accept an email after every attempt.

    ``cause`` says why, with no personal data: ``http_<status>``,
    ``postmark_<ErrorCode>`` for an email Postmark refused with its own
    error code (406 is a suppressed address), ``timeout``,
    ``connection_error`` or ``secret_unavailable``.
    """

    def __init__(self, cause: str) -> None:
        """Keep ``cause``, which also forms the message."""
        super().__init__(f"Postmark did not accept the email: {cause}")
        self.cause = cause


@dataclass(frozen=True)
class PostmarkSettings:
    """Validated Postmark settings.

    Exactly one of ``server_token`` and ``server_token_resource`` (a Secret
    Manager version name) is set; the token is kept out of ``repr``.
    ``app_url`` has no trailing slash.
    """

    sender_address: str
    app_url: str
    server_token: str = field(default="", repr=False)
    server_token_resource: str = ""


def _app_url(value: str) -> str:
    """Return the app's address without a trailing slash, or raise."""
    parts = urlsplit(value)
    local = parts.scheme == "http" and parts.hostname in LOCAL_APP_HOSTS
    if not parts.netloc or not (parts.scheme == "https" or local):
        msg = (
            f"{POLICYENGINE_APP_URL_ENV} must be an https address (http only "
            "for localhost)"
        )
        raise PostmarkConfigurationError(msg)
    if parts.query or parts.fragment or value.endswith(("?", "#")):
        msg = f"{POLICYENGINE_APP_URL_ENV} must have no query or fragment"
        raise PostmarkConfigurationError(msg)
    return value.rstrip("/")


def load_postmark_settings(
    environ: Mapping[str, str] | None = None,
) -> PostmarkSettings | None:
    """Return complete Postmark settings, or ``None`` when none are set."""
    values = os.environ if environ is None else environ
    token = values.get(POSTMARK_SERVER_TOKEN_ENV, "").strip()
    token_resource = values.get(POSTMARK_SERVER_TOKEN_SECRET_RESOURCE_ENV, "").strip()
    sender = values.get(POSTMARK_SENDER_ADDRESS_ENV, "").strip()
    app_url = values.get(POLICYENGINE_APP_URL_ENV, "").strip()
    if not any((token, token_resource, sender, app_url)):
        return None
    if token and token_resource:
        msg = (
            f"Set exactly one of {POSTMARK_SERVER_TOKEN_ENV} or "
            f"{POSTMARK_SERVER_TOKEN_SECRET_RESOURCE_ENV}"
        )
        raise PostmarkConfigurationError(msg)
    if not (token or token_resource) or not sender or not app_url:
        msg = (
            "Postmark email is partially configured: set "
            f"{POSTMARK_SENDER_ADDRESS_ENV}, {POLICYENGINE_APP_URL_ENV}, and "
            "exactly one server-token source"
        )
        raise PostmarkConfigurationError(msg)
    if token_resource and SECRET_RESOURCE_PATTERN.fullmatch(token_resource) is None:
        msg = f"{POSTMARK_SERVER_TOKEN_SECRET_RESOURCE_ENV} is invalid"
        raise PostmarkConfigurationError(msg)
    if len(sender) > MAXIMUM_SENDER_LENGTH or SENDER_PATTERN.fullmatch(sender) is None:
        msg = f"{POSTMARK_SENDER_ADDRESS_ENV} must be an email address"
        raise PostmarkConfigurationError(msg)
    return PostmarkSettings(
        sender_address=sender,
        app_url=_app_url(app_url),
        server_token=token,
        server_token_resource=token_resource,
    )


@cache
def _load_secret_from_secret_manager(resource_name: str) -> str:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource_name})
    return response.payload.data.decode("utf-8")


def _postmark_error_code(response: httpx.Response) -> int | None:
    """Return the answer's Postmark ``ErrorCode``, or None when it has none."""
    try:
        answer = response.json()
    except ValueError:
        return None
    if not isinstance(answer, dict):
        return None
    error_code = answer.get("ErrorCode")
    if isinstance(error_code, bool) or not isinstance(error_code, int):
        return None
    return error_code


def _retryable(response: httpx.Response) -> bool:
    """Say whether Postmark may accept the same request later."""
    return (
        response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        or response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
    )


class PostmarkEmailSender:
    """Send template emails through Postmark, retrying a failed request."""

    def __init__(
        self,
        settings: PostmarkSettings,
        *,
        http_client: httpx.Client | None = None,
        secret_loader: Callable[[str], str] = _load_secret_from_secret_manager,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Use ``settings``; tests pass a mock ``http_client`` and ``sleep``.

        ``secret_loader`` reads ``server_token_resource`` when no token is
        set directly.
        """
        self._settings = settings
        self._http_client = http_client
        self._secret_loader = secret_loader
        self._sleep = sleep

    @property
    def app_url(self) -> str:
        """Return the app's address that emails link to, without a trailing slash."""
        return self._settings.app_url

    def _server_token(self) -> str:
        if self._settings.server_token:
            return self._settings.server_token
        cause = "secret_unavailable"
        try:
            token = self._secret_loader(self._settings.server_token_resource).strip()
        except Exception as error:
            raise EmailSendError(cause) from error
        if not token:
            raise EmailSendError(cause)
        return token

    def _post(self, http_client: httpx.Client, request: httpx.Request) -> str | None:
        """Send one attempt; return None when accepted, else its failure cause.

        Raise EmailSendError for an answer that a retry wouldn't change.
        """
        try:
            response = http_client.send(request)
        except httpx.TimeoutException:
            return "timeout"
        except httpx.HTTPError:
            return "connection_error"
        error_code = _postmark_error_code(response)
        if response.status_code == HTTPStatus.OK and not error_code:
            return None
        if _retryable(response):
            return f"http_{response.status_code}"
        # Postmark refuses an email it can't send, such as one to a
        # suppressed address, with 422 and its own error code.
        if error_code and response.status_code in POSTMARK_REFUSAL_STATUSES:
            cause = f"postmark_{error_code}"
        else:
            cause = f"http_{response.status_code}"
        raise EmailSendError(cause)

    def send_template(
        self,
        *,
        to: str,
        template_alias: str,
        template_model: Mapping[str, object],
    ) -> None:
        """Send the template ``template_alias`` filled with ``template_model``.

        A timeout, a connection error, HTTP 429 or a server error is tried
        again, up to three attempts in all, after waits of 0.5 and 1 second;
        a retried timeout may send the email twice. Raise EmailSendError,
        with its cause, when Postmark refuses the email or every attempt
        fails.
        """
        request_body = {
            "From": self._settings.sender_address,
            "To": to,
            "TemplateAlias": template_alias,
            "TemplateModel": dict(template_model),
            "MessageStream": MESSAGE_STREAM,
        }
        headers = {
            "Accept": "application/json",
            "X-Postmark-Server-Token": self._server_token(),
        }
        if self._http_client is not None:
            self._send_with_retries(self._http_client, request_body, headers)
            return
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http_client:
            self._send_with_retries(http_client, request_body, headers)

    def _send_with_retries(
        self,
        http_client: httpx.Client,
        request_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> None:
        cause = "unknown"
        for attempt in range(SEND_ATTEMPTS):
            if attempt:
                self._sleep(RETRY_WAIT_SECONDS[attempt - 1])
            request = http_client.build_request(
                "POST", POSTMARK_TEMPLATE_URL, json=request_body, headers=headers
            )
            failure = self._post(http_client, request)
            if failure is None:
                return
            cause = failure
        raise EmailSendError(cause)


def build_postmark_email_sender(
    environ: Mapping[str, str] | None = None,
) -> PostmarkEmailSender | None:
    """Return a sender for the configured Postmark server, or ``None``.

    Settings are read on each call; invalid ones raise
    PostmarkConfigurationError.
    """
    settings = load_postmark_settings(environ)
    if settings is None:
        return None
    return PostmarkEmailSender(settings)
