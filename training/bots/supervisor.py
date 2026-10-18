"""Starts and stops the three manager bots independently.

Isolation is the whole job: one bad token, one revoked bot or one crash must
leave the other two running and teaching.
"""

from __future__ import annotations

import logging
import signal
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from training.bots import log as botlog
from training.bots.api import TelegramClient, Transport, http_transport
from training.bots.config import BotConfig, Role, RuntimeConfig
from training.bots.manager import ManagerBot


@dataclass
class Supervisor:
    """Owns the bot runtimes and their lifecycle."""

    runtime: RuntimeConfig
    transport_factory: Callable[[], Transport] = http_transport
    logger: logging.Logger = field(default_factory=botlog.get_logger)
    lock_dir: str | None = None
    bots: list[ManagerBot] = field(default_factory=list)
    skipped: list[tuple[Role, list[str]]] = field(default_factory=list)
    _stop_all = threading.Event()

    def build(self, only: list[str] | None = None) -> None:
        """Creates a runtime per usable bot; records why the others were skipped."""
        wanted = set(only) if only else None
        for bot_cfg in self.runtime.bots:
            if wanted is not None and bot_cfg.role.bot_id not in wanted:
                continue
            if not bot_cfg.ok:
                self.skipped.append((bot_cfg.role, bot_cfg.errors))
                botlog.event(self.logger, bot_cfg.role.bot_id, "skipped",
                             level=logging.WARNING, reasons=bot_cfg.errors)
                continue
            client = TelegramClient(
                token=bot_cfg.token,
                transport=self.transport_factory(),
                dry_run=self.runtime.dry_run,
            )
            self.bots.append(ManagerBot(
                bot_cfg=bot_cfg, runtime=self.runtime, client=client,
                logger=self.logger, lock_dir=self.lock_dir,
            ))

    def verify_all(self) -> list[tuple[str, bool, str]]:
        """Verifies every identity. Never raises; one failure does not stop others."""
        out: list[tuple[str, bool, str]] = []
        for bot in self.bots:
            try:
                ok, detail = bot.verify()
            except Exception as exc:
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            out.append((bot.role.bot_id, ok, detail))
        return out

    def start_all(self) -> list[threading.Thread]:
        threads = [bot.start_background() for bot in self.bots]
        botlog.event(self.logger, "supervisor", "start_all",
                     started=len(threads), skipped=len(self.skipped),
                     dry_run=self.runtime.dry_run)
        return threads

    def stop_all(self, reason: str = "requested") -> None:
        for bot in self.bots:
            try:
                bot.stop(reason)
            except Exception as exc:
                botlog.event(self.logger, bot.role.bot_id, "stop.failed",
                             level=logging.ERROR, reason=str(exc))
        self._stop_all.set()

    def join_all(self, timeout: float = 15.0) -> list[str]:
        """Waits for a clean shutdown. Returns the ids that did not finish."""
        stragglers = [b.role.bot_id for b in self.bots if not b.join(timeout)]
        if stragglers:
            botlog.event(self.logger, "supervisor", "join.timeout",
                         level=logging.WARNING, bots=stragglers)
        return stragglers

    def install_signal_handlers(self) -> None:
        """Ctrl-C and SIGTERM stop every bot cleanly, releasing their locks."""

        def handler(signum: int, _frame: Any) -> None:
            botlog.event(self.logger, "supervisor", "signal",
                         signal=signal.Signals(signum).name)
            self.stop_all(f"signal {signal.Signals(signum).name}")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                # Not the main thread, or unsupported. Not fatal.
                pass

    def wait(self) -> None:
        """Blocks until stopped. Any live bot keeps the supervisor alive."""
        while not self._stop_all.is_set():
            if not any(b.state.running for b in self.bots):
                # Give threads a moment to come up before concluding they are done.
                if self._stop_all.wait(0.5):
                    break
                if not any(b.state.running for b in self.bots) and \
                        all(b._thread is not None and not b._thread.is_alive()
                            for b in self.bots):
                    break
            self._stop_all.wait(0.5)

    def status(self) -> list[dict[str, Any]]:
        return [b.state.snapshot() for b in self.bots]
