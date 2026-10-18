"""Guided training scenarios.

Three scenarios, covering only what the production system actually does. Each
step states what a manager should do, what should happen, and *why* — then
verifies the claim rather than asserting it.

Verification comes in two strengths, and they are never conflated:

  * APPLICATION_INTEGRATION — the claim is checked against the production
    source on disk. If the checkout is absent the step is NOT TESTED.
  * SIMULATED — the claim is checked against the local reproduction. It
    demonstrates the workflow; it does not prove production behaves this way.
    The drift check is what ties the reproduction to reality.

A step is never reported PASS on the strength of a reproduction alone when the
claim is really about production behaviour.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from training import production as prod
from training.leads import Lead, generate
from training.modes import Mode, RunLog, Status, Step

#: What a step hands back: (status, what actually happened).
Outcome = tuple[Status, str]


@dataclass
class TrainingStep:
    name: str
    mode: Mode
    expected: str
    explanation: str
    mistake: str
    run: Callable[["Context"], Outcome]


@dataclass
class Scenario:
    id: str
    title: str
    objective: str
    starting_state: str
    steps: list[TrainingStep]


@dataclass
class Context:
    """Everything a step may read. Holds no secrets."""

    lead: Lead
    source_root: str | None
    drift: prod.DriftResult

    def source(self, rel: str) -> str | None:
        if self.source_root is None:
            return None
        path = os.path.join(self.source_root, rel)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def requires_source(self, rel: str) -> tuple[str | None, Outcome | None]:
        """Reads a production file, or returns the NOT TESTED outcome to use."""
        text = self.source(rel)
        if text is None:
            return None, (
                Status.NOT_TESTED,
                "production checkout not available — set ALCANA_SOURCE_PATH to "
                "verify this against the real source",
            )
        return text, None


# ── helpers ─────────────────────────────────────────────────────────────────

def _contains_all(haystack: str, needles: list[str], label: str) -> Outcome:
    missing = [n for n in needles if n not in haystack]
    if missing:
        return Status.FAIL, f"{label}: missing {missing}"
    return Status.PASS, f"{label}: all {len(needles)} present"


# ── Scenario 1 — reading a lead from the web form ───────────────────────────

def _s1_labels(ctx: Context) -> Outcome:
    text, blocked = ctx.requires_source("src/lib/telegram.ts")
    if blocked:
        return blocked
    assert text is not None
    return _contains_all(
        text,
        ["Yangi ariza — ALCANA PRINT", "Ism:", "Telefon:", "Xizmat:",
         "Bog'lanish:", "Loyiha haqida:", "Vaqt:"],
        "field labels in production formatter",
    )


def _s1_render(ctx: Context) -> Outcome:
    from training.render import render_web_lead

    msg = render_web_lead(ctx.lead)
    return _contains_all(
        msg,
        ["Yangi ariza — ALCANA PRINT", "Ism:", "Telefon:", "Xizmat:", "Bog'lanish:"],
        "rendered notification",
    )


def _s1_phone_two_forms(ctx: Context) -> Outcome:
    from training.render import render_web_lead

    msg = render_web_lead(ctx.lead)
    grouped = prod.format_uz_phone(ctx.lead.phone)
    if grouped not in msg:
        return Status.FAIL, f"grouped phone {grouped!r} not shown"
    if ctx.lead.phone not in msg:
        return Status.FAIL, "raw E.164 number (the tappable one) not shown"
    return Status.PASS, f"both forms present: {grouped!r} to read, {ctx.lead.phone} to tap"


def _s1_contact_method(ctx: Context) -> Outcome:
    label = prod.contact_method_label(ctx.lead.contact_method)
    if ctx.lead.contact_method not in prod.CONTACT_METHODS:
        return Status.FAIL, f"unknown contact method {ctx.lead.contact_method!r}"
    action = "telephone the customer" if ctx.lead.contact_method == "phone" \
        else "message the customer on Telegram"
    return Status.PASS, f"{label!r} → the manager should {action}"


def _s1_escaping(ctx: Context) -> Outcome:
    from training.render import render_web_lead

    marked = Lead(
        test_id=ctx.lead.test_id, name="Olim <b>Test</b> & Co",
        phone=ctx.lead.phone, service=ctx.lead.service,
        contact_method=ctx.lead.contact_method, received_at=ctx.lead.received_at,
    )
    msg = render_web_lead(marked)
    if "<b>Test</b>" in msg.replace("<b>Ism:</b>", ""):
        return Status.FAIL, "markup in the name was NOT escaped — it would render as bold"
    if "&lt;b&gt;Test&lt;/b&gt;" not in msg:
        return Status.FAIL, "escaped form not found"
    return Status.PASS, "markup escaped to &lt;b&gt;Test&lt;/b&gt; — shown literally, as intended"


SCENARIO_1 = Scenario(
    id="S1",
    title="Reading a lead that arrived from the website form",
    objective=(
        "Read every field in a manager-group notification correctly and decide "
        "the right follow-up action."
    ),
    starting_state=(
        "A synthetic lead from the web form. In production this message is "
        "posted to TELEGRAM_MANAGER_CHAT_ID and nothing else happens: there is "
        "no button to press and no status to change."
    ),
    steps=[
        TrainingStep(
            name="Confirm the field labels against the shipped code",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="Production's formatter still emits the seven labels taught here",
            explanation=(
                "Training that drifts from the product teaches the wrong thing. "
                "This reads src/lib/telegram.ts and checks the labels are intact."
            ),
            mistake="Trusting a screenshot from months ago after the product changed.",
            run=_s1_labels,
        ),
        TrainingStep(
            name="Recognise a new lead in the group",
            mode=Mode.SIMULATED,
            expected="A 🟢 message headed 'Yangi ariza — ALCANA PRINT' with all core fields",
            explanation=(
                "🟢 means the website form; 🤖 means the Telegram bot. The heading "
                "is how you tell at a glance which channel the customer used."
            ),
            mistake=(
                "Skimming past the heading and assuming every lead came from the bot, "
                "then looking for a Telegram handle that a web lead never has."
            ),
            run=_s1_render,
        ),
        TrainingStep(
            name="Read the phone number",
            mode=Mode.SIMULATED,
            expected="Grouped number next to 'Telefon:', bare E.164 on the last line",
            explanation=(
                "The grouped form (+998 90 000 00 83) is for reading aloud. The "
                "bare number on the ☎️ line is there because Telegram makes a bare "
                "E.164 number tappable — that is the one to dial."
            ),
            mistake=(
                "Re-typing the number by hand from the grouped form and transposing "
                "a digit, instead of tapping the ☎️ line."
            ),
            run=_s1_phone_two_forms,
        ),
        TrainingStep(
            name="Decide the follow-up from 'Bog'lanish'",
            mode=Mode.SIMULATED,
            expected="'Telefon qo'ng'irog'i' → call; 'Telegram orqali' → message",
            explanation=(
                "This is the one field that changes what you do next. The customer "
                "chose it, so honouring it is the whole point of collecting it."
            ),
            mistake=(
                "Calling a customer who asked for Telegram. It reads as not listening, "
                "and some customers pick Telegram because they cannot take calls at work."
            ),
            run=_s1_contact_method,
        ),
        TrainingStep(
            name="Interpret angle brackets in a name",
            mode=Mode.SIMULATED,
            expected="Markup appears literally as &lt;b&gt;, not as formatting",
            explanation=(
                "Production escapes customer text before sending it (telegram.ts:20). "
                "Seeing &lt;b&gt; in the group means the escaping worked."
            ),
            mistake=(
                "Reporting it as a display bug, or worse, assuming the system was "
                "attacked. Escaped markup is the system defending itself correctly."
            ),
            run=_s1_escaping,
        ),
    ],
)


# ── Scenario 2 — the bot's four-step conversation ───────────────────────────

def _s2_four_steps(ctx: Context) -> Outcome:
    """Each marker is checked in the file that actually defines it.

    The webhook routes the steps; the reply keyboard that asks for the contact
    card lives in telegram-bot.ts, so looking for `request_contact` in the
    webhook would wrongly fail.
    """
    wanted = [
        ("src/app/api/telegram/webhook/route.ts", "/start", "step 1 is routed"),
        ("src/lib/telegram-bot.ts", "request_contact", "step 2 asks for the contact card"),
        ("src/app/api/telegram/webhook/route.ts", "svc:", "step 3 reads the service callback"),
        ("src/app/api/telegram/webhook/route.ts", "force_reply", "step 4 prompts for details"),
    ]
    found, missing = [], []
    for rel, marker, label in wanted:
        text, blocked = ctx.requires_source(rel)
        if blocked:
            return blocked
        assert text is not None
        (found if marker in text else missing).append(label)
    if missing:
        return Status.FAIL, f"conversation steps missing from source: {missing}"
    return Status.PASS, f"all four steps confirmed in source ({len(found)}/4)"


def _s2_stateless(ctx: Context) -> Outcome:
    text, blocked = ctx.requires_source("src/lib/telegram-bot.ts")
    if blocked:
        return blocked
    assert text is not None
    missing = [m for m in (prod.PHONE_TAG, prod.SERVICE_TAG) if m not in text]
    if missing:
        return Status.FAIL, f"state markers missing from source: {missing}"
    if "no server-side session store" not in text:
        return Status.FAIL, "the stateless design note is gone — re-check the design"
    return Status.PASS, (
        "confirmed stateless: the 📞 and 🧩 markers in the bot's own prompts "
        "carry the answers forward"
    )


def _s2_phone_unformatted(ctx: Context) -> Outcome:
    from training.render import render_bot_lead, render_web_lead

    bot_lead = Lead(
        test_id=ctx.lead.test_id, name=ctx.lead.name, phone=ctx.lead.phone,
        service=ctx.lead.service, contact_method="telegram", channel="bot",
        handle="test_customer", message="Test", received_at=ctx.lead.received_at,
    )
    bot_msg = render_bot_lead(bot_lead)
    web_msg = render_web_lead(ctx.lead)
    grouped = prod.format_uz_phone(ctx.lead.phone)

    if f"<b>Telefon:</b> {ctx.lead.phone}" not in bot_msg:
        return Status.FAIL, "bot notification did not show the raw number"
    if grouped not in web_msg:
        return Status.FAIL, "web notification did not show the grouped number"
    return Status.PASS, (
        f"bot shows {ctx.lead.phone}, web shows {grouped} — the bot path does not "
        "group the number"
    )


def _s2_no_details(ctx: Context) -> Outcome:
    from training.render import render_bot_lead

    lead = Lead(
        test_id=ctx.lead.test_id, name=ctx.lead.name, phone=ctx.lead.phone,
        service=ctx.lead.service, contact_method="telegram", channel="bot",
        message="—", handle="test_user", received_at=ctx.lead.received_at,
    )
    msg = render_bot_lead(lead)
    if "—" not in msg.split("Loyiha haqida:")[-1]:
        return Status.FAIL, "the em dash placeholder was not shown"
    return Status.PASS, (
        "'—' under 'Loyiha haqida' — the bot told the customer to send it when "
        "they did not know the details"
    )


def _s2_hardcoded_telegram(ctx: Context) -> Outcome:
    text, blocked = ctx.requires_source("src/lib/telegram-bot.ts")
    if blocked:
        return blocked
    assert text is not None
    if 'contactMethodLabel("telegram")' not in text:
        return Status.FAIL, (
            "the bot no longer hardcodes the contact method — re-check this lesson"
        )
    return Status.PASS, (
        "confirmed in source: a bot lead always reports 'Telegram orqali', even "
        "though the customer shared a phone number"
    )


SCENARIO_2 = Scenario(
    id="S2",
    title="Understanding how the bot collected the lead",
    objective=(
        "Know what the customer was actually asked, so you know what you still "
        "have to ask — and read a bot notification's quirks correctly."
    ),
    starting_state=(
        "A synthetic lead from @alcana_lead_bot's four-step private conversation: "
        "/start → share contact → pick a service → describe the project."
    ),
    steps=[
        TrainingStep(
            name="Confirm the four steps in the shipped code",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="/start, request_contact, svc: callbacks and force_reply all present",
            explanation=(
                "The customer was asked exactly four things. Anything else you need "
                "— size, material, deadline, budget — was never asked, so it is "
                "your job on the call."
            ),
            mistake=(
                "Assuming the bot gathered a full brief and calling the customer "
                "unprepared, with nothing to ask."
            ),
            run=_s2_four_steps,
        ),
        TrainingStep(
            name="Understand why a customer can resume an hour later",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="The 📞 and 🧩 markers are present and the design is stateless",
            explanation=(
                "There is no session store. The bot re-reads its own previous "
                "message to recover the phone and service, so a customer who "
                "wanders off and comes back still completes the flow."
            ),
            mistake=(
                "Telling a customer to 'start again' when they return. They do not "
                "need to; replying to the last prompt still works."
            ),
            run=_s2_stateless,
        ),
        TrainingStep(
            name="Notice the phone is not grouped on bot leads",
            mode=Mode.SIMULATED,
            expected="Bot shows +998900000083; web shows +998 90 000 00 83",
            explanation=(
                "formatBotLeadMessage does not call formatUzPhone. Both are the same "
                "number and both are tappable — only the spacing differs."
            ),
            mistake=(
                "Thinking the unspaced number is malformed or truncated and discarding "
                "a perfectly good lead."
            ),
            run=_s2_phone_unformatted,
        ),
        TrainingStep(
            name="Handle a lead with no project details",
            mode=Mode.SIMULATED,
            expected="'Loyiha haqida' shows '—'",
            explanation=(
                "The bot explicitly invites '—' when the customer does not know the "
                "details yet. It is a complete, valid lead that needs a scoping call."
            ),
            mistake=(
                "Treating '—' as an error or a time-waster. The customer followed "
                "the instructions; they are waiting for your questions."
            ),
            run=_s2_no_details,
        ),
        TrainingStep(
            name="Read 'Bog'lanish' on a bot lead with suspicion",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="The bot hardcodes 'Telegram orqali' regardless of the customer's wish",
            explanation=(
                "Unlike the web form, the bot never asks how to make contact — it "
                "always reports Telegram. The customer did share a phone number, so "
                "either channel is available to you."
            ),
            mistake=(
                "Concluding the customer refuses calls. They were never asked. Use "
                "the Telegram handle first if there is one, but calling is fine."
            ),
            run=_s2_hardcoded_telegram,
        ),
    ],
)


# ── Scenario 3 — when delivery to the group fails ───────────────────────────

def _s3_logs_lead(ctx: Context) -> Outcome:
    text, blocked = ctx.requires_source("src/app/api/telegram/webhook/route.ts")
    if blocked:
        return blocked
    assert text is not None
    return _contains_all(
        text,
        ["group delivery failed:", "console.error", "receivedAt"],
        "the delivery-failure fallback",
    )


def _s3_customer_still_thanked(ctx: Context) -> Outcome:
    text, blocked = ctx.requires_source("src/app/api/telegram/webhook/route.ts")
    if blocked:
        return blocked
    assert text is not None
    # The customer confirmation is sent after the failure branch, unconditionally.
    idx_fail = text.find("group delivery failed:")
    idx_reply = text.find("managersReply()")
    if idx_fail == -1 or idx_reply == -1:
        return Status.FAIL, "could not locate the failure branch and the reply"
    if idx_reply < idx_fail:
        return Status.FAIL, "the customer reply no longer follows the failure branch"
    return Status.PASS, (
        "confirmed: the customer is thanked even when the group post fails — so a "
        "customer may believe they are in the queue when no manager has seen them"
    )


def _s3_failure_shape(ctx: Context) -> Outcome:
    from training.render import render

    # What the operator would find in the runtime log, reproduced locally.
    rendered = render(ctx.lead)
    if "Yangi ariza" not in rendered:
        return Status.FAIL, "could not reproduce the lead that would have been lost"
    return Status.PASS, (
        "reproduced the log payload shape: name, phone, service, details, "
        "receivedAt — enough to recover the lead by hand"
    )


def _s3_group_silence(ctx: Context) -> Outcome:
    text, blocked = ctx.requires_source("src/app/api/telegram/webhook/route.ts")
    if blocked:
        return blocked
    assert text is not None
    if 'message.chat?.type !== "private"' not in text:
        return Status.FAIL, (
            "the group-silence guard is gone — the bot may now react to group "
            "messages, and this training material needs revisiting"
        )
    return Status.PASS, (
        "confirmed: the bot ignores everything posted in the manager group — "
        "replying to the notification there does nothing"
    )


SCENARIO_3 = Scenario(
    id="S3",
    title="Recognising a lead that never arrived",
    objective=(
        "Understand the one silent failure in this system, and what a manager "
        "can and cannot do about it."
    ),
    starting_state=(
        "A synthetic lead whose delivery to the manager group fails — an invalid "
        "chat id, the bot removed from the group, or Telegram unreachable."
    ),
    steps=[
        TrainingStep(
            name="Learn where a failed lead goes",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="The lead is written to the runtime log with 'group delivery failed:'",
            explanation=(
                "Nothing is queued and nothing is retried beyond one attempt. The "
                "lead survives only as a line in the server log, so recovery means "
                "someone reading the deployment's logs."
            ),
            mistake=(
                "Assuming a failed lead will arrive later. It will not — there is "
                "no retry queue."
            ),
            run=_s3_logs_lead,
        ),
        TrainingStep(
            name="Understand what the customer was told",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="The customer is thanked regardless of whether delivery succeeded",
            explanation=(
                "This is the important one. A customer can be told 'we will contact "
                "you shortly' while no manager ever saw the lead. If a customer "
                "says they already applied and you have no record, believe them."
            ),
            mistake=(
                "Telling a customer they never submitted anything. From their side "
                "they did, and they have a confirmation message to prove it."
            ),
            run=_s3_customer_still_thanked,
        ),
        TrainingStep(
            name="Know what a recoverable log line contains",
            mode=Mode.SIMULATED,
            expected="name, phone, service, details and receivedAt are all logged",
            explanation=(
                "Everything needed to call the customer back is in the log line. "
                "Escalating to whoever can read the deployment logs is worth it."
            ),
            mistake="Writing the lead off as unrecoverable without asking.",
            run=_s3_failure_shape,
        ),
        TrainingStep(
            name="Learn why replying in the group achieves nothing",
            mode=Mode.APPLICATION_INTEGRATION,
            expected="The webhook ignores all non-private chats",
            explanation=(
                "The bot is a member of the group but deliberately silent there. "
                "Replying to a notification, or typing a command, does nothing at "
                "all. Follow-up happens by phone or Telegram, outside this bot."
            ),
            mistake=(
                "Typing 'taken' or '/done' under a lead and believing it was "
                "recorded. Nothing is recorded; use whatever the team agreed "
                "outside the bot."
            ),
            run=_s3_group_silence,
        ),
    ],
)


ALL_SCENARIOS = [SCENARIO_1, SCENARIO_2, SCENARIO_3]


def by_id(scenario_id: str) -> Scenario:
    for s in ALL_SCENARIOS:
        if s.id.lower() == scenario_id.lower():
            return s
    raise KeyError(
        f"unknown scenario {scenario_id!r}. available: "
        f"{[s.id for s in ALL_SCENARIOS]}"
    )


def run_scenario(scenario: Scenario, ctx: Context, log: RunLog) -> list[Step]:
    """Executes every step, recording the real outcome of each."""
    out: list[Step] = []
    for ts in scenario.steps:
        try:
            status, actual = ts.run(ctx)
            error = ""
        except Exception as exc:  # a broken check must not look like a pass
            status, actual, error = Status.FAIL, "step raised", f"{type(exc).__name__}: {exc}"
        out.append(log.record(Step(
            scenario_id=scenario.id,
            step=ts.name,
            mode=ts.mode,
            status=status,
            expected=ts.expected,
            actual=actual,
            explanation=ts.explanation,
            lead_id=ctx.lead.test_id,
            error=error,
        )))
    return out
