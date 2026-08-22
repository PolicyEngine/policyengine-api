"""Guard the installed anthropic SDK against the call shape the services use.

The AI analysis services call ``claude_client.messages.stream(...)`` with a
``temperature`` keyword. The unit suites mock the client with permissive
fakes, so an SDK whose real signature dropped that keyword (anthropic 1.x
removed ``temperature``/``top_p``/``top_k`` and ``HUMAN_PROMPT``) still
passes every mocked test while failing at runtime on a cache miss. This test
checks the real installed SDK instead.
"""

import inspect

import anthropic
from anthropic.resources.messages import Messages


def test_installed_anthropic_sdk_accepts_stream_temperature():
    parameters = inspect.signature(Messages.stream).parameters
    assert "temperature" in parameters, (
        f"anthropic {anthropic.__version__} no longer accepts temperature in "
        "Messages.stream(); migrate ai_analysis_service before raising the pin"
    )


def test_installed_anthropic_sdk_is_pre_1_0():
    major = int(anthropic.__version__.split(".")[0])
    assert major < 1, (
        f"anthropic {anthropic.__version__} installed; pyproject pins <1 until "
        "the services are migrated to the 1.x call surface"
    )
