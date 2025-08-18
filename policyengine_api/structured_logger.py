import logging
import json
import sys


class JsonFormatter(logging.Formatter):
    """Formatter that outputs logs as structured JSON."""

    def format(self, record):
        log_record = {
            "severity": record.levelname,
            "event": getattr(record, "event", None),
            "input": getattr(record, "input", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def get_logger(name="policyengine-api", level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # If no handlers are set, add a StreamHandler with JSON formatting
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def log_struct(event, input_data, message, severity="INFO", logger=None):
    """
    Implementation-agnostic structured logger.
    """
    if logger is None:
        logger = get_logger()

    log_func = getattr(logger, severity.lower(), logger.info)
    log_func(message, extra={"event": event, "input": input_data})
