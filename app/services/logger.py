"""
logger.py — Structured logging for Social Context.
"""

import logging
import json


class StructuredLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: str, event: str, **kwargs):
        msg = json.dumps({"event": event, **kwargs})
        getattr(self._logger, level)(msg)

    def info(self, event: str, **kwargs):
        self._log("info", event, **kwargs)

    def warning(self, event: str, **kwargs):
        self._log("warning", event, **kwargs)

    def error(self, event: str, **kwargs):
        self._log("error", event, **kwargs)

    def debug(self, event: str, **kwargs):
        self._log("debug", event, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
