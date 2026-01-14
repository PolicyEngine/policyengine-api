import pytest
from typing import Optional
from unittest.mock import MagicMock, patch


# Event class to mimic Anthropic's streaming response events
class MockEvent:
    def __init__(
        self,
        event_type: str,
        text: Optional[str] = None,
        error: Optional[dict[str, str]] = None,
    ):
        self.type = event_type
        self.text = text
        self.error = error


@pytest.fixture()
def patch_anthropic():
    """
    Fixture that patches the anthropic module at the root level.
    This ensures all imports of anthropic.Anthropic use our mock.
    """
    with patch("anthropic.Anthropic") as mock:
        yield mock


@pytest.fixture
def mock_stream_text_events(patch_anthropic):
    """
    Fixture that configures the mock Anthropic client to stream text events.
    """

    def _configure(text_chunks: list[str]):
        # Set up mock client
        mock_client = MagicMock()
        patch_anthropic.return_value = mock_client

        # Set up mock stream
        mock_stream = MagicMock()
        mock_client.messages.stream.return_value.__enter__.return_value = mock_stream

        # Configure stream to yield text events
        events = [MockEvent(event_type="text", text=chunk) for chunk in text_chunks]
        mock_stream.__iter__.return_value = events

        return mock_client

    return _configure


@pytest.fixture
def mock_stream_error_event(patch_anthropic):
    """
    Fixture that configures the mock Anthropic client to stream an error event.
    """

    def _configure(error_type: str):
        # Set up mock client
        mock_client = MagicMock()
        patch_anthropic.return_value = mock_client

        # Set up mock stream
        mock_stream = MagicMock()
        mock_client.messages.stream.return_value.__enter__.return_value = mock_stream

        # Configure stream to yield an error event
        error_event = MockEvent(event_type="error", error={"type": error_type})
        mock_stream.__iter__.return_value = [error_event]

        return mock_client

    return _configure


def parse_to_chunks(input: str) -> list[str]:
    """
    The AI analysis service returns streaming output in chunks of 5 characters.
    Parse any string to that format.
    """
    CHAR_LEN = 5

    return [input[i : i + CHAR_LEN] for i in range(0, len(input), CHAR_LEN)]
