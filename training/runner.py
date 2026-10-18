#!/usr/bin/env python3
"""Runs the training scenarios and prints a report.

By default nothing leaves this machine: scenarios run locally and verify
against the production source. `--post` additionally posts the rendered
synthetic notifications to the configured test group, and is refused unless
every isolation guard passes.

    python3 -m training.runner                      # run all scenarios
    python3 -m training.runner --scenario S2        # one scenario
    python3 -m training.runner --teach              # manager-facing walkthrough
    python3 -m training.runner --post               # also post to the test group

Environment:
    ALCANA_SOURCE_PATH   production checkout, for APPLICATION_INTEGRATION steps
    TRAINING_ENVIRONMENT must be "training"
    plus the TRAINING_* variables in .env.example when using --post
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from training import production as prod
from training.envfile import load_env_file
from training.leads import generate
from training.modes import Mode, RunLog, Status, Step, redact
from training.render import as_test_message
from training.scenarios import ALL_SCENARIOS, Context, by_id, run_scenario

DEFAULT_OUT = os.path.join("var", "training-runs")
API = "https://api.telegram.org"

_BADGE = {
    Status.PASS: "✓ PASS",
    Status.FAIL: "✗ FAIL",
    Status.BLOCKED: "⚠ BLOCKED",
    Status.NOT_TESTED: "– NOT TESTED",
}


class PostGuard:
    """Decides whether a synthetic message may be sent, and where.

    Fails closed. A test lead reaching the real manager group is the worst
    outcome this subsystem could produce, so every condition must hold.
    """

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.reasons: list[str] = []
        self.chat_id: int | None = None
        self.token_var = "TRAINING_MANAGER_01_BOT_TOKEN"

    def check(self) -> bool:
        e = self.env
        if e.get("TRAINING_ENVIRONMENT") != "training":
            self.reasons.append(
                "TRAINING_ENVIRONMENT must be exactly 'training' "
                f"(got {e.get('TRAINING_ENVIRONMENT') or 'unset'!r})"
            )

        raw = e.get("TRAINING_MANAGER_GROUP_ID", "").strip()
        if not raw:
            self.reasons.append("TRAINING_MANAGER_GROUP_ID is not set")
        elif raw == "-1000000000000":
            self.reasons.append("TRAINING_MANAGER_GROUP_ID is still the placeholder")
        else:
            try:
                self.chat_id = int(raw)
            except ValueError:
                self.reasons.append(f"TRAINING_MANAGER_GROUP_ID is not an integer: {raw!r}")

        allowed = {c.strip() for c in e.get("TRAINING_ALLOWED_CHAT_IDS", "").split(",") if c.strip()}
        if not allowed:
            self.reasons.append("TRAINING_ALLOWED_CHAT_IDS is empty")
        elif self.chat_id is not None and str(self.chat_id) not in allowed:
            self.reasons.append("the target group is not in TRAINING_ALLOWED_CHAT_IDS")

        # Explicit production denylist: belt and braces over the allowlist.
        forbidden = {c.strip() for c in e.get("TRAINING_FORBIDDEN_CHAT_IDS", "").split(",") if c.strip()}
        if self.chat_id is not None and str(self.chat_id) in forbidden:
            self.reasons.append(
                "the target group appears in TRAINING_FORBIDDEN_CHAT_IDS — refusing"
            )

        if not e.get(self.token_var, "").strip():
            self.reasons.append(f"{self.token_var} is not set")
        elif "REPLACE_WITH" in e[self.token_var]:
            self.reasons.append(f"{self.token_var} is still a placeholder")

        # A production token must never be reused for training.
        prod_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if prod_token and prod_token == e.get(self.token_var, "").strip():
            self.reasons.append(
                "the training token is identical to TELEGRAM_BOT_TOKEN (production) "
                "— refusing to post as the production bot"
            )

        return not self.reasons


def post_message(token: str, chat_id: int, html: str) -> tuple[bool, str]:
    """Posts one synthetic notification. Returns (ok, message_ref_or_error)."""
    body = json.dumps({
        "chat_id": chat_id,
        "text": html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"{API}/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
            return False, redact(str(payload.get("description", f"HTTP {exc.code}")))
        except Exception:
            return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, redact(f"network error: {exc.reason}")
    if not payload.get("ok"):
        return False, redact(str(payload.get("description", "unknown error")))
    mid = payload.get("result", {}).get("message_id")
    return True, f"chat={chat_id} message_id={mid}"


def print_teaching(scenario, ctx) -> None:
    """The manager-facing walkthrough."""
    from training.render import render

    print("=" * 74)
    print(f"{scenario.id} — {scenario.title}")
    print("=" * 74)
    print(f"\nObjective\n  {scenario.objective}")
    print(f"\nStarting state\n  {scenario.starting_state}")
    print("\nThe notification a manager sees:")
    print("  " + "\n  ".join(render(ctx.lead).splitlines()))
    print()
    for n, ts in enumerate(scenario.steps, 1):
        print(f"\nStep {n}/{len(scenario.steps)} — {ts.name}")
        print(f"  What should happen : {ts.expected}")
        print(f"  Why                : {ts.explanation}")
        print(f"  Common mistake     : {ts.mistake}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", help="run one scenario (S1, S2, S3)")
    ap.add_argument("--seed", type=int, default=1, help="scenario seed (default 1)")
    ap.add_argument("--teach", action="store_true",
                    help="print the manager-facing walkthrough as well")
    ap.add_argument("--post", action="store_true",
                    help="also post synthetic notifications to the test group")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--out-dir", default=DEFAULT_OUT, help=f"default: {DEFAULT_OUT}")
    args = ap.parse_args(argv)

    file_env = load_env_file(args.env_file)
    env = {**file_env, **{k: v for k, v in os.environ.items() if k.startswith("TRAINING_")}}

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-s{args.seed}"
    log = RunLog(run_id=run_id)

    scenarios = [by_id(args.scenario)] if args.scenario else ALL_SCENARIOS
    leads = generate(seed=args.seed, count=max(len(scenarios), 3))

    root = prod.source_root()
    drift = prod.check_drift(root)

    print(f"TEST MODE — training run {run_id}")
    print(f"production source : {drift.source_path or 'NOT AVAILABLE (set ALCANA_SOURCE_PATH)'}")
    if drift.available:
        if drift.ok:
            print(f"drift check       : PASS — {len(drift.checked)} fact groups match "
                  f"({', '.join(drift.checked)})")
        else:
            print(f"drift check       : FAIL — {len(drift.mismatches)} mismatch(es)")
            for m in drift.mismatches:
                print(f"                    · {m}")
            print("\nThe training material no longer matches the product. "
                  "Fix training/production.py before teaching from this.")
    else:
        print("drift check       : NOT TESTED — APPLICATION_INTEGRATION steps "
              "will be reported NOT TESTED")
    log.record(Step(
        scenario_id="-", step="production drift check",
        mode=Mode.APPLICATION_INTEGRATION,
        status=Status.PASS if drift.ok else (
            Status.NOT_TESTED if not drift.available else Status.FAIL),
        expected="mirrored product facts match the shipped source",
        actual=("matched: " + ", ".join(drift.checked)) if drift.ok else
               ("; ".join(drift.mismatches) or "source not available"),
        explanation="Ties the local reproduction to the real product.",
    ))

    # Posting is decided once, before anything is sent.
    guard = PostGuard(env)
    can_post = guard.check() if args.post else False
    if args.post and not can_post:
        print("\nposting           : REFUSED")
        for r in guard.reasons:
            print(f"                    · {r}")
        print("                    Nothing was sent.")
    elif args.post:
        print(f"posting           : enabled → chat {guard.chat_id}")

    print()
    for scenario, lead in zip(scenarios, leads):
        ctx = Context(lead=lead, source_root=root, drift=drift)
        if args.teach:
            print_teaching(scenario, ctx)
            print()

        print(f"── {scenario.id} — {scenario.title}")
        print(f"   lead {lead.test_id}  ({lead.kind}, {lead.channel}, {lead.language})")
        steps = run_scenario(scenario, ctx, log)
        for n, st in enumerate(steps, 1):
            print(f"   {_BADGE[st.status]:<14} {n}. {st.step}")
            print(f"   {'':<14}    mode={st.mode.value}  {st.actual}")
            if st.error:
                print(f"   {'':<14}    error: {st.error}")

        if args.post and can_post:
            assert guard.chat_id is not None
            ok, ref = post_message(
                env[guard.token_var], guard.chat_id, as_test_message(lead, run_id)
            )
            log.record(Step(
                scenario_id=scenario.id, step="post synthetic lead to the test group",
                mode=Mode.TELEGRAM_BOT_API,
                status=Status.PASS if ok else Status.FAIL,
                expected="the labelled synthetic notification appears in the test group",
                actual=ref if ok else "", error="" if ok else ref,
                lead_id=lead.test_id, telegram_ref=ref if ok else "",
                explanation="Real Telegram Bot API call with the training token.",
            ))
            print(f"   {_BADGE[Status.PASS if ok else Status.FAIL]:<14} "
                  f"posted to test group")
            print(f"   {'':<14}    mode=TELEGRAM_BOT_API  {ref}")
        elif args.post:
            log.record(Step(
                scenario_id=scenario.id, step="post synthetic lead to the test group",
                mode=Mode.TELEGRAM_BOT_API, status=Status.BLOCKED,
                expected="the labelled synthetic notification appears in the test group",
                actual="refused by the isolation guard: " + "; ".join(guard.reasons),
                lead_id=lead.test_id,
                explanation="Posting is refused unless every isolation guard passes.",
            ))
        else:
            log.record(Step(
                scenario_id=scenario.id, step="post synthetic lead to the test group",
                mode=Mode.TELEGRAM_BOT_API, status=Status.NOT_TESTED,
                expected="the labelled synthetic notification appears in the test group",
                actual="not attempted — pass --post to send to the configured test group",
                lead_id=lead.test_id,
                explanation="No Telegram call is made unless explicitly requested.",
            ))
        print()

    counts = log.counts()
    passed, attempted = log.score()
    print("=" * 74)
    print("Result by execution mode (how each check was actually carried out):")
    for m in Mode:
        n = sum(1 for s in log.steps if s.mode is m)
        if n:
            ps = sum(1 for s in log.steps if s.mode is m and s.status is Status.PASS)
            print(f"  {m.value:<24} {ps}/{n} passed")
    print(f"\nTotals: " + "  ".join(f"{k}={v}" for k, v in counts.items() if v))
    print(f"Score : {passed}/{attempted} attempted checks passed"
          f"{' (NOT TESTED steps are not attempts)' if counts['NOT TESTED'] else ''}")

    path = log.write(args.out_dir)
    print(f"Report: {os.path.abspath(path)}")

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
