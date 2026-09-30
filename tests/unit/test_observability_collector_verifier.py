from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path

import grpc
import pytest

ROOT = Path(__file__).parents[2]
VERIFIER_PATH = ROOT / ".github" / "scripts" / "verify_observability_collector.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("collector_verifier", VERIFIER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Unimplemented(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNIMPLEMENTED


def test_verify_accepts_traces_and_metrics_but_requires_logs_to_be_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    exports: list[tuple[str, tuple[tuple[str, str], ...], float]] = []

    def stub(signal: str, *, reject: bool = False):
        class Stub:
            def __init__(self, _channel):
                pass

            def Export(self, _request, *, metadata, timeout):
                exports.append((signal, metadata, timeout))
                if reject:
                    raise _Unimplemented()

        return Stub

    monkeypatch.setattr(
        verifier.grpc,
        "secure_channel",
        lambda *_args, **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(verifier, "TraceServiceStub", stub("traces"))
    monkeypatch.setattr(verifier, "MetricsServiceStub", stub("metrics"))
    monkeypatch.setattr(verifier, "LogsServiceStub", stub("logs", reject=True))

    verifier.verify("https://collector.example", "token", timeout_seconds=3.0)

    assert exports == [
        ("traces", (("authorization", "Bearer token"),), 3.0),
        ("metrics", (("authorization", "Bearer token"),), 3.0),
        ("logs", (("authorization", "Bearer token"),), 3.0),
    ]


def test_verify_fails_when_the_collector_accepts_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()

    class AcceptingStub:
        def __init__(self, _channel):
            pass

        def Export(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        verifier.grpc,
        "secure_channel",
        lambda *_args, **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(verifier, "TraceServiceStub", AcceptingStub)
    monkeypatch.setattr(verifier, "MetricsServiceStub", AcceptingStub)
    monkeypatch.setattr(verifier, "LogsServiceStub", AcceptingStub)

    with pytest.raises(RuntimeError, match="unexpectedly accepted application logs"):
        verifier.verify("https://collector.example", "token")


@pytest.mark.parametrize(
    "endpoint",
    ["http://collector.example", "collector.example", "https:///missing-host"],
)
def test_authority_rejects_non_https_or_hostless_endpoints(endpoint: str) -> None:
    verifier = _load_verifier()

    with pytest.raises(ValueError, match="HTTPS URL"):
        verifier._authority(endpoint)
