"""Minimal Telegram Bot API client.

`transport` is injectable so the whole runtime can be driven offline in tests.
That is not only for convenience: this build environment cannot reach
api.telegram.org, so an injectable transport is the only way the poll loop and
handlers get real test coverage at all.

Dry run is enforced here, at the single choke point every send passes through,
rather than at each call site.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

API_BASE = "https://api.telegram.org"

#: (method, token, payload) -> decoded JSON response
Transport = Callable[[str, str, dict[str, Any]], dict[str, Any]]


class TelegramError(RuntimeError):
    """An error Telegram itself reported. Never carries token material."""

    def __init__(self, method: str, description: str, code: int | None = None) -> None:
        super().__init__(f"{method}: {description}")
        self.method = method
        self.description = description
        self.code = code

    @property
    def permanent(self) -> bool:
        """A 4xx will not fix itself; retrying only wastes the trainee's time."""
        return self.code is not None and 400 <= self.code < 500


def http_transport(timeout: int = 35) -> Transport:
    """The real transport."""

    def send(method: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{API_BASE}/bot{token}/{method}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode())
            except Exception:
                return {"ok": False, "error_code": exc.code,
                        "description": f"HTTP {exc.code}"}

    return send


@dataclass
class SentMessage:
    """What a send produced. `dry_run` means nothing was transmitted."""

    chat_id: int
    text: str
    message_id: int | None = None
    dry_run: bool = False


@dataclass
class TelegramClient:
    """One bot's API client."""

    token: str
    transport: Transport = field(default_factory=http_transport)
    dry_run: bool = True
    #: Every suppressed send, so a dry run is inspectable and testable.
    outbox: list[SentMessage] = field(default_factory=list)

    def call(self, method: str, **payload: Any) -> Any:
        response = self.transport(method, self.token, payload)
        if not isinstance(response, dict):
            raise TelegramError(method, "malformed response")
        if not response.get("ok"):
            raise TelegramError(
                method,
                str(response.get("description", "unknown error")),
                response.get("error_code"),
            )
        return response.get("result")

    # ── read-only ──────────────────────────────────────────────────────────

    def get_me(self) -> dict[str, Any]:
        """Identity. The only way to know which bot a token belongs to."""
        return self.call("getMe")

    def get_updates(self, offset: int | None = None, timeout: int = 25,
                    allowed_updates: list[str] | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        result = self.call("getUpdates", **payload)
        return result if isinstance(result, list) else []

    def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        return self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    def get_chat(self, chat_id: int) -> dict[str, Any]:
        return self.call("getChat", chat_id=chat_id)

    # ── writes ─────────────────────────────────────────────────────────────

    def send_message(self, chat_id: int, text: str,
                     reply_to: int | None = None) -> SentMessage:
        """Sends, or records the intent when dry run is on.

        Dry run is checked before the transport is touched, so a dry run cannot
        reach Telegram even if a transport is misconfigured.
        """
        if self.dry_run:
            pending = SentMessage(chat_id=chat_id, text=text, dry_run=True)
            self.outbox.append(pending)
            return pending

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to is not None:
            payload["reply_to_message_id"] = reply_to
        result = self.call("sendMessage", **payload)
        message_id = result.get("message_id") if isinstance(result, dict) else None
        sent = SentMessage(chat_id=chat_id, text=text, message_id=message_id)
        self.outbox.append(sent)
        return sent


# ── test transports ─────────────────────────────────────────────────────────

def scripted_transport(
    me: dict[str, Any] | None = None,
    update_batches: list[list[dict[str, Any]]] | None = None,
    fail: dict[str, tuple[int, str]] | None = None,
) -> Transport:
    """A transport that replays canned responses. For tests and `--self-test`.

    `update_batches` is consumed one `getUpdates` call at a time; when it runs
    out, every later poll returns no updates.
    """
    identity = me or {"id": 1, "username": "scripted_bot", "is_bot": True}
    batches = list(update_batches or [])
    failures = fail or {}
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(method: str, _token: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((method, payload))
        if method in failures:
            code, description = failures[method]
            return {"ok": False, "error_code": code, "description": description}
        if method == "getMe":
            return {"ok": True, "result": identity}
        if method == "getUpdates":
            batch = batches.pop(0) if batches else []
            return {"ok": True, "result": batch}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 1000 + len(calls)}}
        if method == "getChat":
            return {"ok": True, "result": {"id": payload.get("chat_id"),
                                           "type": "supergroup", "title": "[TEST] group"}}
        if method == "getChatMember":
            return {"ok": True, "result": {"status": "member"}}
        return {"ok": False, "error_code": 400, "description": f"unsupported: {method}"}

    send.calls = calls  # type: ignore[attr-defined]
    return send
