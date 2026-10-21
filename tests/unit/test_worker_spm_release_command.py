"""Characterization of the worker release check's command-line entry point."""

import io
import json
import sys

import pytest

from policyengine_api import worker_spm_release

USAGE = "Usage: python -m policyengine_api.worker_spm_release BUNDLE_VERSION"


@pytest.mark.parametrize("arguments", [[], ["1.0.0", "extra"]])
def test_wrong_argument_count_exits_with_usage(monkeypatch, arguments):
    validate = []
    monkeypatch.setattr(sys, "argv", ["worker_spm_release", *arguments])
    monkeypatch.setattr(
        worker_spm_release,
        "validate_installed_worker",
        lambda *call: validate.append(call),
    )

    with pytest.raises(SystemExit) as caught:
        worker_spm_release.main()

    assert caught.value.code == USAGE
    assert validate == []


@pytest.mark.parametrize(
    ("selection", "expected_output"),
    [
        (None, "The installed legacy bundle and registered worker agree\n"),
        (
            {"scenario": "baseline"},
            "The installed bundle and registered worker capability agree\n",
        ),
    ],
)
def test_one_bundle_version_validates_the_registry_from_stdin(
    monkeypatch, capsys, selection, expected_output
):
    calls = []
    registry = {"policyengine": {"1.0.0": "worker-app"}}
    monkeypatch.setattr(sys, "argv", ["worker_spm_release", "1.0.0"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(registry)))

    def validate(document, bundle_version):
        calls.append((document, bundle_version))
        return selection

    monkeypatch.setattr(worker_spm_release, "validate_installed_worker", validate)

    worker_spm_release.main()

    assert calls == [(registry, "1.0.0")]
    assert capsys.readouterr().out == expected_output
