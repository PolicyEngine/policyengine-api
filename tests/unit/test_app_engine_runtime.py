from __future__ import annotations

from unittest.mock import Mock

import pytest

from policyengine_api import app_engine_runtime


SECRET_RESOURCE_PREFIX = "projects/test-project/secrets"


def _direct_secret_env() -> dict[str, str]:
    return {
        value_name: f"direct-{index}"
        for index, (value_name, _) in enumerate(
            app_engine_runtime.SECRET_ENV_SOURCES,
            start=1,
        )
    }


def _resource_secret_env() -> dict[str, str]:
    return {
        resource_name: f"{SECRET_RESOURCE_PREFIX}/secret-{index}/versions/latest"
        for index, (_, resource_name) in enumerate(
            app_engine_runtime.SECRET_ENV_SOURCES,
            start=1,
        )
    }


def test_direct_secrets_do_not_call_secret_manager():
    environ = _direct_secret_env()
    loader = Mock(side_effect=AssertionError("loader must not be called"))

    app_engine_runtime.hydrate_app_engine_runtime_secrets(
        environ,
        secret_loader=loader,
    )

    loader.assert_not_called()


def test_secret_resources_are_resolved_only_into_process_environment():
    environ = _resource_secret_env()
    calls = []

    def load_secret(resource: str) -> str:
        calls.append(resource)
        return f"resolved-{len(calls)}"

    app_engine_runtime.hydrate_app_engine_runtime_secrets(
        environ,
        secret_loader=load_secret,
    )

    assert calls == list(_resource_secret_env().values())
    for index, (value_name, _) in enumerate(
        app_engine_runtime.SECRET_ENV_SOURCES,
        start=1,
    ):
        assert environ[value_name] == f"resolved-{index}"
    assert not set(_resource_secret_env()) & set(environ)

    app_engine_runtime.hydrate_app_engine_runtime_secrets(
        environ,
        secret_loader=Mock(side_effect=AssertionError("loader must not be called")),
    )


@pytest.mark.parametrize(
    ("mutate", "expected_message"),
    [
        (
            lambda env, value, resource: env.update({value: "direct"}),
            "set exactly one of",
        ),
        (
            lambda env, value, resource: env.pop(resource),
            "is required",
        ),
        (
            lambda env, value, resource: env.update({resource: "not-a-resource"}),
            "is invalid",
        ),
    ],
)
def test_secret_source_configuration_fails_closed(mutate, expected_message):
    environ = _resource_secret_env()
    value_name, resource_name = app_engine_runtime.SECRET_ENV_SOURCES[0]
    mutate(environ, value_name, resource_name)

    with pytest.raises(
        app_engine_runtime.AppEngineRuntimeConfigurationError,
        match=expected_message,
    ):
        app_engine_runtime.hydrate_app_engine_runtime_secrets(
            environ,
            secret_loader=lambda _: "resolved",
        )


@pytest.mark.parametrize(
    ("loader", "expected_message"),
    [
        (lambda _: "", "is empty"),
        (Mock(side_effect=PermissionError), "could not be resolved"),
    ],
)
def test_secret_resolution_fails_closed_without_exposing_values(
    loader,
    expected_message,
):
    environ = _resource_secret_env()

    with pytest.raises(
        app_engine_runtime.AppEngineRuntimeConfigurationError,
        match=expected_message,
    ) as error:
        app_engine_runtime.hydrate_app_engine_runtime_secrets(
            environ,
            secret_loader=loader,
        )

    assert "resolved-secret-value" not in str(error.value)


def test_main_hydrates_secrets_before_replacing_process(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_engine_runtime,
        "hydrate_app_engine_runtime_secrets",
        lambda: calls.append("hydrate"),
    )
    monkeypatch.setenv("PORT", "9090")

    def execvp(executable, args):
        calls.append((executable, args))

    monkeypatch.setattr(app_engine_runtime.os, "execvp", execvp)

    app_engine_runtime.main()

    assert calls == [
        "hydrate",
        (
            "gunicorn",
            [
                "gunicorn",
                "-b",
                ":9090",
                "policyengine_api.api",
                "--timeout",
                "900",
                "--workers",
                "5",
            ],
        ),
    ]
