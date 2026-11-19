"""Structured (JSON) logging with a per-job correlation id.

Policy: never log post text, e-mail addresses, phone numbers or credentials.
Log counts and identifiers only.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        job_id = job_id_var.get()
        if job_id:
            payload["job_id"] = job_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        job_id = job_id_var.get()
        record.job = f" [job={job_id[:8]}]" if job_id else ""
        return super().format(record)


def configure_logging(level: str = "INFO", as_json: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if as_json else _TextFormatter("%(asctime)s %(levelname)s %(name)s%(job)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
