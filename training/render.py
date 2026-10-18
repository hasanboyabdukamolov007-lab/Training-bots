"""Reproduces the manager-group notification, field for field.

This is a reproduction, not the production code path: these functions are a
port of `formatLeadMessage` (src/lib/telegram.ts:55) and
`formatBotLeadMessage` (src/lib/telegram-bot.ts:140). Steps that use them are
recorded as SIMULATED.

`production.check_drift()` reads the real formatters and fails if the labels
or markers change, so the reproduction cannot silently diverge from what a
manager actually sees.

The two paths differ in ways worth teaching, and the difference is real:

  * the web form shows the phone grouped for reading (+998 90 123 45 67),
    while the bot path prints raw E.164 — `formatBotLeadMessage` does not call
    `formatUzPhone`;
  * a bot lead always reports "Telegram orqali" as the contact method, because
    the bot hardcodes it, even though the customer shared a phone number;
  * only the web form carries "Manba" (source) and "Sahifa" (page).
"""

from __future__ import annotations

from training.leads import Lead
from training.production import (
    contact_method_label,
    escape_html,
    format_uz_phone,
    service_title,
)


def format_tashkent_time(dt) -> str:
    """Port of `formatTashkentTime` (telegram.ts:39): dd/mm/yyyy, HH:MM."""
    return dt.strftime("%d/%m/%Y, %H:%M")


def render_web_lead(lead: Lead) -> str:
    """Port of `formatLeadMessage` — the web form's notification."""
    lines = [
        "\U0001F7E2 <b>Yangi ariza — ALCANA PRINT</b>",
        "",
        f"\U0001F464 <b>Ism:</b> {escape_html(lead.name)}",
        f"\U0001F4DE <b>Telefon:</b> {escape_html(format_uz_phone(lead.phone))}",
        f"\U0001F9E9 <b>Xizmat:</b> {escape_html(service_title(lead.service))}",
        f"\U0001F4F2 <b>Bog'lanish:</b> "
        f"{escape_html(contact_method_label(lead.contact_method))}",
    ]

    if lead.message:
        lines += ["", "\U0001F4AC <b>Loyiha haqida:</b>", escape_html(lead.message)]

    lines += [
        "",
        f"\U0001F552 <b>Vaqt:</b> "
        f"{escape_html(format_tashkent_time(lead.received_at))} (Toshkent)",
    ]

    if lead.source:
        lines.append(f"\U0001F517 <b>Manba:</b> {escape_html(lead.source)}")
    if lead.page_url:
        lines.append(f"\U0001F4C4 <b>Sahifa:</b> {escape_html(lead.page_url)}")

    # A bare E.164 number is tappable in Telegram; a tel: link is not.
    lines += ["", f"☎️ {escape_html(lead.phone)}"]

    return "\n".join(lines)


def render_bot_lead(lead: Lead) -> str:
    """Port of `formatBotLeadMessage` — the 4-step conversation's notification."""
    lines = [
        "\U0001F916 <b>Yangi ariza — Telegram bot</b>",
        "",
        f"\U0001F464 <b>Ism:</b> {escape_html(lead.name)}",
        # Deliberately unformatted: production does not call formatUzPhone here.
        f"\U0001F4DE <b>Telefon:</b> {escape_html(lead.phone)}",
        f"\U0001F9E9 <b>Xizmat:</b> {escape_html(service_title(lead.service))}",
        # Hardcoded to "telegram" in production, whatever the customer chose.
        f"\U0001F4F2 <b>Bog'lanish:</b> {escape_html(contact_method_label('telegram'))}",
    ]

    if lead.handle:
        lines.append(f"\U0001F4AC <b>Telegram:</b> @{escape_html(lead.handle)}")

    lines += ["", "\U0001F4AC <b>Loyiha haqida:</b>",
              escape_html(lead.message or "—")]
    lines += [
        "",
        f"\U0001F552 <b>Vaqt:</b> "
        f"{escape_html(format_tashkent_time(lead.received_at))} (Toshkent)",
    ]
    lines += ["", f"☎️ {escape_html(lead.phone)}"]

    return "\n".join(lines)


def render(lead: Lead) -> str:
    """Renders whichever notification the lead's channel would produce."""
    return render_bot_lead(lead) if lead.channel == "bot" else render_web_lead(lead)


def as_test_message(lead: Lead, run_id: str) -> str:
    """Wraps a rendered notification in an unmissable training banner.

    Only this wrapped form is ever posted to a test group, so a message in a
    chat can always be traced to its run and can never be mistaken for a real
    lead.
    """
    return "\n".join([
        "⚠️ <b>TEST MODE — SYNTHETIC LEAD, DO NOT ACTION</b>",
        f"<i>run {escape_html(run_id)} · {escape_html(lead.test_id)} · "
        f"do not dial this number</i>",
        "─" * 18,
        "",
        render(lead),
    ])
