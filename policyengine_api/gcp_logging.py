import os
import logging
from google.cloud.logging import Client

if os.environ.get("FLASK_DEBUG") == "1":
    logger = logging.getLogger(__name__)

    # shims to make default logger act like google's
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    def log_struct(msg, severity="INFO"):
        logger.log(levels.get(severity, "INFO"), msg)

    def log_text(msg, severity="INFO"):
        logger.log(levels.get(severity, "INFO"), msg)

    logger.log_struct = log_struct
    logger.log_text = log_text
else:
    logger = Client().logger("policyengine-api")
