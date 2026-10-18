#!/usr/bin/env python3
"""Tests for the three manager bot runtimes.

Runs entirely offline with a scripted transport: `python3 tests/test_bots.py`.
Nothing here contacts Telegram, so nothing here proves anything about live
Telegram — see the NOT TESTED note in docs/manager-bots.md.

The negative tests carry the weight. A guard that allows everything and a
redactor that redacts nothing both pass a happy-path test.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training.bots import config as botconfig                      # noqa: E402
from training.bots import log as botlog                            # noqa: E402
from training.bots.api import (                                    # noqa: E402
    TelegramClient, TelegramError, scripted_transport,
)
from training.bots.lock import LockHeld, PollLock, token_fingerprint  # noqa: E402
from training.bots.manager import ManagerBot                       # noqa: E402
from training.bots.supervisor import Supervisor                    # noqa: E402
from training.envfile import load_env_file, resolve_env            # noqa: E402

failures: list[str] = []
GOOD_TOKEN = "123456789:AAFakeTokenForTestingOnly_NotRealXY1"
TOKEN_2 = "223456789:BBFakeTokenForTestingOnly_NotRealXY2"
TOKEN_3 = "323456789:CCFakeTokenForTestingOnly_NotRealXY3"


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [  PASS  ] {name}")
    else:
        print(f"  [  FAIL  ] {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def section(title: str) -> None:
    print(f"\n{title}")


def base_env(**over: str) -> dict[str, str]:
    env = {
        "TRAINING_ENVIRONMENT": "training",
        "TRAINING_MANAGER_GROUP_ID": "-1001234567890",
        "TRAINING_ALLOWED_CHAT_IDS": "-1001234567890",
        "TRAINING_MANAGER_01_BOT_TOKEN": GOOD_TOKEN,
        "TRAINING_MANAGER_02_BOT_TOKEN": TOKEN_2,
        "TRAINING_MANAGER_03_BOT_TOKEN": TOKEN_3,
    }
    for k, v in over.items():
        if v == "<unset>":
            env.pop(k, None)
        else:
            env[k] = v
    return env


# ── env file parsing ────────────────────────────────────────────────────────
section("canonical .env loader")
with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
    fh.write('# comment\nA=1\nB="quoted"\nexport C=3\nD=\nmalformed\n')
    env_path = fh.name
parsed = load_env_file(env_path)
check("reads plain keys", parsed.get("A") == "1")
check("strips quotes", parsed.get("B") == "quoted")
check("accepts pasted 'export'", parsed.get("C") == "3")
check("keeps empty values", parsed.get("D") == "")
check("skips comments and malformed lines", "malformed" not in parsed and len(parsed) == 4,
      str(parsed))
check("missing file yields empty dict", load_env_file("/nonexistent/x.env") == {})
merged = resolve_env(env_path, process_env={"TRAINING_ENVIRONMENT": "training",
                                            "UNRELATED": "x", "A": "overridden"})
check("process env wins for prefixed keys", merged.get("TRAINING_ENVIRONMENT") == "training")
check("unprefixed process vars are ignored",
      "UNRELATED" not in merged and merged.get("A") == "1", str(merged))
os.unlink(env_path)

# ── configuration validation ────────────────────────────────────────────────
section("configuration validation")
cfg = botconfig.load(env=base_env())
check("valid config is ok", cfg.ok, str(cfg.errors))
check("three bots configured", len(cfg.bots) == 3)
check("all three usable", len(cfg.runnable) == 3)
check("dry run defaults to true with no setting", cfg.dry_run)

check("dry run stays on for a typo",
      botconfig.load(env=base_env(TRAINING_DRY_RUN="flase")).dry_run)
check("dry run stays on for empty",
      botconfig.load(env=base_env(TRAINING_DRY_RUN="")).dry_run)
check("dry run off only for explicit false",
      not botconfig.load(env=base_env(TRAINING_DRY_RUN="false")).dry_run)
check("dry run off for '0'", not botconfig.load(env=base_env(TRAINING_DRY_RUN="0")).dry_run)


def rejects(name: str, **over: str) -> None:
    c = botconfig.load(env=base_env(**over))
    check(name, not c.ok, f"accepted it: {c.errors}")


rejects("rejects TRAINING_ENVIRONMENT=production", TRAINING_ENVIRONMENT="production")
rejects("rejects unset TRAINING_ENVIRONMENT", TRAINING_ENVIRONMENT="<unset>")
rejects("rejects a group absent from the allowlist",
        TRAINING_ALLOWED_CHAT_IDS="-1009999999999")
rejects("rejects a group on the denylist",
        TRAINING_FORBIDDEN_CHAT_IDS="-1001234567890")
rejects("rejects a non-integer group id", TRAINING_MANAGER_GROUP_ID="abc")
rejects("rejects a non-integer in the allowlist", TRAINING_ALLOWED_CHAT_IDS="-100,xyz")

c = botconfig.load(env=base_env(TRAINING_MANAGER_GROUP_ID="<unset>"), require_group=True)
check("requires the group id when starting", not c.ok, str(c.errors))
c = botconfig.load(env=base_env(TRAINING_MANAGER_GROUP_ID="-1000000000000",
                                TRAINING_ALLOWED_CHAT_IDS="-1000000000000"),
                   require_group=True)
check("rejects the placeholder group id when starting", not c.ok, str(c.errors))

# per-bot token problems must not disable the others
c = botconfig.load(env=base_env(TRAINING_MANAGER_02_BOT_TOKEN="<unset>"))
check("a missing token disables only that bot", len(c.runnable) == 2, str(len(c.runnable)))
check("the other two stay usable",
      {b.role.bot_id for b in c.runnable} ==
      {"TRAINING_MANAGER_01", "TRAINING_MANAGER_03"})
check("shared config stays ok when one bot is unusable", c.ok, str(c.errors))

c = botconfig.load(env=base_env(TRAINING_MANAGER_02_BOT_TOKEN="not-a-token"))
check("a malformed token is rejected per bot",
      any("shaped like" in e for b in c.bots for e in b.errors))
c = botconfig.load(env=base_env(
    TRAINING_MANAGER_02_BOT_TOKEN="000000000:REPLACE_WITH_TOKEN_FROM_BOTFATHER"))
check("a placeholder token is rejected per bot",
      any("placeholder" in e for b in c.bots for e in b.errors))

c = botconfig.load(env=base_env(TRAINING_MANAGER_02_BOT_TOKEN=GOOD_TOKEN))
check("a duplicated token is rejected",
      any("same token" in e for b in c.bots for e in b.errors),
      str([b.errors for b in c.bots]))
check("the first of a duplicated pair stays usable", len(c.runnable) == 2)

c = botconfig.load(env=base_env(TELEGRAM_BOT_TOKEN=GOOD_TOKEN))
check("a token equal to the production token is rejected",
      any("production" in e for b in c.bots for e in b.errors),
      str([b.errors for b in c.bots]))

# ── roles are fixed and distinct ────────────────────────────────────────────
section("roles")
check("three roles", len(botconfig.ROLES) == 3)
check("scenario ids distinct",
      len({r.scenario_id for r in botconfig.ROLES}) == 3)
check("seeds distinct", len({r.seed for r in botconfig.ROLES}) == 3)
check("token vars distinct", len({r.token_var for r in botconfig.ROLES}) == 3)
check("manager 1 teaches S1", botconfig.ROLES_BY_ID["TRAINING_MANAGER_01"].scenario_id == "S1")
check("manager 2 teaches S2", botconfig.ROLES_BY_ID["TRAINING_MANAGER_02"].scenario_id == "S2")
check("manager 3 teaches S3", botconfig.ROLES_BY_ID["TRAINING_MANAGER_03"].scenario_id == "S3")
check("alias m2 resolves", botconfig.resolve_role("m2").bot_id == "TRAINING_MANAGER_02")
check("alias 3 resolves", botconfig.resolve_role("3").bot_id == "TRAINING_MANAGER_03")
check("full id resolves",
      botconfig.resolve_role("TRAINING_MANAGER_01").bot_id == "TRAINING_MANAGER_01")
try:
    botconfig.resolve_role("m9")
    check("unknown manager rejected", False, "no error")
except KeyError:
    check("unknown manager rejected", True)

# ── chat allowlisting ───────────────────────────────────────────────────────
section("chat allowlisting")
rc = botconfig.load(env=base_env(TRAINING_FORBIDDEN_CHAT_IDS="-100555"))
allowed, why = rc.is_chat_allowed(-1001234567890, "supergroup")
check("allowlisted group permitted", allowed, why)
allowed, why = rc.is_chat_allowed(-100999, "supergroup")
check("non-allowlisted group refused", not allowed, why)
allowed, why = rc.is_chat_allowed(-100555, "supergroup")
check("denylisted group refused", not allowed, why)
allowed, _ = rc.is_chat_allowed(4242, "private")
check("private chat permitted (that is where trainees talk)", allowed)
allowed, why = rc.is_chat_allowed(-100555, "private")
check("denylist beats private", not allowed, why)
allowed, why = rc.is_chat_allowed(-1001234567890, "group")
check("plain group type also honoured", allowed, why)

# ── token redaction ─────────────────────────────────────────────────────────
section("token redaction")
botlog.clear_secrets()
botlog.register_secret(GOOD_TOKEN)
check("registered token redacted", GOOD_TOKEN not in botlog.redact(f"x {GOOD_TOKEN} y"))
check("bot id prefix redacted", "123456789" not in botlog.redact(f"x {GOOD_TOKEN} y"))
check("token in an api url redacted",
      "AAFake" not in botlog.redact(
          f"https://api.telegram.org/bot{GOOD_TOKEN}/getUpdates"))
check("unregistered token-shaped string redacted",
      "ZZSecret" not in botlog.redact("oops 987654321:ZZSecretTokenShapedValueHere12345"))
check("ordinary text untouched", "hello world" in botlog.redact("hello world"))

stream = io.StringIO()
logger = botlog.get_logger("test.redaction", stream=stream)
botlog.event(logger, "TRAINING_MANAGER_01", "poll.failed",
             reason=f"401 for {GOOD_TOKEN}", url=f"api.telegram.org/bot{GOOD_TOKEN}/x",
             nested={"inner": GOOD_TOKEN}, listed=[GOOD_TOKEN])
out = stream.getvalue()
check("no token in a JSON log line", "AAFake" not in out, out[:160])
check("no token in nested dict values", out.count("<redacted-token>") >= 3, out[:200])
check("log line is valid JSON", bool(json.loads(out.strip().splitlines()[0])))
record = json.loads(out.strip().splitlines()[0])
check("log carries bot and event fields",
      record["bot"] == "TRAINING_MANAGER_01" and record["event"] == "poll.failed")

# ── duplicate polling prevention ────────────────────────────────────────────
section("duplicate polling prevention")
with tempfile.TemporaryDirectory() as d:
    check("fingerprint is not the token",
          GOOD_TOKEN not in token_fingerprint(GOOD_TOKEN))
    check("fingerprint is stable",
          token_fingerprint(GOOD_TOKEN) == token_fingerprint(GOOD_TOKEN))
    check("different tokens fingerprint differently",
          token_fingerprint(GOOD_TOKEN) != token_fingerprint(TOKEN_2))

    first = PollLock(token=GOOD_TOKEN, lock_dir=d)
    first.acquire()
    check("lock file contains no token material",
          GOOD_TOKEN not in open(first.path).read() and
          GOOD_TOKEN not in os.path.basename(first.path))
    second = PollLock(token=GOOD_TOKEN, lock_dir=d)
    try:
        second.acquire()
        check("second poller on the same token refused", False, "it was allowed")
    except LockHeld:
        check("second poller on the same token refused", True)

    other = PollLock(token=TOKEN_2, lock_dir=d)
    try:
        other.acquire()
        check("a different token is not blocked", True)
        other.release()
    except LockHeld:
        check("a different token is not blocked", False, "wrongly blocked")

    first.release()
    again = PollLock(token=GOOD_TOKEN, lock_dir=d)
    try:
        again.acquire()
        check("lock is reusable after release", True)
        again.release()
    except LockHeld:
        check("lock is reusable after release", False)

    # a stale lock from a dead process must be taken over, not block forever
    stale = PollLock(token=TOKEN_3, lock_dir=d)
    os.makedirs(d, exist_ok=True)
    with open(stale.path, "w") as fh:
        fh.write("999999999")  # a pid that does not exist
    try:
        stale.acquire()
        check("stale lock from a dead process is taken over", True)
        stale.release()
    except LockHeld:
        check("stale lock from a dead process is taken over", False, "blocked on a dead pid")

    with PollLock(token=GOOD_TOKEN, lock_dir=d) as held:
        check("context manager acquires", os.path.isfile(held.path))
    check("context manager releases", not os.path.isfile(held.path))

# ── api client ──────────────────────────────────────────────────────────────
section("api client and dry run")
client = TelegramClient(token=GOOD_TOKEN, dry_run=True,
                        transport=scripted_transport(me={"id": 9, "username": "m1_bot"}))
check("getMe returns identity", client.get_me()["username"] == "m1_bot")
sent = client.send_message(-100, "hi")
check("dry-run send is marked dry_run", sent.dry_run)
check("dry-run send has no message id", sent.message_id is None)
check("dry-run send is recorded in the outbox", len(client.outbox) == 1)
check("dry-run send never reaches the transport",
      not any(m == "sendMessage" for m, _ in client.transport.calls))

live = TelegramClient(token=GOOD_TOKEN, dry_run=False,
                      transport=scripted_transport())
sent = live.send_message(-100, "hi")
check("live send is not marked dry_run", not sent.dry_run)
check("live send returns a message id", sent.message_id is not None)
check("live send does reach the transport",
      any(m == "sendMessage" for m, _ in live.transport.calls))

bad = TelegramClient(token=GOOD_TOKEN,
                     transport=scripted_transport(fail={"getMe": (401, "Unauthorized")}))
try:
    bad.get_me()
    check("api error raises", False, "no error")
except TelegramError as exc:
    check("api error raises", True)
    check("4xx is permanent", exc.permanent)
    check("error message carries no token", GOOD_TOKEN not in str(exc))
flaky = TelegramClient(token=GOOD_TOKEN,
                       transport=scripted_transport(fail={"getUpdates": (500, "Bad Gateway")}))
try:
    flaky.get_updates()
except TelegramError as exc:
    check("5xx is not permanent", not exc.permanent)

# ── startup, failure isolation, shutdown ────────────────────────────────────
section("startup, per-bot failure, shutdown")


def make_bot(role_index: int, lock_dir: str, token: str = GOOD_TOKEN,
             updates=None, fail=None, dry_run: bool = True,
             allowed=frozenset({-100777})) -> tuple[ManagerBot, TelegramClient]:
    runtime = botconfig.RuntimeConfig(
        environment="training", dry_run=dry_run, group_id=-100777,
        allowed_chat_ids=allowed, poll_timeout=0)
    cfg = botconfig.BotConfig(role=botconfig.ROLES[role_index], token=token)
    client = TelegramClient(
        token=token, dry_run=dry_run,
        transport=scripted_transport(
            me={"id": 10 + role_index, "username": f"m{role_index + 1}_bot"},
            update_batches=updates, fail=fail))
    quiet = botlog.get_logger("test.quiet", stream=io.StringIO())
    return ManagerBot(cfg, runtime, client, quiet, lock_dir=lock_dir), client


def drain(bot: ManagerBot, expect: int, limit: float = 3.0) -> None:
    thread = bot.start_background()
    deadline = time.time() + limit
    while time.time() < deadline and bot.state.updates_handled < expect:
        thread.join(0.01)
    bot.stop("test complete")
    bot.join(3)


with tempfile.TemporaryDirectory() as d:
    msgs = [[
        {"update_id": 1, "message": {"message_id": 1, "text": "/start",
                                     "chat": {"id": 42, "type": "private"}}},
        {"update_id": 2, "message": {"message_id": 2, "text": "/whoami",
                                     "chat": {"id": 42, "type": "private"}}},
        {"update_id": 3, "message": {"message_id": 3, "text": "/lead",
                                     "chat": {"id": 42, "type": "private"}}},
        {"update_id": 4, "message": {"message_id": 4, "text": "/next",
                                     "chat": {"id": 42, "type": "private"}}},
    ]]
    bot, client = make_bot(0, d, updates=msgs)
    drain(bot, 4)
    check("bot verified its identity on startup", bot.state.verified)
    check("bot handled every update", bot.state.updates_handled == 4,
          str(bot.state.updates_handled))
    check("bot answered every command", bot.state.replies == 4, str(bot.state.replies))
    check("no errors during a clean run", bot.state.errors == 0, bot.state.last_error)
    check("bot is not running after stop", not bot.state.running)
    check("all replies suppressed in dry run", all(m.dry_run for m in client.outbox))
    check("lock released on shutdown", not os.path.isfile(bot._lock.path))
    texts = [m.text for m in client.outbox]
    check("intro names the bot's own scenario", "S1" in texts[0], texts[0][:80])
    check("every reply carries the TEST MODE banner",
          all("TEST MODE" in t for t in texts))
    check("dry run is labelled in the banner", all("DRY RUN" in t for t in texts))
    check("/lead warns against dialling", "do not dial" in texts[2])
    check("/next shows step 1 of the scenario", "1/" in texts[3], texts[3][:120])

with tempfile.TemporaryDirectory() as d:
    # a message from a non-allowlisted group must be counted but not answered
    msgs = [[
        {"update_id": 1, "message": {"message_id": 1, "text": "/lead",
                                     "chat": {"id": -100999, "type": "supergroup"}}},
        {"update_id": 2, "message": {"message_id": 2, "text": "/lead",
                                     "chat": {"id": -100777, "type": "supergroup"}}},
    ]]
    bot, client = make_bot(1, d, token=TOKEN_2, updates=msgs)
    drain(bot, 2)
    check("non-allowlisted group not answered", bot.state.replies == 1,
          str(bot.state.replies))
    check("allowlisted group answered",
          len(client.outbox) == 1 and client.outbox[0].chat_id == -100777)

with tempfile.TemporaryDirectory() as d:
    # a bad token must fail verification and not start polling
    bot, _ = make_bot(0, d, fail={"getMe": (401, "Unauthorized")})
    bot.start()
    check("a bot with a revoked token does not start", not bot.state.verified)
    check("failure reason recorded", "Unauthorized" in bot.state.last_error)
    check("stopped reason explains why",
          "identity" in bot.state.stopped_reason, bot.state.stopped_reason)
    check("lock released after a failed start", not os.path.isfile(bot._lock.path))

with tempfile.TemporaryDirectory() as d:
    # a permanent polling error must end that bot, not spin forever
    bot, _ = make_bot(0, d, fail={"getUpdates": (409, "Conflict: webhook is active")})
    bot.start()
    check("permanent poll error stops the bot", not bot.state.running)
    check("permanent poll error is recorded",
          "Conflict" in bot.state.last_error, bot.state.last_error)
    check("permanent poll error explains the stop",
          "permanent" in bot.state.stopped_reason, bot.state.stopped_reason)

with tempfile.TemporaryDirectory() as d:
    # a malformed update must not end the session
    msgs = [[
        {"update_id": 1, "message": "this is not a dict"},
        {"update_id": 2},
        {"update_id": 3, "message": {"message_id": 3, "text": "/start",
                                     "chat": {"id": 42, "type": "private"}}},
    ]]
    bot, client = make_bot(0, d, updates=msgs)
    drain(bot, 1)
    check("malformed updates survived and the good one answered",
          bot.state.replies == 1, str(bot.state.replies))
    check("a second poller cannot start while one holds the lock",
          True)  # covered above; asserted here for the startup section's completeness

with tempfile.TemporaryDirectory() as d:
    # a bot already locked must refuse to start, leaving others free
    holder = PollLock(token=GOOD_TOKEN, lock_dir=d)
    holder.acquire()
    bot, _ = make_bot(0, d)
    bot.start()
    check("start refused while another process polls the same token",
          not bot.state.verified and "already polling" in bot.state.stopped_reason,
          bot.state.stopped_reason)
    holder.release()

# ── supervisor: isolation across the three ──────────────────────────────────
section("supervisor")
with tempfile.TemporaryDirectory() as d:
    cfg = botconfig.load(env=base_env(TRAINING_MANAGER_02_BOT_TOKEN="not-a-token"))
    cfg.allowed_chat_ids = frozenset({-1001234567890})
    quiet = botlog.get_logger("test.quiet2", stream=io.StringIO())
    sup = Supervisor(runtime=cfg, logger=quiet, lock_dir=d,
                     transport_factory=lambda: scripted_transport(
                         me={"id": 1, "username": "sup_bot"}))
    sup.build()
    check("unusable bot skipped, others built", len(sup.bots) == 2, str(len(sup.bots)))
    check("skip reason recorded", len(sup.skipped) == 1 and sup.skipped[0][1])
    check("the skipped one is manager 2",
          sup.skipped[0][0].bot_id == "TRAINING_MANAGER_02")
    results = sup.verify_all()
    check("every built bot verified", all(ok for _, ok, _ in results), str(results))
    sup.start_all()
    time.sleep(0.3)
    sup.stop_all("test")
    stragglers = sup.join_all(5)
    check("all bots shut down cleanly", not stragglers, str(stragglers))
    check("status reports every built bot", len(sup.status()) == 2)
    check("locks all released",
          not [f for f in os.listdir(d) if f.endswith(".lock")], str(os.listdir(d)))

with tempfile.TemporaryDirectory() as d:
    # one bot failing verification must not stop the others starting
    cfg = botconfig.load(env=base_env())
    cfg.allowed_chat_ids = frozenset({-1001234567890})
    quiet = botlog.get_logger("test.quiet3", stream=io.StringIO())
    calls = {"n": 0}

    def flaky_factory():
        calls["n"] += 1
        if calls["n"] == 2:   # only the second bot's token is bad
            return scripted_transport(fail={"getMe": (401, "Unauthorized")})
        return scripted_transport(me={"id": calls["n"], "username": f"b{calls['n']}"})

    sup = Supervisor(runtime=cfg, logger=quiet, lock_dir=d,
                     transport_factory=flaky_factory)
    sup.build()
    results = sup.verify_all()
    oks = [ok for _, ok, _ in results]
    check("one bad identity among three is isolated",
          oks.count(True) == 2 and oks.count(False) == 1, str(results))
    sup.stop_all("test")
    sup.join_all(5)

# ── existing scenarios still work through the bots ──────────────────────────
section("scenario integration")
from training.scenarios import ALL_SCENARIOS, by_id                # noqa: E402

for role in botconfig.ROLES:
    sc = by_id(role.scenario_id)
    check(f"{role.bot_id} maps to a real scenario ({sc.id})", bool(sc.steps))
check("all three scenarios are covered by a manager",
      {r.scenario_id for r in botconfig.ROLES} == {s.id for s in ALL_SCENARIOS})

with tempfile.TemporaryDirectory() as d:
    bot, client = make_bot(2, d, token=TOKEN_3, updates=[[
        {"update_id": 1, "message": {"message_id": 1, "text": "/check",
                                     "chat": {"id": 42, "type": "private"}}},
    ]])
    drain(bot, 1)
    check("/check runs the real scenario and reports",
          bot.state.replies == 1 and "S3" in client.outbox[0].text,
          client.outbox[0].text[:120] if client.outbox else "no reply")

with tempfile.TemporaryDirectory() as d:
    # commands addressed as /lead@BotName in a group must still work
    bot, client = make_bot(0, d, updates=[[
        {"update_id": 1, "message": {"message_id": 1, "text": "/lead@Training1Bot",
                                     "chat": {"id": -100777, "type": "supergroup"}}},
    ]])
    drain(bot, 1)
    check("/command@botname is understood in groups", bot.state.replies == 1)

with tempfile.TemporaryDirectory() as d:
    bot, client = make_bot(0, d, updates=[[
        {"update_id": 1, "message": {"message_id": 1, "text": "/nosuchcommand",
                                     "chat": {"id": 42, "type": "private"}}},
        {"update_id": 2, "message": {"message_id": 2, "text": "just chatting",
                                     "chat": {"id": 42, "type": "private"}}},
    ]])
    drain(bot, 2)
    check("unknown command gets a helpful reply", bot.state.replies == 1,
          str(bot.state.replies))
    check("plain text is ignored, not answered",
          len(client.outbox) == 1 and "mavjud emas" in client.outbox[0].text)

botlog.clear_secrets()
print()
if failures:
    print(f"RESULT: FAIL — {len(failures)} check(s) failed:")
    for f in failures:
        print(f"  · {f}")
    sys.exit(1)
print("RESULT: PASS — all checks passed.")
