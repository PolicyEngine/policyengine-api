"""Unit tests for :mod:`policyengine_api.libs.auth0_management`."""

from __future__ import annotations

import httpx
import pytest

from policyengine_api.libs.auth0_management import (
    Auth0ManagementClient,
    Auth0ManagementConfigurationError,
    Auth0ManagementError,
    Auth0ManagementSettings,
    Auth0UserIdSearch,
    Auth0UserProfile,
    Auth0UserProfilesUnavailableError,
    build_auth0_user_deleter,
    build_auth0_user_profile_reader,
    load_auth0_management_settings,
    load_auth0_user_profile_settings,
)

DOMAIN = "policyengine.us.auth0.com"
SECRET_RESOURCE = "projects/p/secrets/auth0-management/versions/latest"


def _client(handler, **settings) -> tuple[Auth0ManagementClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    values = {"domain": DOMAIN, "client_id": "m2m", "client_secret": "raw-secret"}
    values.update(settings)
    return (
        Auth0ManagementClient(
            Auth0ManagementSettings(**values),
            http_client=httpx.Client(transport=httpx.MockTransport(record)),
            secret_loader=lambda _resource: "loaded-secret",
        ),
        requests,
    )


def _token_then(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200, json={"access_token": "mgmt", "expires_in": 3600}
            )
        return httpx.Response(status)

    return handler


def test_settings_are_optional_and_all_or_none() -> None:
    assert load_auth0_management_settings({}) is None
    assert build_auth0_user_deleter({}) is None
    with pytest.raises(Auth0ManagementConfigurationError, match="partially"):
        load_auth0_management_settings({"AUTH0_MANAGEMENT_DOMAIN": DOMAIN})
    with pytest.raises(Auth0ManagementConfigurationError, match="exactly one"):
        load_auth0_management_settings(
            {
                "AUTH0_MANAGEMENT_DOMAIN": DOMAIN,
                "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
                "AUTH0_MANAGEMENT_CLIENT_SECRET": "raw",
                "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
            }
        )
    with pytest.raises(Auth0ManagementConfigurationError, match="bare host"):
        load_auth0_management_settings(
            {
                "AUTH0_MANAGEMENT_DOMAIN": f"https://{DOMAIN}/",
                "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
                "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
            }
        )
    settings = load_auth0_management_settings(
        {
            "AUTH0_MANAGEMENT_DOMAIN": DOMAIN,
            "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
            "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
        }
    )
    assert settings is not None
    assert "raw" not in repr(settings)


@pytest.mark.parametrize("status", [204, 404])
def test_delete_user_uses_an_encoded_subject_and_tolerates_absent_users(
    status: int,
) -> None:
    client, requests = _client(_token_then(status))

    client.delete_user("google-oauth2|1234")

    token_request, delete_request = requests
    assert token_request.url == f"https://{DOMAIN}/oauth/token"
    assert b'"audience":"https://policyengine.us.auth0.com/api/v2/"' in (
        token_request.content.replace(b" ", b"")
    )
    assert delete_request.method == "DELETE"
    assert delete_request.url.raw_path == b"/api/v2/users/google-oauth2%7C1234"
    assert delete_request.headers["authorization"] == "Bearer mgmt"


def test_token_is_cached_and_secret_resources_are_loaded() -> None:
    client, requests = _client(
        _token_then(204), client_secret="", client_secret_resource=SECRET_RESOURCE
    )

    client.delete_user("auth0|1")
    client.delete_user("auth0|2")

    assert [request.url.raw_path for request in requests] == [
        b"/oauth/token",
        b"/api/v2/users/auth0%7C1",
        b"/api/v2/users/auth0%7C2",
    ]
    assert b"loaded-secret" in requests[0].content


@pytest.mark.parametrize("status", [401, 403, 500])
def test_failed_deletions_raise_without_leaking_subjects(status: int) -> None:
    client, _requests = _client(_token_then(status))

    with pytest.raises(Auth0ManagementError) as error:
        client.delete_user("google-oauth2|secret-subject")

    assert "secret-subject" not in str(error.value)


def test_deleters_share_one_client_and_its_token(monkeypatch) -> None:
    from policyengine_api.libs import auth0_management

    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _token_then(204)(request)

    mock_client = httpx.Client
    monkeypatch.setattr(
        auth0_management.httpx,
        "Client",
        lambda **kwargs: mock_client(transport=httpx.MockTransport(record), **kwargs),
    )
    monkeypatch.setattr(auth0_management, "_shared_clients", {})
    environ = {
        "AUTH0_MANAGEMENT_DOMAIN": DOMAIN,
        "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
        "AUTH0_MANAGEMENT_CLIENT_SECRET": "raw-secret",
    }

    first = build_auth0_user_deleter(environ)
    second = build_auth0_user_deleter(environ)
    assert first is not None
    assert second is not None
    first.delete_user("auth0|1")
    second.delete_user("auth0|2")

    assert first is second
    assert [request.url.raw_path for request in requests] == [
        b"/oauth/token",
        b"/api/v2/users/auth0%7C1",
        b"/api/v2/users/auth0%7C2",
    ]


def _tokens_then(delete_statuses: list[int]):
    """Issue numbered tokens and answer deletions with the given statuses."""
    issued_tokens: list[str] = []
    remaining_statuses = list(delete_statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            issued_tokens.append(f"mgmt-{len(issued_tokens) + 1}")
            return httpx.Response(
                200, json={"access_token": issued_tokens[-1], "expires_in": 86400}
            )
        return httpx.Response(remaining_statuses.pop(0))

    return handler


def test_a_rejected_token_is_dropped_and_the_deletion_retried_once() -> None:
    client, requests = _client(_tokens_then([401, 204]))

    client.delete_user("auth0|1")

    assert [request.url.raw_path for request in requests] == [
        b"/oauth/token",
        b"/api/v2/users/auth0%7C1",
        b"/oauth/token",
        b"/api/v2/users/auth0%7C1",
    ]
    assert requests[1].headers["authorization"] == "Bearer mgmt-1"
    assert requests[3].headers["authorization"] == "Bearer mgmt-2"


def test_a_second_rejection_fails_without_further_retries() -> None:
    client, requests = _client(_tokens_then([401, 401]))

    with pytest.raises(Auth0ManagementError, match="HTTP 401"):
        client.delete_user("auth0|1")

    assert len(requests) == 4


def test_prepare_deletion_loads_the_secret_and_fetches_a_token() -> None:
    client, requests = _client(
        _tokens_then([204]), client_secret="", client_secret_resource=SECRET_RESOURCE
    )

    client.prepare_deletion()
    client.delete_user("auth0|1")

    assert [request.url.raw_path for request in requests] == [
        b"/oauth/token",
        b"/api/v2/users/auth0%7C1",
    ]


def test_prepare_deletion_fails_when_the_secret_cannot_be_read() -> None:
    def unreadable(_resource: str) -> str:
        msg = "secretmanager.versions.access denied"
        raise PermissionError(msg)

    requests: list[httpx.Request] = []
    client = Auth0ManagementClient(
        Auth0ManagementSettings(
            domain=DOMAIN, client_id="m2m", client_secret_resource=SECRET_RESOURCE
        ),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(500)
            )
        ),
        secret_loader=unreadable,
    )

    with pytest.raises(Auth0ManagementError, match="could not be loaded"):
        client.prepare_deletion()
    assert requests == []


PROFILE_ENVIRONMENT = {
    "AUTH0_USER_PROFILES_DOMAIN": DOMAIN,
    "AUTH0_USER_PROFILES_CLIENT_ID": "profile-reader",
    "AUTH0_USER_PROFILES_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
}
PROFILE_FIELDS = "user_id,email,email_verified,given_name,family_name,name"


def test_user_profile_settings_are_optional_all_or_none_and_validated() -> None:
    assert load_auth0_user_profile_settings({}) is None
    assert build_auth0_user_profile_reader({}) is None
    # The deletion settings never configure profile reads, or the reverse.
    assert (
        load_auth0_user_profile_settings(
            {
                "AUTH0_MANAGEMENT_DOMAIN": DOMAIN,
                "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
                "AUTH0_MANAGEMENT_CLIENT_SECRET": "raw",
            }
        )
        is None
    )
    assert load_auth0_management_settings(PROFILE_ENVIRONMENT) is None
    with pytest.raises(
        Auth0ManagementConfigurationError, match="profile reads are partially"
    ):
        load_auth0_user_profile_settings({"AUTH0_USER_PROFILES_DOMAIN": DOMAIN})
    with pytest.raises(
        Auth0ManagementConfigurationError,
        match="AUTH0_USER_PROFILES_CLIENT_SECRET or "
        "AUTH0_USER_PROFILES_CLIENT_SECRET_RESOURCE",
    ):
        load_auth0_user_profile_settings(
            {**PROFILE_ENVIRONMENT, "AUTH0_USER_PROFILES_CLIENT_SECRET": "raw"}
        )
    with pytest.raises(
        Auth0ManagementConfigurationError,
        match="AUTH0_USER_PROFILES_DOMAIN must be a bare host name",
    ):
        load_auth0_user_profile_settings(
            {**PROFILE_ENVIRONMENT, "AUTH0_USER_PROFILES_DOMAIN": f"https://{DOMAIN}/"}
        )
    with pytest.raises(
        Auth0ManagementConfigurationError,
        match="AUTH0_USER_PROFILES_CLIENT_SECRET_RESOURCE is invalid",
    ):
        load_auth0_user_profile_settings(
            {
                **PROFILE_ENVIRONMENT,
                "AUTH0_USER_PROFILES_CLIENT_SECRET_RESOURCE": "auth0-profiles",
            }
        )
    from_resource = load_auth0_user_profile_settings(PROFILE_ENVIRONMENT)
    direct = load_auth0_user_profile_settings(
        {
            "AUTH0_USER_PROFILES_DOMAIN": DOMAIN,
            "AUTH0_USER_PROFILES_CLIENT_ID": "profile-reader",
            "AUTH0_USER_PROFILES_CLIENT_SECRET": "raw-profile-secret",
        }
    )

    assert from_resource == Auth0ManagementSettings(
        domain=DOMAIN,
        client_id="profile-reader",
        client_secret_resource=SECRET_RESOURCE,
    )
    assert direct is not None
    assert direct.client_secret == "raw-profile-secret"
    assert "raw-profile-secret" not in repr(direct)


def test_profile_readers_share_one_client_and_its_token(monkeypatch) -> None:
    from policyengine_api.libs import auth0_management

    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200, json={"access_token": "mgmt", "expires_in": 3600}
            )
        return httpx.Response(200, json=[])

    mock_client = httpx.Client
    monkeypatch.setattr(
        auth0_management.httpx,
        "Client",
        lambda **kwargs: mock_client(transport=httpx.MockTransport(record), **kwargs),
    )
    monkeypatch.setattr(auth0_management, "_shared_clients", {})
    environment = {
        "AUTH0_USER_PROFILES_DOMAIN": DOMAIN,
        "AUTH0_USER_PROFILES_CLIENT_ID": "profile-reader",
        "AUTH0_USER_PROFILES_CLIENT_SECRET": "raw-profile-secret",
    }

    first = build_auth0_user_profile_reader(environment)
    second = build_auth0_user_profile_reader(environment)
    assert first is not None
    assert second is not None
    first.read_user_profiles(["auth0|1"])
    second.read_user_profiles(["auth0|2"])

    assert first is second
    assert isinstance(first, Auth0ManagementClient)
    assert [request.url.path for request in requests] == [
        "/oauth/token",
        "/api/v2/users",
        "/api/v2/users",
    ]
    assert b"profile-reader" in requests[0].content


def _profile_payload(user_id: str, **fields: object) -> dict[str, object]:
    return {"user_id": user_id, **fields}


def _token_then_users(answer_users):
    """Issue a token, then answer each user search with ``answer_users``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200, json={"access_token": "mgmt", "expires_in": 3600}
            )
        assert request.url.path == "/api/v2/users"
        return answer_users(request)

    return handler


def _searches(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in requests if request.url.path == "/api/v2/users"]


def test_profiles_are_read_with_one_search_per_fifty_user_ids() -> None:
    user_ids = [f"auth0|{number}" for number in range(120)]

    def answer(request: httpx.Request) -> httpx.Response:
        requested = [
            quoted.strip('"')
            for quoted in request.url.params["q"]
            .removeprefix("user_id:(")
            .removesuffix(")")
            .split(" OR ")
        ]
        return httpx.Response(
            200,
            json=[
                _profile_payload(
                    user_id,
                    email=f"{user_id.split('|')[1]}@example.test",
                    email_verified=True,
                    given_name="Given",
                    family_name="Family",
                    name="Given Family",
                )
                for user_id in requested
            ],
        )

    client, requests = _client(_token_then_users(answer))

    profiles = client.read_user_profiles([*user_ids, user_ids[0]])

    searches = _searches(requests)
    assert [search.url.params["per_page"] for search in searches] == [
        "50",
        "50",
        "20",
    ]
    for search in searches:
        assert search.method == "GET"
        assert search.headers["authorization"] == "Bearer mgmt"
        assert search.url.params["search_engine"] == "v3"
        assert search.url.params["fields"] == PROFILE_FIELDS
        assert search.url.params["include_fields"] == "true"
    assert searches[0].url.params["q"] == (
        "user_id:(" + " OR ".join(f'"auth0|{number}"' for number in range(50)) + ")"
    )
    assert set(profiles) == set(user_ids)
    assert profiles["auth0|7"] == Auth0UserProfile(
        user_id="auth0|7",
        email="7@example.test",
        email_verified=True,
        given_name="Given",
        family_name="Family",
        name="Given Family",
    )


def test_profile_reads_escape_quotes_and_backslashes_in_user_ids() -> None:
    client, requests = _client(
        _token_then_users(lambda _request: httpx.Response(200, json=[]))
    )

    profiles = client.read_user_profiles(['auth0|quote"d', "auth0|back\\slash"])

    (search,) = _searches(requests)
    assert profiles == {}
    assert search.url.params["q"] == (
        'user_id:("auth0|quote\\"d" OR "auth0|back\\\\slash")'
    )


def test_profile_reads_keep_only_requested_well_formed_users() -> None:
    answered = [
        _profile_payload(
            "auth0|kept",
            email="  kept@example.test ",
            email_verified="true",
            given_name="",
            family_name=7,
        ),
        _profile_payload("auth0|not-requested", email="other@example.test"),
        {"email": "no-id@example.test"},
        "not a user",
    ]
    client, _requests = _client(
        _token_then_users(lambda _request: httpx.Response(200, json=answered))
    )

    profiles = client.read_user_profiles(["auth0|kept"])

    assert profiles == {
        "auth0|kept": Auth0UserProfile(
            user_id="auth0|kept",
            email="kept@example.test",
            email_verified=False,
            given_name=None,
            family_name=None,
            name=None,
        )
    }


def test_no_user_ids_need_no_request() -> None:
    client, requests = _client(_token_then_users(lambda _request: httpx.Response(500)))

    assert client.read_user_profiles([]) == {}
    assert requests == []


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("ant", "email:*ant*"),
        ("an", "email:an*"),
        ("Ant", "email:*ant*"),
        ("@policyengine.org", "email:*@policyengine.org*"),
        ("a+b", "email:*a\\+b*"),
        ("a b", "email:*a\\ b*"),
        ("x:y", "email:*x\\:y*"),
        ("*?", "email:\\*\\?*"),
        (
            '+-&|!(){}[]^"~*?:\\/ ',
            "email:*"
            + "".join(f"\\{character}" for character in '+-&|!(){}[]^"~*?:\\/ ')
            + "*",
        ),
    ],
)
def test_email_searches_escape_the_text_and_wildcards_need_three_characters(
    text: str, query: str
) -> None:
    client, requests = _client(
        _token_then_users(lambda _request: httpx.Response(200, json=[]))
    )

    result = client.search_user_ids_by_email(text)

    (search,) = _searches(requests)
    assert result == Auth0UserIdSearch(user_ids=(), limit_reached=False)
    assert search.url.params["q"] == query
    assert search.url.params["search_engine"] == "v3"
    assert search.url.params["fields"] == "user_id"
    assert search.url.params["include_fields"] == "true"
    assert search.url.params["per_page"] == "50"
    assert search.url.params["page"] == "0"


def _pages_of_user_ids(total: int):
    def answer(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        per_page = int(request.url.params["per_page"])
        numbers = range(page * per_page, min(total, (page + 1) * per_page))
        return httpx.Response(
            200, json=[{"user_id": f"auth0|{number}"} for number in numbers]
        )

    return answer


def test_email_searches_page_through_results_fifty_at_a_time() -> None:
    client, requests = _client(_token_then_users(_pages_of_user_ids(120)))

    result = client.search_user_ids_by_email("example")

    assert [search.url.params["page"] for search in _searches(requests)] == [
        "0",
        "1",
        "2",
    ]
    assert result.user_ids == tuple(f"auth0|{number}" for number in range(120))
    assert result.limit_reached is False


def test_email_searches_stop_at_auth0s_one_thousand_result_limit() -> None:
    client, requests = _client(_token_then_users(_pages_of_user_ids(5000)))

    result = client.search_user_ids_by_email("example")

    assert len(_searches(requests)) == 20
    assert len(result.user_ids) == 1000
    assert result.limit_reached is True


def _failing_with(failure):
    def answer(request: httpx.Request) -> httpx.Response:
        if isinstance(failure, int):
            return httpx.Response(failure, json={"message": "refused"})
        message = "the Management API did not answer"
        raise failure(message, request=request)

    return answer


@pytest.mark.parametrize(
    "failure",
    [403, 429, 500, 503, 400, httpx.ConnectTimeout, httpx.ConnectError],
)
@pytest.mark.parametrize("operation", ["read_user_profiles", "search"])
def test_profile_failures_raise_one_unavailable_error_without_personal_data(
    failure, operation: str
) -> None:
    client, _requests = _client(_token_then_users(_failing_with(failure)))
    read_profiles_or_search = (
        (lambda: client.search_user_ids_by_email("secret-person@example.test"))
        if operation == "search"
        else (lambda: client.read_user_profiles(["google-oauth2|secret-subject"]))
    )

    with pytest.raises(Auth0UserProfilesUnavailableError) as error:
        read_profiles_or_search()

    message = str(error.value)
    for personal_or_secret in ("secret-person", "secret-subject", "mgmt", "raw"):
        assert personal_or_secret not in message
    assert isinstance(error.value, Auth0ManagementError)


@pytest.mark.parametrize(
    "token_answer",
    [
        httpx.Response(500),
        httpx.Response(200, json={"expires_in": 3600}),
    ],
)
def test_a_failed_token_request_makes_profiles_unavailable(
    token_answer: httpx.Response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return token_answer
        return httpx.Response(200, json=[])

    client, _requests = _client(handler)

    with pytest.raises(Auth0UserProfilesUnavailableError):
        client.read_user_profiles(["auth0|1"])


def test_an_unreadable_profile_answer_makes_profiles_unavailable() -> None:
    client, _requests = _client(
        _token_then_users(
            lambda _request: httpx.Response(200, json={"users": "not a list"})
        )
    )

    with pytest.raises(Auth0UserProfilesUnavailableError):
        client.read_user_profiles(["auth0|1"])
    with pytest.raises(Auth0UserProfilesUnavailableError):
        client.search_user_ids_by_email("example")


def test_profile_reads_retry_once_with_a_fresh_token_after_a_401() -> None:
    issued_tokens: list[str] = []
    search_statuses = [401, 200, 401, 401]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            issued_tokens.append(f"mgmt-{len(issued_tokens) + 1}")
            return httpx.Response(
                200, json={"access_token": issued_tokens[-1], "expires_in": 86400}
            )
        status = search_statuses.pop(0)
        return httpx.Response(status, json=[] if status == 200 else None)

    client, requests = _client(handler)

    assert client.read_user_profiles(["auth0|1"]) == {}
    with pytest.raises(Auth0UserProfilesUnavailableError, match="HTTP 401"):
        client.read_user_profiles(["auth0|1"])

    searches = _searches(requests)
    assert [search.headers["authorization"] for search in searches] == [
        "Bearer mgmt-1",
        "Bearer mgmt-2",
        "Bearer mgmt-2",
        "Bearer mgmt-3",
    ]
