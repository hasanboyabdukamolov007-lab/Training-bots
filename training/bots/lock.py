"""Prevents two processes polling the same bot token.

Telegram delivers each update once. Two pollers on one token means updates are
split unpredictably between them and a trainee sees half their replies, which
looks exactly like a broken bot. A lock makes that failure impossible rather
than rare.

The lock filename is a hash of the token, never the token: a directory listing
must not leak credentials.
"""

from __future__ import annotations

import errno
import hashlib
import os
import tempfile
from dataclasses import dataclass

DEFAULT_LOCK_DIR = os.path.join(tempfile.gettempdir(), "training-bots-locks")


def token_fingerprint(token: str) -> str:
    """A stable, non-reversible id for a token."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class LockHeld(RuntimeError):
    """Raised when another live process already polls this token."""


@dataclass
class PollLock:
    """An advisory lock keyed on the token's fingerprint."""

    token: str
    lock_dir: str = DEFAULT_LOCK_DIR
    path: str = ""
    _acquired: bool = False

    def __post_init__(self) -> None:
        if not self.path:
            self.path = os.path.join(
                self.lock_dir, f"{token_fingerprint(self.token)}.lock"
            )

    def acquire(self) -> None:
        os.makedirs(self.lock_dir, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            holder = self._read_pid()
            if holder is not None and _pid_alive(holder):
                raise LockHeld(
                    f"another process (pid {holder}) is already polling this bot. "
                    "Stop it first, or the two will split Telegram's updates "
                    "between them."
                )
            # The holder is gone; the lock is stale. Take it over.
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        # Only remove a lock still owned by this process.
        if self._read_pid() == os.getpid():
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
        self._acquired = False

    def _read_pid(self) -> int | None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def __enter__(self) -> "PollLock":
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True
