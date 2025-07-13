from policyengine_api.utils.logger import Logger

def test_log_struct(capsys):
    logger = Logger("test-logger")
    logger.log_struct(
        {"event": "test_event", "user_id": "abc123"},
        severity="INFO",
        message="Logging from test"
    )
    captured = capsys.readouterr()
    assert '"severity": "INFO"' in captured.out
    assert '"event": "test_event"' in captured.out
    assert '"message": "Logging from test"' in captured.out
