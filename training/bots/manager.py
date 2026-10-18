"""The manager bot runtime.

Each bot polls `getUpdates`, answers a small command set, and walks a trainee
through its one assigned scenario. Replies are plain HTML, escaped the same way
production escapes customer text.

What it is not: a simulated colleague. Telegram bots cannot see one another's
group messages, so three bots cannot role-play a team (AUDIT.md §3). Each is a
tutor for one lesson, which is something they genuinely can be.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from training import production as prod
from training.bots import log as botlog
from training.bots.api import TelegramClient, TelegramError
from training.bots.config import BotConfig, RuntimeConfig
from training.bots.lock import LockHeld, PollLock
from training.leads import generate
from training.modes import Mode, RunLog, Status
from training.render import as_test_message, render
from training.scenarios import Context, by_id, run_scenario

#: Backoff between failed polls: grows, then holds. Never gives up silently.
BACKOFF_SECONDS = (1, 2, 5, 10, 30)


def _esc(text: str) -> str:
    return prod.escape_html(text)


@dataclass
class BotState:
    """Live state of one bot. Safe to read from another thread."""

    bot_id: str
    display: str
    scenario_id: str
    running: bool = False
    identity: str = ""
    verified: bool = False
    updates_handled: int = 0
    replies: int = 0
    errors: int = 0
    last_error: str = ""
    stopped_reason: str = ""
    #: The step each trainee chat has reached, keyed by chat id.
    progress: dict[int, int] = field(default_factory=dict)
    #: Chats where this bot's lesson is running. In a group holding all three
    #: managers, only the active one answers plain messages — otherwise every
    #: sentence a trainee types draws three different replies.
    active_chats: set[int] = field(default_factory=set)
    #: An open question per chat, awaiting a typed answer.
    pending: dict[int, str] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "bot": self.bot_id, "display": self.display,
            "scenario": self.scenario_id, "running": self.running,
            "identity": self.identity or "-", "verified": self.verified,
            "updates": self.updates_handled, "replies": self.replies,
            "errors": self.errors,
            "last_error": self.last_error, "stopped_reason": self.stopped_reason,
        }


class ManagerBot:
    """One training manager bot: verify, poll, answer, stop cleanly."""

    def __init__(self, bot_cfg: BotConfig, runtime: RuntimeConfig,
                 client: TelegramClient, logger: logging.Logger | None = None,
                 lock_dir: str | None = None) -> None:
        self.cfg = bot_cfg
        self.runtime = runtime
        self.client = client
        self.log = logger or botlog.get_logger()
        self.role = bot_cfg.role
        self.state = BotState(
            bot_id=self.role.bot_id, display=self.role.display,
            scenario_id=self.role.scenario_id,
        )
        self._stop = threading.Event()
        self._offset: int | None = None
        self._lock = PollLock(token=bot_cfg.token,
                              **({"lock_dir": lock_dir} if lock_dir else {}))
        self._thread: threading.Thread | None = None
        #: Our own @username, learned from getMe. Used to tell whether a
        #: command in a group was addressed to us or to another bot.
        self.username = ""
        botlog.register_secret(bot_cfg.token)

    # ── identity ───────────────────────────────────────────────────────────

    def verify(self) -> tuple[bool, str]:
        """Confirms the token's identity via getMe.

        Returns (ok, detail). A failure is reported, never raised: one bot's
        bad token must not stop the other two.
        """
        try:
            me = self.client.get_me()
        except TelegramError as exc:
            self.state.last_error = exc.description
            botlog.event(self.log, self.role.bot_id, "identity.failed",
                         level=logging.ERROR, reason=exc.description,
                         permanent=exc.permanent)
            return False, exc.description
        except Exception as exc:  # network, DNS, proxy
            detail = f"{type(exc).__name__}: {exc}"
            self.state.last_error = detail
            botlog.event(self.log, self.role.bot_id, "identity.unreachable",
                         level=logging.ERROR, reason=detail)
            return False, detail

        username = me.get("username", "")
        self.username = username
        self.state.identity = f"@{username} (id {me.get('id')})"
        self.state.verified = True
        botlog.event(self.log, self.role.bot_id, "identity.verified",
                     username=username, bot_api_id=me.get("id"),
                     scenario=self.role.scenario_id)
        return True, self.state.identity

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Runs the poll loop in this thread until `stop()`."""
        try:
            self._lock.acquire()
        except LockHeld as exc:
            self.state.stopped_reason = str(exc)
            botlog.event(self.log, self.role.bot_id, "start.refused",
                         level=logging.ERROR, reason=str(exc))
            return

        try:
            ok, _ = self.verify()
            if not ok:
                self.state.stopped_reason = "identity verification failed"
                return

            self.state.running = True
            botlog.event(self.log, self.role.bot_id, "started",
                         scenario=self.role.scenario_id,
                         dry_run=self.runtime.dry_run,
                         identity=self.state.identity)
            self._poll_loop()
        finally:
            self.state.running = False
            self._lock.release()
            botlog.event(self.log, self.role.bot_id, "stopped",
                         reason=self.state.stopped_reason or "requested",
                         updates=self.state.updates_handled,
                         replies=self.state.replies, errors=self.state.errors)

    def start_background(self) -> threading.Thread:
        """Starts the bot on its own thread, isolating its failures."""

        def runner() -> None:
            try:
                self.start()
            except Exception as exc:  # must never reach the supervisor
                self.state.errors += 1
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                self.state.stopped_reason = "crashed"
                botlog.event(self.log, self.role.bot_id, "crashed",
                             level=logging.ERROR, reason=self.state.last_error)

        thread = threading.Thread(target=runner, name=self.role.bot_id, daemon=True)
        thread.start()
        self._thread = thread
        return thread

    def stop(self, reason: str = "requested") -> None:
        self.state.stopped_reason = reason
        self._stop.set()

    def join(self, timeout: float = 10.0) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    # ── polling ────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        consecutive = 0
        while not self._stop.is_set():
            try:
                updates = self.client.get_updates(
                    offset=self._offset,
                    timeout=self.runtime.poll_timeout,
                    allowed_updates=["message"],
                )
                consecutive = 0
            except TelegramError as exc:
                self.state.errors += 1
                self.state.last_error = exc.description
                botlog.event(self.log, self.role.bot_id, "poll.failed",
                             level=logging.ERROR, reason=exc.description,
                             permanent=exc.permanent)
                if exc.permanent:
                    # A revoked token or a webhook conflict will not resolve.
                    self.state.stopped_reason = f"permanent API error: {exc.description}"
                    return
                consecutive += 1
                self._sleep_backoff(consecutive)
                continue
            except Exception as exc:
                self.state.errors += 1
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                botlog.event(self.log, self.role.bot_id, "poll.error",
                             level=logging.ERROR, reason=self.state.last_error)
                consecutive += 1
                self._sleep_backoff(consecutive)
                continue

            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self._offset = update_id + 1
                try:
                    self._handle(update)
                except Exception as exc:
                    # One malformed update must not end the session.
                    self.state.errors += 1
                    self.state.last_error = f"{type(exc).__name__}: {exc}"
                    botlog.event(self.log, self.role.bot_id, "update.failed",
                                 level=logging.ERROR,
                                 reason=self.state.last_error,
                                 update_id=update_id)

    def _sleep_backoff(self, attempt: int) -> None:
        delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]
        self._stop.wait(delay)

    # ── handling ───────────────────────────────────────────────────────────

    def _handle(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return

        self.state.updates_handled += 1

        allowed, why = self.runtime.is_chat_allowed(chat_id, str(chat.get("type", "")))
        if not allowed:
            botlog.event(self.log, self.role.bot_id, "chat.refused",
                         level=logging.WARNING, chat_id=chat_id,
                         chat_type=chat.get("type"), reason=why)
            return

        # Being added to a group: introduce this bot and its lesson. Service
        # messages arrive even with Telegram privacy mode left on.
        if self._joined(message):
            self.state.active_chats.add(chat_id)
            self._reply(chat_id, self._text_intro(), None)
            return

        text = (message.get("text") or "").strip()

        if not text.startswith("/"):
            self._handle_plain(chat_id, text, message, str(chat.get("type", "")))
            return

        # In a group holding all three managers, Telegram delivers a bare
        # "/next" to every one of them. Answering a command addressed to a
        # different bot would bury the trainee in three different lessons, so
        # an explicit @name that is not ours is ignored.
        head = text.split()[0]
        command, _, addressed_to = head.partition("@")
        command = command.lower()
        if addressed_to and self.username and \
                addressed_to.lower() != self.username.lower():
            botlog.event(self.log, self.role.bot_id, "command.not_ours",
                         chat_id=chat_id, addressed_to=addressed_to,
                         command=command)
            return

        # Any command addressed to this bot makes it the active teacher here.
        self.state.active_chats.add(chat_id)

        reply = self._dispatch(command, chat_id)
        if reply is None:
            return

        self._reply(chat_id, reply, message.get("message_id"))

    def _joined(self, message: dict[str, Any]) -> bool:
        """True when this bot is among the newly added members."""
        members = message.get("new_chat_members")
        if not isinstance(members, list) or not self.username:
            return False
        return any(
            isinstance(m, dict)
            and str(m.get("username", "")).lower() == self.username.lower()
            for m in members
        )

    def _handle_plain(self, chat_id: int, text: str, message: dict[str, Any],
                      chat_type: str) -> None:
        """Answers ordinary messages — the automatic part of the training.

        In a group this runs only while this bot's lesson is active, so three
        managers in one chat do not all answer the same sentence. A reply to
        this bot's own message counts as addressed to it either way.
        """
        if not text:
            return

        replied_to = message.get("reply_to_message") or {}
        from_bot = (replied_to.get("from") or {}).get("username", "")
        is_reply_to_us = bool(self.username) and \
            str(from_bot).lower() == self.username.lower()

        if chat_type != "private" and chat_id not in self.state.active_chats \
                and not is_reply_to_us:
            return

        question = self.state.pending.pop(chat_id, None)
        if question is not None:
            self._reply(chat_id, self._grade(question, text), message.get("message_id"))
            return

        # Nothing pending: nudge rather than stay silent, so a trainee who
        # types instead of tapping is not left wondering.
        if chat_type == "private" or is_reply_to_us:
            self._reply(chat_id, self._text_nudge(), message.get("message_id"))

    def _grade(self, question: str, answer: str) -> str:
        """Checks a typed answer against the lead this bot is teaching from."""
        lead = self._lead()
        said = answer.lower()

        if question == "contact":
            wants_call = lead.contact_method == "phone"
            said_call = any(w in said for w in
                            ("qo'ng'ir", "qongir", "qo‘ng‘ir", "telefon", "call",
                             "звон", "позвон"))
            said_msg = any(w in said for w in
                           ("telegram", "yoz", "xabar", "message", "напиш", "пиш"))
            correct = (said_call and not said_msg) if wants_call else \
                      (said_msg and not said_call)
            label = prod.contact_method_label(lead.contact_method)
            if correct:
                return "\n".join([
                    "✅ <b>To'g'ri.</b>",
                    f"Arizada <b>Bog'lanish:</b> {_esc(label)} deb turibdi, "
                    f"shuning uchun {'qo‘ng‘iroq qilasiz' if wants_call else 'Telegram orqali yozasiz'}.",
                    "",
                    "Bu — arizadagi <b>yagona</b> maydon: keyingi harakatingizni "
                    "aynan shu belgilaydi.",
                    "", "<b>/next</b> — davom etish.",
                ])
            return "\n".join([
                "❌ <b>Noto'g'ri.</b>",
                f"Arizada <b>Bog'lanish:</b> {_esc(label)} deb turibdi — "
                f"demak {'qo‘ng‘iroq qilish' if wants_call else 'Telegram orqali yozish'} kerak.",
                "",
                "⚠️ Mijoz o'zi tanlagan usulni hurmat qiling. Ba'zilar "
                "Telegram'ni tanlaydi, chunki ish vaqtida qo'ng'iroqni ola olmaydi.",
                "", "<b>/next</b> — davom etish.",
            ])

        if question == "phone":
            digits = "".join(ch for ch in said if ch.isdigit())
            correct = digits.endswith("".join(
                ch for ch in lead.phone if ch.isdigit())[-9:])
            if correct:
                return ("✅ <b>To'g'ri raqam.</b> Oxirgi ☎️ qatoridagi "
                        "raqamni bosib tering — qo'lda ko'chirsangiz raqam "
                        "adashishi mumkin.\n\n<b>/next</b> — davom etish.")
            return ("❌ Bu raqam emas. Arizaning eng oxirgi ☎️ "
                    f"qatoriga qarang: <code>{_esc(lead.phone)}</code>\n\n"
                    "<b>/next</b> — davom etish.")

        return self._text_nudge()

    def _text_nudge(self) -> str:
        return "\n".join([
            f"Men <b>{_esc(self.role.display)}</b> — {_esc(self.role.scenario_id)} "
            "darsini o'rgataman.",
            "",
            "<b>/lead</b> — namunaviy ariza va savol",
            "<b>/next</b> — keyingi qadam",
            "<b>/scenario</b> — dars rejasi",
        ])

    def _dispatch(self, command: str, chat_id: int) -> str | None:
        if command in ("/start", "/help"):
            return self._text_intro()
        if command == "/whoami":
            return self._text_whoami()
        if command == "/lead":
            return self._text_lead(chat_id)
        if command == "/stop":
            self.state.active_chats.discard(chat_id)
            self.state.pending.pop(chat_id, None)
            return ("Dars to'xtatildi. Qayta boshlash uchun "
                    "<b>/start</b> yozing.")
        if command == "/scenario":
            return self._text_scenario_overview()
        if command == "/next":
            return self._text_next_step(chat_id)
        if command == "/reset":
            self.state.progress.pop(chat_id, None)
            return "Qaytadan boshlaymiz. <b>/next</b> bilan davom eting."
        if command == "/check":
            return self._text_verify_scenario()
        return (
            "Bu buyruq mavjud emas. Mavjud buyruqlar: /start /whoami /lead "
            "/scenario /next /reset /stop /check"
        )

    def _reply(self, chat_id: int, text: str, reply_to: int | None) -> None:
        try:
            sent = self.client.send_message(chat_id, text, reply_to=reply_to)
        except TelegramError as exc:
            self.state.errors += 1
            self.state.last_error = exc.description
            botlog.event(self.log, self.role.bot_id, "reply.failed",
                         level=logging.ERROR, chat_id=chat_id,
                         reason=exc.description)
            return
        self.state.replies += 1
        botlog.event(self.log, self.role.bot_id,
                     "reply.suppressed" if sent.dry_run else "reply.sent",
                     chat_id=chat_id, dry_run=sent.dry_run,
                     message_id=sent.message_id, chars=len(text))

    # ── message bodies ─────────────────────────────────────────────────────

    def _banner(self) -> str:
        mode = "DRY RUN" if self.runtime.dry_run else "LIVE"
        return (f"⚠️ <b>TEST MODE ({mode})</b> — "
                f"{_esc(self.role.display)}")

    def _text_intro(self) -> str:
        return "\n".join([
            self._banner(),
            "",
            f"Men <b>{_esc(self.role.display)}</b> — o'quv botiman.",
            f"Mening darsim: <b>{_esc(self.role.focus)}</b> "
            f"({_esc(self.role.scenario_id)}).",
            "",
            "Buyruqlar:",
            "/lead — namunaviy (sintetik) ariza",
            "/scenario — dars rejasi",
            "/next — keyingi qadam",
            "/check — dars haqiqiy kodga mos ekanini tekshirish",
            "/reset — boshidan",
            "/stop — darsni to'xtatish",
            "",
            "<i>Barcha arizalar sintetik. Raqamlarga qo'ng'iroq qilmang.</i>",
        ])

    def _text_whoami(self) -> str:
        s = self.state
        return "\n".join([
            self._banner(), "",
            f"<b>ID:</b> {_esc(self.role.bot_id)}",
            f"<b>Telegram:</b> {_esc(s.identity or 'not verified')}",
            f"<b>Scenario:</b> {_esc(self.role.scenario_id)} — {_esc(self.role.focus)}",
            f"<b>Seed:</b> {self.role.seed}",
            f"<b>Updates:</b> {s.updates_handled}  <b>Replies:</b> {s.replies}  "
            f"<b>Errors:</b> {s.errors}",
        ])

    def _lead(self):
        """This manager's lead. Fixed seed, so it is always the same one."""
        return generate(seed=self.role.seed, count=1)[0]

    def _text_lead(self, chat_id: int | None = None) -> str:
        # The bot's own banner goes first so DRY RUN vs LIVE is stated on every
        # reply, not only on the ones that happen to build it themselves.
        lead = as_test_message(self._lead(), f"{self.role.bot_id}-seed{self.role.seed}")
        question = ("\u2753 <b>Savol:</b> bu mijozga qanday bog'lanasiz — "
                    "qo'ng'iroq qilasizmi yoki Telegram orqali yozasizmi?\n"
                    "<i>Javobni shu yerga yozing.</i>")
        if chat_id is not None:
            self.state.pending[chat_id] = "contact"
        return f"{self._banner()}\n\n{lead}\n\n{question}"

    def _text_scenario_overview(self) -> str:
        sc = by_id(self.role.scenario_id)
        lines = [self._banner(), "",
                 f"<b>{_esc(sc.id)} — {_esc(sc.title)}</b>", "",
                 f"<b>Maqsad:</b> {_esc(sc.objective)}", "",
                 f"<b>Boshlang'ich holat:</b> {_esc(sc.starting_state)}", "",
                 f"<b>Qadamlar:</b> {len(sc.steps)}"]
        for n, step in enumerate(sc.steps, 1):
            lines.append(f"{n}. {_esc(step.name)}")
        lines += ["", "<b>/next</b> — birinchi qadamdan boshlash."]
        return "\n".join(lines)

    def _text_next_step(self, chat_id: int) -> str:
        sc = by_id(self.role.scenario_id)
        index = self.state.progress.get(chat_id, 0)
        if index >= len(sc.steps):
            self.state.progress[chat_id] = 0
            return ("Dars tugadi ✅ Qaytadan ko'rish uchun <b>/next</b>, "
                    "yoki <b>/check</b> bilan tekshiring.")

        step = sc.steps[index]
        self.state.progress[chat_id] = index + 1
        return "\n".join([
            self._banner(), "",
            f"<b>Qadam {index + 1}/{len(sc.steps)} — {_esc(step.name)}</b>", "",
            f"<b>Nima bo'lishi kerak:</b> {_esc(step.expected)}", "",
            f"<b>Nega:</b> {_esc(step.explanation)}", "",
            f"⚠️ <b>Keng tarqalgan xato:</b> {_esc(step.mistake)}", "",
            f"<i>Tekshirish usuli: {step.mode.value}</i>",
            "", "<b>/next</b> — davom etish.",
        ])

    def _text_verify_scenario(self) -> str:
        """Runs this manager's scenario for real and reports the outcome."""
        sc = by_id(self.role.scenario_id)
        root = prod.source_root()
        drift = prod.check_drift(root)
        ctx = Context(lead=self._lead(), source_root=root, drift=drift)
        run = RunLog(run_id=f"{self.role.bot_id}-check")
        steps = run_scenario(sc, ctx, run)

        badge = {Status.PASS: "✅", Status.FAIL: "❌",
                 Status.BLOCKED: "⚠️", Status.NOT_TESTED: "–"}
        lines = [self._banner(), "", f"<b>{_esc(sc.id)} tekshiruvi</b>"]
        if not drift.available:
            lines.append("<i>ALCANA_SOURCE_PATH o'rnatilmagan — haqiqiy kodga "
                         "nisbatan tekshirilmadi.</i>")
        elif not drift.ok:
            lines.append(f"<b>Diqqat:</b> haqiqiy kod o'zgargan "
                         f"({len(drift.mismatches)} nomuvofiqlik).")
        lines.append("")
        for n, st in enumerate(steps, 1):
            lines.append(f"{badge[st.status]} {n}. {_esc(st.step)}")
            lines.append(f"    <i>{st.mode.value} — {_esc(st.actual)}</i>")
        passed, attempted = run.score()
        lines += ["", f"<b>Natija:</b> {passed}/{attempted} "
                      f"({'NOT TESTED hisobga olinmaydi' if attempted < len(steps) else 'barchasi'})"]
        return "\n".join(lines)
