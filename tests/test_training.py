#!/usr/bin/env python3
"""Tests for the training subsystem.

Runs with no network and no dependencies: `python3 tests/test_training.py`.

The important tests here are the negative ones. It is easy to write a drift
check that passes because it checks nothing, and a safety guard that allows
everything. Each is therefore tested against a deliberately broken input.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training import production as prod                       # noqa: E402
from training.leads import TEST_MARKER, Lead, generate        # noqa: E402
from training.modes import Mode, RunLog, Status, Step, redact  # noqa: E402
from training.render import (                                  # noqa: E402
    as_test_message, render, render_bot_lead, render_web_lead,
)
from training.runner import PostGuard                          # noqa: E402
from training.scenarios import (                               # noqa: E402
    ALL_SCENARIOS, Context, by_id, run_scenario,
)

failures: list[str] = []
SOURCE = os.environ.get("ALCANA_SOURCE_PATH", "/home/user/alcana-taplink-page")


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [  PASS  ] {name}")
    else:
        print(f"  [  FAIL  ] {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def section(title: str) -> None:
    print(f"\n{title}")


# ── phone porting ───────────────────────────────────────────────────────────
section("production helper ports")
check("E.164 passthrough", prod.normalize_uz_phone("+998901234567") == "+998901234567")
check("national number gets country code",
      prod.normalize_uz_phone("901234567") == "+998901234567")
check("formatting characters stripped",
      prod.normalize_uz_phone("+998 (90) 123-45-67") == "+998901234567")
check("unissued prefix rejected", prod.normalize_uz_phone("+998101234567") is None)
check("too short rejected", prod.normalize_uz_phone("9012345") is None)
check("empty rejected", prod.normalize_uz_phone("") is None)
check("non-string rejected", prod.normalize_uz_phone(None) is None)  # type: ignore[arg-type]
check("grouped for display",
      prod.format_uz_phone("+998901234567") == "+998 90 123 45 67")
check("non-Uzbek number returned unchanged",
      prod.format_uz_phone("+12025550123") == "+12025550123")
check("html escaped",
      prod.escape_html("<b>&'\"") == "&lt;b&gt;&amp;&#39;&quot;")
check("unknown service id falls back to the id",
      prod.service_title("no-such") == "no-such")
check("all ten services mirrored", len(prod.SERVICES) == 10, str(len(prod.SERVICES)))

# ── drift check: must FAIL on a mutated copy ────────────────────────────────
section("drift check (the negative tests are the point)")
have_source = os.path.isdir(os.path.join(SOURCE, "src"))
if not have_source:
    print("  [  SKIP  ] production checkout absent; set ALCANA_SOURCE_PATH")
else:
    real = prod.check_drift(SOURCE)
    check("real source reports available", real.available)
    check("real source has no drift", real.ok, str(real.mismatches))
    check("all seven fact groups checked", len(real.checked) == 7, str(real.checked))

    tmp = tempfile.mkdtemp()
    try:
        copy = os.path.join(tmp, "src")
        shutil.copytree(os.path.join(SOURCE, "src"), copy)

        def mutate(rel: str, old: str, new: str) -> None:
            p = os.path.join(tmp, rel)
            with open(p, encoding="utf-8") as fh:
                t = fh.read()
            assert old in t, f"fixture text not found: {old!r}"
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(t.replace(old, new, 1))

        # a renamed field label must be caught
        mutate("src/lib/telegram.ts", "<b>Xizmat:</b>", "<b>Service:</b>")
        d = prod.check_drift(tmp)
        check("renamed label detected",
              any("Xizmat" in m for m in d.mismatches), str(d.mismatches))

        # a changed service title must be caught
        mutate("src/config/site.ts", 'title: "Neon yozuvlar"', 'title: "Neon signs"')
        d = prod.check_drift(tmp)
        check("changed service title detected",
              any("neon" in m for m in d.mismatches), str(d.mismatches))

        # removing the group-silence guard must be caught: it would invalidate S3
        mutate("src/app/api/telegram/webhook/route.ts",
               'message.chat?.type !== "private"', 'false')
        d = prod.check_drift(tmp)
        check("removed group-silence guard detected",
              any("group-silence" in m for m in d.mismatches), str(d.mismatches))

        # a dropped phone prefix must be caught
        mutate("src/lib/phone.ts", '  "99",', "")
        d = prod.check_drift(tmp)
        check("changed phone prefixes detected",
              any("prefix" in m for m in d.mismatches), str(d.mismatches))

        check("a mutated source is never reported ok", not prod.check_drift(tmp).ok)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

check("absent source reports unavailable, not ok",
      prod.check_drift("/nonexistent-path").available is False)
check("absent source is not ok", not prod.check_drift("/nonexistent-path").ok)

# ── synthetic leads ─────────────────────────────────────────────────────────
section("synthetic lead generator")
a, b = generate(seed=42, count=6), generate(seed=42, count=6)
check("same seed reproduces identical leads",
      [(x.name, x.phone, x.service) for x in a] == [(x.name, x.phone, x.service) for x in b])
check("different seed differs",
      [x.name for x in generate(seed=43, count=6)] != [x.name for x in a])
check("every lead carries the test marker",
      all(TEST_MARKER in x.test_id for x in a))
check("every lead id is unique", len({x.test_id for x in a}) == len(a))
check("every phone is a valid Uzbek number",
      all(prod.normalize_uz_phone(x.phone) for x in a))
check("every phone is in the unallocated 000-00-NN block",
      all(x.phone.startswith("+99890000") for x in a), str([x.phone for x in a[:3]]))
check("every service id is real", all(x.service in prod.SERVICES for x in a))
check("every contact method is real",
      all(x.contact_method in prod.CONTACT_METHODS for x in a))
check("messages respect the production limit",
      all(x.message is None or len(x.message) <= prod.MESSAGE_MAX for x in a))
check("uz, ru and en content all generated",
      {x.language for x in generate(seed=3, count=24)} >= {"uz", "ru", "en"},
      str({x.language for x in generate(seed=3, count=24)}))

try:
    Lead(test_id="x", name="n", phone="+998101234567", service="banner",
         contact_method="phone")
    check("invalid phone rejected at construction", False, "no error raised")
except ValueError:
    check("invalid phone rejected at construction", True)

try:
    Lead(test_id="x", name="n", phone="+998901234567", service="nope",
         contact_method="phone")
    check("invalid service rejected at construction", False, "no error raised")
except ValueError:
    check("invalid service rejected at construction", True)

try:
    generate(kinds=("overdue",))
    check("invented lead kind rejected", False, "no error raised")
except ValueError as exc:
    check("invented lead kind rejected", "overdue" in str(exc))

# ── rendering ───────────────────────────────────────────────────────────────
section("notification rendering")
web = Lead(test_id="[TEST] X", name="Dilshod Karimov", phone="+998900000001",
           service="banner", contact_method="phone", message="Banner kerak",
           source="instagram")
bot = Lead(test_id="[TEST] Y", name="Nigora Yusupova", phone="+998900000002",
           service="neon", contact_method="telegram", channel="bot",
           handle="test_user", message="—")

wm, bm = render_web_lead(web), render_bot_lead(bot)
check("web heading", "Yangi ariza — ALCANA PRINT" in wm)
check("bot heading", "Yangi ariza — Telegram bot" in bm)
check("web shows the grouped phone", "+998 90 000 00 01" in wm)
check("bot shows the raw phone unformatted",
      "<b>Telefon:</b> +998900000002" in bm)
check("bot does NOT group the phone", "+998 90 000 00 02" not in bm)
check("web carries the source line", "Manba:" in wm)
check("bot carries no source line", "Manba:" not in bm)
check("bot shows the telegram handle", "@test_user" in bm)
check("bot hardcodes 'Telegram orqali'", "Telegram orqali" in bm)
check("web honours the chosen contact method",
      "Telefon qo&#39;ng&#39;irog&#39;i" in wm)
check("tappable E.164 on the last line", wm.strip().endswith("+998900000001"))
check("render() dispatches on channel",
      render(web) == wm and render(bot) == bm)

evil = Lead(test_id="[TEST] Z", name="<b>x</b>", phone="+998900000003",
            service="banner", contact_method="phone",
            message="<script>alert(1)</script>")
em = render_web_lead(evil)
check("markup in name escaped", "&lt;b&gt;x&lt;/b&gt;" in em)
check("markup in message escaped", "&lt;script&gt;" in em)
check("no raw script tag survives", "<script>" not in em)
check("only intended bold tags remain",
      em.count("<b>") == em.count("</b>") and "<b>Ism:</b>" in em)

banner = as_test_message(web, "run-test")
check("test banner present", "TEST MODE" in banner and "DO NOT ACTION" in banner)
check("test banner names the run", "run-test" in banner)
check("test banner warns against dialling", "do not dial" in banner)
check("test banner keeps the real notification", "Yangi ariza" in banner)

# ── post guard: must refuse ─────────────────────────────────────────────────
section("post guard (fails closed)")
good = {
    "TRAINING_ENVIRONMENT": "training",
    "TRAINING_MANAGER_GROUP_ID": "-1001234567890",
    "TRAINING_ALLOWED_CHAT_IDS": "-1001234567890",
    "TRAINING_MANAGER_01_BOT_TOKEN": "123456789:AAFakeTokenForTestingOnly_NotReal12",
}
check("complete config is allowed", PostGuard(dict(good)).check())


def refuses(label: str, **changes: str) -> None:
    env = dict(good)
    for k, v in changes.items():
        if v == "<unset>":
            env.pop(k, None)
        else:
            env[k] = v
    g = PostGuard(env)
    check(label, not g.check(), "guard allowed it")


refuses("refuses when TRAINING_ENVIRONMENT is production",
        TRAINING_ENVIRONMENT="production")
refuses("refuses when TRAINING_ENVIRONMENT is unset",
        TRAINING_ENVIRONMENT="<unset>")
refuses("refuses a group absent from the allowlist",
        TRAINING_ALLOWED_CHAT_IDS="-1009999999999")
refuses("refuses an empty allowlist", TRAINING_ALLOWED_CHAT_IDS="")
refuses("refuses the placeholder group id",
        TRAINING_MANAGER_GROUP_ID="-1000000000000",
        TRAINING_ALLOWED_CHAT_IDS="-1000000000000")
refuses("refuses a missing group id", TRAINING_MANAGER_GROUP_ID="<unset>")
refuses("refuses a non-numeric group id", TRAINING_MANAGER_GROUP_ID="abc")
refuses("refuses a missing token", TRAINING_MANAGER_01_BOT_TOKEN="<unset>")
refuses("refuses a placeholder token",
        TRAINING_MANAGER_01_BOT_TOKEN="000000000:REPLACE_WITH_TOKEN_FROM_BOTFATHER")
refuses("refuses a chat on the production denylist",
        TRAINING_FORBIDDEN_CHAT_IDS="-1001234567890")

# the production token must never be reusable for training
os.environ["TELEGRAM_BOT_TOKEN"] = good["TRAINING_MANAGER_01_BOT_TOKEN"]
g = PostGuard(dict(good))
check("refuses a training token identical to the production token",
      not g.check() and any("production" in r for r in g.reasons), str(g.reasons))
del os.environ["TELEGRAM_BOT_TOKEN"]

# ── scenarios ───────────────────────────────────────────────────────────────
section("scenarios")
check("three scenarios defined", len(ALL_SCENARIOS) == 3, str(len(ALL_SCENARIOS)))
check("scenario ids unique", len({s.id for s in ALL_SCENARIOS}) == 3)
check("by_id finds a scenario", by_id("s2").id == "S2")
try:
    by_id("S9")
    check("by_id rejects an unknown id", False, "no error raised")
except KeyError:
    check("by_id rejects an unknown id", True)

for s in ALL_SCENARIOS:
    check(f"{s.id} has objective, starting state and steps",
          bool(s.objective and s.starting_state and s.steps))
    check(f"{s.id} every step explains itself and names a mistake",
          all(st.expected and st.explanation and st.mistake for st in s.steps))

lead = generate(seed=1, count=1)[0]

# with the source absent, integration steps must be NOT TESTED — never PASS
ctx_none = Context(lead=lead, source_root=None, drift=prod.check_drift("/nonexistent"))
log_none = RunLog(run_id="t-none")
for s in ALL_SCENARIOS:
    run_scenario(s, ctx_none, log_none)
integration = [s for s in log_none.steps if s.mode is Mode.APPLICATION_INTEGRATION]
check("integration steps exist", len(integration) >= 6, str(len(integration)))
check("no integration step PASSes without the source",
      all(s.status is Status.NOT_TESTED for s in integration),
      str([(s.step, s.status.value) for s in integration if s.status is not Status.NOT_TESTED]))
check("simulated steps still run without the source",
      any(s.status is Status.PASS for s in log_none.steps if s.mode is Mode.SIMULATED))

if have_source:
    ctx = Context(lead=lead, source_root=SOURCE, drift=prod.check_drift(SOURCE))
    log = RunLog(run_id="t-real")
    for s in ALL_SCENARIOS:
        run_scenario(s, ctx, log)
    bad = [(s.scenario_id, s.step, s.status.value, s.actual, s.error)
           for s in log.steps if s.status is not Status.PASS]
    check("every scenario step passes against the real source", not bad, str(bad))
    passed, attempted = log.score()
    check("score counts every step as an attempt", attempted == len(log.steps))
    check("all attempted steps passed", passed == attempted, f"{passed}/{attempted}")

# a step that raises must be FAIL, never silently passed
section("failure handling")
from training.scenarios import Scenario, TrainingStep  # noqa: E402


def _boom(_ctx: Context) -> tuple[Status, str]:
    raise RuntimeError("deliberate")


broken = Scenario(id="SX", title="t", objective="o", starting_state="s", steps=[
    TrainingStep(name="raises", mode=Mode.SIMULATED, expected="e",
                 explanation="x", mistake="m", run=_boom),
])
log_b = RunLog(run_id="t-broken")
run_scenario(broken, ctx_none, log_b)
check("a raising step is recorded FAIL", log_b.steps[0].status is Status.FAIL)
check("the exception is captured", "deliberate" in log_b.steps[0].error)

# ── audit log ───────────────────────────────────────────────────────────────
section("audit log")
check("token-shaped text is redacted from audit fields",
      "<redacted-token>" in redact("fail 123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"))
log_r = RunLog(run_id="t-audit")
log_r.record(Step(scenario_id="S1", step="s", mode=Mode.SIMULATED, status=Status.PASS,
                  error="token 123456789:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB leaked"))
d = log_r.steps[0].to_dict()
check("no token survives serialisation", "BBBB" not in str(d), str(d["error"]))
check("mode and status serialise as strings",
      d["mode"] == "SIMULATED" and d["status"] == "PASS")
rd = log_r.to_dict()
check("run dict reports counts, score and modes",
      {"counts", "score", "modes", "steps", "run_id"} <= set(rd))

ln = RunLog(run_id="t-score")
ln.record(Step(scenario_id="A", step="a", mode=Mode.SIMULATED, status=Status.PASS))
ln.record(Step(scenario_id="A", step="b", mode=Mode.SIMULATED, status=Status.NOT_TESTED))
ln.record(Step(scenario_id="A", step="c", mode=Mode.SIMULATED, status=Status.FAIL))
check("NOT TESTED steps are excluded from the score", ln.score() == (1, 2), str(ln.score()))

print()
if failures:
    print(f"RESULT: FAIL — {len(failures)} check(s) failed:")
    for f in failures:
        print(f"  · {f}")
    sys.exit(1)
print(f"RESULT: PASS — all checks passed.")
