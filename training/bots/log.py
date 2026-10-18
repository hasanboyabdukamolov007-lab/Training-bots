"""Structured logging with unconditional redaction.

A bot token in a log file is a compromised bot. Redaction is therefore applied
at the formatter, not at each call site: a developer who forgets to redact still
cannot leak a token through this logger.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

#: Token material registered at startup, stripped from every record.
_SECRETS: set[str] = set()

_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
#: Also catch a token smuggled inside an api.telegram.org URL.
_URL_RE = re.compile(r"(api\.telegram\.org/bot)[^/\s]+")


def register_secret(value: str) -> None:
    if value and value.strip():
        _SECRETS.add(value.strip())


def clear_secrets() -> None:
    _SECRETS.clear()


def redact(text: str) -> str:
    """Removes every known secret and anything token-shaped."""
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, "<redacted-token>")
            head = secret.split(":", 1)[0]
            if head and len(head) >= 5:
                text = text.replace(head, "<redacted-bot-id>")
    text = _URL_RE.sub(r"\1<redacted-token>", text)
    return _TOKEN_RE.sub("<redacted-token>", text)


class RedactingJsonFormatter(logging.Formatter):
    """One JSON object per line, with every string value redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "bot": getattr(record, "bot", "-"),
            "event": getattr(record, "event", record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if payload["event"] != record.getMessage():
            payload["msg"] = record.getMessage()

        def scrub(value: Any) -> Any:
            if isinstance(value, str):
                return redact(value)
            if isinstance(value, dict):
                return {k: scrub(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [scrub(v) for v in value]
            return value

        return json.dumps(scrub(payload), ensure_ascii=False, sort_keys=False)


def get_logger(name: str = "training.bots", stream=None) -> logging.Logger:
    """A logger that writes redacted JSON lines. Idempotent."""
    logger = logging.getLogger(name)
    if not any(getattr(h, "_training_bots", False) for h in logger.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(RedactingJsonFormatter())
        handler._training_bots = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def event(logger: logging.Logger, bot: str, name: str, level: int = logging.INFO,
          **fields: Any) -> None:
    """Logs a structured event. All values are redacted by the formatter."""
    logger.log(level, name, extra={"bot": bot, "event": name, "fields": fields})
