"""Unit tests for :mod:`policyengine_api.libs.gateway_auth`."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from policyengine_api.libs.gateway_auth import (
    GatewayAuthError,
    GatewayAuthTokenProvider,
    GatewayBearerAuth,
)


ISSUER = "https://policyengine.uk.auth0.com"
AUDIENCE = "https://sim-gateway.policyengine.org"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"


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

        def test__given_empty_env__then_configured_false(self):
            with patch.dict(
                "os.environ",
                {
                    "GATEWAY_AUTH_ISSUER": "",
                    "GATEWAY_AUTH_AUDIENCE": "",
                    "GATEWAY_AUTH_CLIENT_ID": "",
                    "GATEWAY_AUTH_CLIENT_SECRET": "",
                },
                clear=False,
            ):
                provider = GatewayAuthTokenProvider()

                assert provider.configured is False

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
            positional_url = mock_post.call_args.args[0]
            assert positional_url == f"{ISSUER}/oauth/token"

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

            url = mock_post.call_args.args[0]
            assert url == f"{ISSUER}/oauth/token"

        def test__given_fresh_cached_token__then_second_call_reuses(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=_make_token_response("tok-1", expires_in=86400),
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
                _make_token_response("tok-1", expires_in=60),
                _make_token_response("tok-2", expires_in=86400),
            ]
            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                side_effect=responses,
            ) as mock_post:
                first = provider.get_token()
                # Simulate wall-clock advancing past the refresh margin.
                provider._expires_at = time.time() - 1
                second = provider.get_token()

            assert first == "tok-1"
            assert second == "tok-2"
            assert mock_post.call_count == 2

        def test__given_auth0_http_error__then_raises_gateway_auth_error(self):
            provider = GatewayAuthTokenProvider(
                issuer=ISSUER,
                audience=AUDIENCE,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )

            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "unauthorized",
                request=MagicMock(),
                response=mock_response,
            )

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=mock_response,
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
            response.json.return_value = {"token_type": "Bearer"}

            with patch(
                "policyengine_api.libs.gateway_auth.httpx.post",
                return_value=response,
            ):
                with pytest.raises(GatewayAuthError):
                    provider.get_token()

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


class TestGatewayBearerAuth:
    def test__given_request__then_attaches_bearer_token_header(self):
        provider = MagicMock()
        provider.get_token.return_value = "tok-xyz"
        auth = GatewayBearerAuth(provider)

        request = httpx.Request("GET", "https://example.invalid/")
        list(auth.auth_flow(request))

        assert request.headers["Authorization"] == "Bearer tok-xyz"
        provider.get_token.assert_called_once()
