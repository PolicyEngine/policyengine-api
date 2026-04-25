"""Unit tests for :mod:`policyengine_api.libs.gateway_auth`."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from policyengine_api.libs.gateway_auth import (
    GATEWAY_AUTH_CLIENT_SECRET_ENV,
    GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV,
    GATEWAY_AUTH_CORE_ENV_VARS,
    GATEWAY_AUTH_ENV_VARS,
    GATEWAY_AUTH_REQUIRED_ENV,
    GatewayAuthError,
    GatewayAuthTokenProvider,
    GatewayBearerAuth,
    _require_all_or_none_gateway_auth_env,
    gateway_auth_required,
)


ISSUER = "https://policyengine.uk.auth0.com"
AUDIENCE = "https://sim-gateway.policyengine.org"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
CLIENT_SECRET_RESOURCE = (
    "projects/policyengine-api/secrets/gateway-auth-client-secret/versions/1"
)


@pytest.fixture(autouse=True)
def clear_gateway_auth_env(monkeypatch):
    """Isolate unit tests from any gateway-auth env baked into the build image."""
    for key in (*GATEWAY_AUTH_ENV_VARS, GATEWAY_AUTH_REQUIRED_ENV):
        monkeypatch.delenv(key, raising=False)


def _make_token_response(token: str, expires_in: int = 86400) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "access_token": token,
        "expires_in": expires_in,
        "token_type": "Bearer",
    }
    return response


class TestGatewayAuthTokenProvider:
    class TestConfigured:
        def test__given_all_kwargs__then_configured_true(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            assert provider.configured is True

        def test__given_missing_client_secret__then_configured_false(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret="",
            )

            assert provider.configured is False

        def test__given_secret_resource__then_configured_true(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret_resource=CLIENT_SECRET_RESOURCE,
            )

            assert provider.configured is True

    class TestGetToken:
        def test__given_unconfigured_provider__then_raises(self):
            provider = GatewayAuthTokenProvider(
                issuer="", audience="", client_id="", client_secret=""
            )

            with pytest.raises(GatewayAuthError):
                provider.get_token()

        def test__given_first_call__then_fetches_and_returns_token(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=_make_token_response("tok-1"),
            ) as mock_post:
                token = provider.get_token()

            assert token == "tok-1"
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["json"]["grant_type"] == "client_credentials"
            assert call_kwargs["json"]["client_id"] == CLIENT_ID
            assert call_kwargs["json"]["client_secret"] == CLIENT_SECRET
            assert call_kwargs["json"]["audience"] == AUDIENCE
            assert call_kwargs["timeout"] == 10.0
            assert mock_post.call_args.args[0] == f"{ISSUER}/oauth/token"

        def test__given_secret_manager_resource__then_loads_secret_once(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret_resource=CLIENT_SECRET_RESOURCE,
            )

            with (
                patch(
                    "policyengine_api.libs.gateway_auth._load_secret_from_secret_manager",
                    return_value=CLIENT_SECRET,
                ) as mock_load,
                patch(
                    "policyengine_api.libs.gateway_auth.httpx.post",
                    return_value=_make_token_response("tok-1"),
                ) as mock_post,
            ):
                first = provider.get_token()
                second = provider.get_token()

            assert first == second == "tok-1"
            mock_load.assert_called_once_with(CLIENT_SECRET_RESOURCE)
            assert mock_post.call_args.kwargs["json"]["client_secret"] == CLIENT_SECRET

        def test__given_secret_manager_failure__then_raises(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret_resource=CLIENT_SECRET_RESOURCE,
            )

            with patch(
                "policyengine_api.libs.gateway_auth._load_secret_from_secret_manager",
                side_effect=RuntimeError("no access"),
            ):
                with pytest.raises(
                    GatewayAuthError,
                    match="Failed to load gateway auth client secret",
                ):
                    provider.get_token()

        def test__given_trailing_slash_issuer__then_no_double_slash(self):
            provider = GatewayAuthTokenProvider(
                issuer=f"{ISSUER}/",
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=_make_token_response("tok-1"),
            ) as mock_post:
                provider.get_token()

            assert mock_post.call_args.args[0] == f"{ISSUER}/oauth/token"

        def test__given_fresh_cached_token__then_second_call_reuses(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=_make_token_response("tok-1"),
            ) as mock_post:
                first = provider.get_token()
                second = provider.get_token()

            assert first == second == "tok-1"
            mock_post.assert_called_once()

        def test__given_expired_token__then_second_call_refreshes(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            responses = [
                _make_token_response("tok-1", expires_in=120),
                _make_token_response("tok-2", expires_in=86400),
            ]
            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                side_effect=responses,
            ) as mock_post:
                first = provider.get_token()
                provider._expires_at = time.time() - 1
                second = provider.get_token()

            assert first == "tok-1"
            assert second == "tok-2"
            assert mock_post.call_count == 2

        def test__given_network_error__then_raises_gateway_auth_error(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                side_effect=httpx.ConnectError("boom"),
            ):
                with pytest.raises(GatewayAuthError):
                    provider.get_token()

        def test__given_response_without_access_token__then_raises(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )
            response = MagicMock()
            response.status_code = 200
            response.raise_for_status = MagicMock()
            response.json.return_value = {"token_type": "Bearer", "expires_in": 3600}

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=response,
            ):
                with pytest.raises(GatewayAuthError):
                    provider.get_token()

        def test__given_missing_expires_in__then_raises(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )
            response = MagicMock()
            response.status_code = 200
            response.raise_for_status = MagicMock()
            response.json.return_value = {"access_token": "tok"}

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=response,
            ):
                with pytest.raises(GatewayAuthError):
                    provider.get_token()

        def test__given_zero_expires_in__then_clamped_to_refresh_margin(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=_make_token_response("tok", expires_in=0),
            ):
                provider.get_token()

            ttl = provider._expires_at - time.time()
            assert ttl > provider._REFRESH_MARGIN_SECONDS

        def test__given_concurrent_callers__then_fetches_once(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            def slow_response(*_args, **_kwargs):
                time.sleep(0.05)
                return _make_token_response("tok-concurrent")

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                side_effect=slow_response,
            ) as mock_post:
                tokens: list[str] = []
                threads = [
                    threading.Thread(target=lambda: tokens.append(provider.get_token()))
                    for _ in range(20)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            assert mock_post.call_count == 1
            assert tokens == ["tok-concurrent"] * 20

    class TestInvalidate:
        def test__given_invalidated_token__then_next_call_refetches(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            responses = [
                _make_token_response("tok-1"),
                _make_token_response("tok-2"),
            ]
            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                side_effect=responses,
            ) as mock_post:
                provider.get_token()
                provider.invalidate()
                provider.get_token()

            assert mock_post.call_count == 2


class TestRequireAllOrNoneGatewayAuthEnv:
    def test__given_no_env__then_ok(self, monkeypatch):
        for name in GATEWAY_AUTH_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

        _require_all_or_none_gateway_auth_env()

    def test__given_all_env__then_ok(self, monkeypatch):
        for name in GATEWAY_AUTH_CORE_ENV_VARS:
            monkeypatch.setenv(name, "x")
        monkeypatch.setenv(GATEWAY_AUTH_CLIENT_SECRET_ENV, "x")

        _require_all_or_none_gateway_auth_env()

    def test__given_core_env_plus_secret_resource__then_ok(self, monkeypatch):
        for name in GATEWAY_AUTH_CORE_ENV_VARS:
            monkeypatch.setenv(name, "x")
        monkeypatch.setenv(GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV, "x")

        _require_all_or_none_gateway_auth_env()

    def test__given_partial_env__then_raises(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://tenant.auth0.com")
        monkeypatch.setenv("GATEWAY_AUTH_AUDIENCE", "aud")
        monkeypatch.delenv("GATEWAY_AUTH_CLIENT_ID", raising=False)
        monkeypatch.delenv(GATEWAY_AUTH_CLIENT_SECRET_ENV, raising=False)
        monkeypatch.delenv(GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV, raising=False)

        with pytest.raises(GatewayAuthError):
            _require_all_or_none_gateway_auth_env()

    def test__given_both_secret_sources__then_raises(self, monkeypatch):
        for name in GATEWAY_AUTH_CORE_ENV_VARS:
            monkeypatch.setenv(name, "x")
        monkeypatch.setenv(GATEWAY_AUTH_CLIENT_SECRET_ENV, "secret")
        monkeypatch.setenv(GATEWAY_AUTH_CLIENT_SECRET_RESOURCE_ENV, "resource")

        with pytest.raises(GatewayAuthError, match="ambiguously configured"):
            _require_all_or_none_gateway_auth_env()


class TestGatewayAuthRequired:
    def test__given_env_unset__then_false(self, monkeypatch):
        monkeypatch.delenv(GATEWAY_AUTH_REQUIRED_ENV, raising=False)

        assert gateway_auth_required() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test__given_truthy_value__then_true(self, monkeypatch, value):
        monkeypatch.setenv(GATEWAY_AUTH_REQUIRED_ENV, value)

        assert gateway_auth_required() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test__given_falsey_value__then_false(self, monkeypatch, value):
        monkeypatch.setenv(GATEWAY_AUTH_REQUIRED_ENV, value)

        assert gateway_auth_required() is False


class TestGatewayBearerAuth:
    def test__given_request__then_attaches_bearer_token_header(self):
        provider = MagicMock()
        provider.get_token.return_value = "tok-xyz"
        auth = GatewayBearerAuth(provider)

        request = httpx.Request("GET", "https://example.invalid/")
        flow = auth.auth_flow(request)
        next(flow)

        assert request.headers["Authorization"] == "Bearer tok-xyz"
        provider.get_token.assert_called_once()

    def test__given_401_response__then_invalidates_and_retries_with_fresh_token(self):
        provider = MagicMock()
        provider.get_token.side_effect = ["stale-token", "fresh-token"]
        auth = GatewayBearerAuth(provider)

        request = httpx.Request("GET", "https://example.invalid/jobs/abc")
        flow = auth.auth_flow(request)

        first_request = next(flow)
        assert first_request.headers["Authorization"] == "Bearer stale-token"

        unauthorized = httpx.Response(401, request=first_request)
        retry_request = flow.send(unauthorized)

        assert retry_request.headers["Authorization"] == "Bearer fresh-token"
        provider.invalidate.assert_called_once()
        with pytest.raises(StopIteration):
            flow.send(httpx.Response(200, request=retry_request))

    def test__given_2xx_response__then_no_retry(self):
        provider = MagicMock()
        provider.get_token.return_value = "tok"
        auth = GatewayBearerAuth(provider)

        request = httpx.Request("GET", "https://example.invalid/jobs/abc")
        flow = auth.auth_flow(request)

        next(flow)
        with pytest.raises(StopIteration):
            flow.send(httpx.Response(200, request=request))

        provider.invalidate.assert_not_called()
