"""
Structured JSON logger for DigiPlus.
Outputs to stdout (INFO+) and logs/digiplus.log (DEBUG+).
No secrets are ever logged.
"""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

# Per-request correlation ID — set by the middleware
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


class _JSONFormatter(logging.Formatter):
    _EXTRA = (
        "correlation_id", "event", "meeting_id", "task_id",
        "run_id", "latency_ms", "status", "model", "error",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "level":          record.levelname,
            "logger":         record.name,
            "msg":            record.getMessage(),
            "correlation_id": correlation_id_var.get("-"),
        }
        for key in self._EXTRA:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _make_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = _JSONFormatter()

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(LOG_DIR / "digiplus.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.propagate = False
    return logger


log = _make_logger("digiplus")
