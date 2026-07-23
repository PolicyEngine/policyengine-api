import pytest

from policyengine_api import readiness


@pytest.fixture(autouse=True)
def _restore_ready():
    # readiness state is module-global; leave it ready for other tests.
    yield
    readiness.mark_ready()


def test_defaults_to_ready():
    assert readiness.is_ready() is True


def test_mark_not_ready_then_ready():
    readiness.mark_not_ready()
    assert readiness.is_ready() is False
    readiness.mark_ready()
    assert readiness.is_ready() is True
