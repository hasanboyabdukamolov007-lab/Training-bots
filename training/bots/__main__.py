"""CLI for the three manager bots.

    python3 -m training.bots verify           # getMe for all three
    python3 -m training.bots start-all        # start all three
    python3 -m training.bots start m1         # start one
    python3 -m training.bots status           # config and role summary
    python3 -m training.bots self-test        # full runtime, offline, no network

Dry run is on unless TRAINING_DRY_RUN=false is set explicitly, so no message is
sent until that is done deliberately.
"""

from __future__ import annotations

import argparse
import sys

from training.bots import config as botconfig
from training.bots import log as botlog
from training.bots.api import scripted_transport
from training.bots.supervisor import Supervisor

OK, WARN, BAD, SKIP = "✓", "⚠", "✗", "–"


def _print_config(cfg: botconfig.RuntimeConfig) -> None:
    print(f"environment : {cfg.environment or '(unset)'}")
    print(f"dry run     : {cfg.dry_run}"
          f"{'  (no message will be sent)' if cfg.dry_run else '  ** LIVE — messages WILL be sent **'}")
    print(f"test group  : {cfg.group_id if cfg.group_id is not None else '(unset)'}")
    print(f"allowlist   : {sorted(cfg.allowed_chat_ids) or '(empty)'}")
    print(f"denylist    : {sorted(cfg.forbidden_chat_ids) or '(empty)'}")
    if cfg.errors:
        print("\nconfiguration errors:")
        for e in cfg.errors:
            print(f"  {BAD} {e}")
    print("\nbots:")
    for b in cfg.bots:
        if b.ok:
            print(f"  {OK} {b.role.bot_id:<20} {b.role.scenario_id}  "
                  f"seed {b.role.seed}  {b.role.focus}")
        else:
            print(f"  {BAD} {b.role.bot_id:<20} {'; '.join(b.errors)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m training.bots", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command",
                    choices=["status", "verify", "start", "start-all", "self-test"])
    ap.add_argument("which", nargs="*", help="manager(s) for 'start': m1, m2, m3")
    ap.add_argument("--env-file", default=".env")
    args = ap.parse_args(argv)

    logger = botlog.get_logger()
    needs_group = args.command in ("start", "start-all")
    cfg = botconfig.load(args.env_file, require_group=needs_group)
    for bot in cfg.bots:
        if bot.token:
            botlog.register_secret(bot.token)

    if args.command == "status":
        _print_config(cfg)
        if not cfg.runnable:
            print("\nNo bot is startable yet — fill in the tokens in .env.")
        # Non-zero when not ready, so a setup script can test for it.
        return 0 if (cfg.ok and cfg.runnable) else 1

    if args.command == "self-test":
        return _self_test(cfg, logger)

    if not cfg.ok:
        print("Refusing to continue — configuration is not valid:\n")
        _print_config(cfg)
        return 1

    only: list[str] | None = None
    if args.command == "start":
        if not args.which:
            print("Which manager? e.g. 'start m1'. Use 'start-all' for all three.")
            return 2
        try:
            only = [botconfig.resolve_role(w).bot_id for w in args.which]
        except KeyError as exc:
            print(exc)
            return 2

    sup = Supervisor(runtime=cfg, logger=logger)
    sup.build(only=only)

    if not sup.bots:
        print("No bot is startable.")
        for role, errors in sup.skipped:
            print(f"  {BAD} {role.bot_id}: {'; '.join(errors)}")
        return 1

    if args.command == "verify":
        print(f"Verifying {len(sup.bots)} bot identity(ies) via getMe\n")
        results = sup.verify_all()
        for bot_id, ok, detail in results:
            print(f"  {OK if ok else BAD} {bot_id:<20} {detail}")
        for role, errors in sup.skipped:
            print(f"  {SKIP} {role.bot_id:<20} not configured: {'; '.join(errors)}")
        return 0 if all(ok for _, ok, _ in results) else 1

    # start / start-all
    _print_config(cfg)
    print(f"\nStarting {len(sup.bots)} bot(s). Ctrl-C to stop.\n")
    sup.install_signal_handlers()
    sup.start_all()
    try:
        sup.wait()
    except KeyboardInterrupt:
        sup.stop_all("keyboard interrupt")
    finally:
        sup.stop_all()
        sup.join_all()

    print("\nfinal status:")
    any_error = False
    for snap in sup.status():
        mark = OK if snap["verified"] and not snap["errors"] else (
            WARN if snap["verified"] else BAD)
        any_error = any_error or bool(snap["errors"]) or not snap["verified"]
        print(f"  {mark} {snap['bot']:<20} {snap['identity']:<28} "
              f"updates={snap['updates']} replies={snap['replies']} "
              f"errors={snap['errors']}")
        if snap["stopped_reason"]:
            print(f"    {'':<20} stopped: {snap['stopped_reason']}")
        if snap["last_error"]:
            print(f"    {'':<20} last error: {snap['last_error']}")
    return 1 if any_error else 0


def _self_test(cfg: botconfig.RuntimeConfig, logger) -> int:
    """Drives the full runtime with a scripted transport. No network at all.

    Exists because this environment cannot reach api.telegram.org: it proves
    the poll loop, dispatch and dry-run suppression work end to end without
    claiming anything about live Telegram.
    """
    import tempfile

    from training.bots.config import ROLES, BotConfig, RuntimeConfig

    print("Self-test: full runtime against a scripted transport (no network)\n")

    runtime = RuntimeConfig(
        environment="training", dry_run=True, group_id=-100777,
        allowed_chat_ids=frozenset({-100777}), poll_timeout=0,
    )
    role = ROLES[0]
    bot_cfg = BotConfig(role=role,
                        token="123456789:SelfTestTokenNotRealAAAAAAAAAAAAAAAA")

    updates = [[
        {"update_id": 1, "message": {"message_id": 1, "text": "/start",
                                     "chat": {"id": 4242, "type": "private"}}},
        {"update_id": 2, "message": {"message_id": 2, "text": "/scenario",
                                     "chat": {"id": 4242, "type": "private"}}},
        {"update_id": 3, "message": {"message_id": 3, "text": "/next",
                                     "chat": {"id": 4242, "type": "private"}}},
        {"update_id": 4, "message": {"message_id": 4, "text": "/lead",
                                     "chat": {"id": -100999, "type": "supergroup"}}},
    ]]

    from training.bots.api import TelegramClient
    from training.bots.manager import ManagerBot

    with tempfile.TemporaryDirectory() as lock_dir:
        client = TelegramClient(
            token=bot_cfg.token,
            transport=scripted_transport(
                me={"id": 55, "username": "selftest_m1_bot", "is_bot": True},
                update_batches=updates),
            dry_run=True)
        bot = ManagerBot(bot_cfg, runtime, client, logger, lock_dir=lock_dir)
        thread = bot.start_background()
        # The scripted transport returns no further updates; stop once drained.
        for _ in range(200):
            if bot.state.updates_handled >= 4:
                break
            thread.join(0.02)
        bot.stop("self-test complete")
        bot.join(5)

    s = bot.state
    checks = [
        ("identity verified via getMe", s.verified),
        ("identity recorded", "selftest_m1_bot" in s.identity),
        ("all four updates handled", s.updates_handled == 4),
        ("three private commands answered", s.replies == 3),
        ("non-allowlisted group refused", s.replies == 3 and s.updates_handled == 4),
        ("no errors", s.errors == 0),
        ("every reply suppressed by dry run",
         all(m.dry_run for m in client.outbox) and len(client.outbox) == 3),
        ("nothing reached the transport",
         not any(m == "sendMessage" for m, _ in client.transport.calls)),
        ("bot stopped cleanly", not s.running),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {OK if ok else BAD} {name}")
    print(f"\nstate: {s.snapshot()}")
    if failed:
        print(f"\nRESULT: FAIL — {failed}")
        return 1
    print("\nRESULT: PASS — runtime works end to end; no message was sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
