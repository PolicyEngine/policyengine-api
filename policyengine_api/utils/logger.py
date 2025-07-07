import logging
import json
import sys
from datetime import datetime, timezone


class Logger:
    def __init__(self, name = "policyengine-api", level = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)

    def log_struct(self, payload: dict, severity: str = "INFO", message: str = None):
        log_entry = {
            "severity": severity.upper(),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        }  

        if message:
            log_entry["message"] = message

        if isinstance(payload, dict):
            log_entry.update(payload)

        json_log = json.dumps(log_entry, ensure_ascii=False)
        self._emit(severity, json_log)

    def _emit(self, severity: str, msg: str):
        level = severity.upper()
        if level == "DEBUG":
            self.logger.debug(msg)
        elif level == "INFO":
            self.logger.info(msg)
        elif level == "WARNING":
            self.logger.warning(msg)
        elif level == "ERROR":
            self.logger.error(msg)
        elif level == "CRITICAL":
            self.logger.critical(msg)
        else:
            self.logger.info(msg)




