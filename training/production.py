"""Facts mirrored from the production system, plus a drift check.

Everything here is a transcription of
`hasanboyabdukamolov007-lab/Alcana-taplink-page` at commit `9c701bb`. A
transcription can go stale, so `check_drift()` reads the real source files and
reports any mismatch. The training run calls it first: if the source is
available the facts are confirmed as APPLICATION_INTEGRATION, and if it is
absent every dependent step is reported NOT TESTED rather than PASS.

Source of each fact is given in `SOURCES` so a reader can verify it by hand.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

SOURCES = {
    "services": "src/config/site.ts:123-134",
    "contact_methods": "src/config/site.ts:146-149",
    "phone_prefixes": "src/lib/phone.ts:15-47",
    "web_message": "src/lib/telegram.ts:55-85 (formatLeadMessage)",
    "bot_message": "src/lib/telegram-bot.ts:140-159 (formatBotLeadMessage)",
    "group_silence": "src/app/api/telegram/webhook/route.ts:93-95",
    "delivery_failure": "src/app/api/telegram/webhook/route.ts:242-257",
    "working_hours": "src/config/site.ts:261",
}

#: The ten services, in the order the customer sees them.
SERVICES: dict[str, str] = {
    "banner": "Banner va konstruksiyalar",
    "hajmli-harflar": "Hajmli va yonadigan harflar",
    "lightbox": "Lightboxlar",
    "peshtoq": "Peshtoq va fasad bezagi",
    "plyonka": "Orakal plyonka bilan bezash",
    "stend": "Stend va ko'rgazma materiallari",
    "tablichka": "Tablichka va navigatsiya",
    "chop-etish": "UV va keng formatli chop etish",
    "neon": "Neon yozuvlar",
    "boshqa": "Boshqa buyurtma",
}

CONTACT_METHODS: dict[str, str] = {
    "phone": "Telefon qo'ng'irog'i",
    "telegram": "Telegram orqali",
}

WORKING_HOURS = "Dushanba — Shanba: 09:00 – 19:00"

#: Dialable Uzbek prefixes. A number outside this set is rejected by the form.
UZ_PHONE_PREFIXES = (
    "20", "33", "50", "55", "77", "88", "90", "91", "93", "94", "95", "97",
    "98", "99",
    "61", "62", "65", "66", "67", "69", "70", "71", "72", "73", "74", "75",
    "76", "78", "79",
)

UZ_COUNTRY_CODE = "998"
NATIONAL_NUMBER_LENGTH = 9

#: Markers the bot uses to re-read its own prompts (telegram-bot.ts:31-32).
#: The conversation is stateless; these carry the state.
PHONE_TAG = "\U0001F4DE"   # 📞
SERVICE_TAG = "\U0001F9E9"  # 🧩

NAME_MIN, NAME_MAX = 2, 60
MESSAGE_MAX = 1_000
#: Faster than this and the submission is treated as a script (lead-schema.ts:16).
MIN_FORM_FILL_MS = 1_500


# ── Faithful ports of the production helpers ────────────────────────────────

def normalize_uz_phone(value: str) -> str | None:
    """Port of `normalizeUzPhone` (src/lib/phone.ts:59)."""
    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if len(digits) == NATIONAL_NUMBER_LENGTH:
        national = digits
    elif (
        len(digits) == len(UZ_COUNTRY_CODE) + NATIONAL_NUMBER_LENGTH
        and digits.startswith(UZ_COUNTRY_CODE)
    ):
        national = digits[len(UZ_COUNTRY_CODE):]
    else:
        return None
    if national[:2] not in UZ_PHONE_PREFIXES:
        return None
    return f"+{UZ_COUNTRY_CODE}{national}"


def format_uz_phone(e164: str) -> str:
    """Port of `formatUzPhone` (src/lib/phone.ts:92)."""
    m = re.fullmatch(r"\+998(\d{2})(\d{3})(\d{2})(\d{2})", e164)
    if not m:
        return e164
    return f"+998 {m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)}"


def escape_html(value: str) -> str:
    """Port of `escapeHtml` (src/lib/telegram.ts:20)."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def service_title(service_id: str) -> str:
    """Port of `serviceTitle`: unknown ids fall back to the id itself."""
    return SERVICES.get(service_id, service_id)


def contact_method_label(method_id: str) -> str:
    return CONTACT_METHODS.get(method_id, method_id)


# ── Drift check against the real source ─────────────────────────────────────

@dataclass
class DriftResult:
    available: bool
    mismatches: list[str]
    checked: list[str]
    source_path: str = ""

    @property
    def ok(self) -> bool:
        return self.available and not self.mismatches


def source_root() -> str | None:
    """Where the production checkout is, from ALCANA_SOURCE_PATH."""
    path = os.environ.get("ALCANA_SOURCE_PATH", "").strip()
    if path and os.path.isdir(os.path.join(path, "src")):
        return path
    return None


def check_drift(root: str | None = None) -> DriftResult:
    """Reads production's own source and confirms the facts above still hold.

    Returns `available=False` when the checkout is absent, so the caller can
    report NOT TESTED instead of claiming verification it did not perform.
    """
    root = root or source_root()
    # An unreadable checkout is "not verified", never "verified and wrong":
    # reporting FAIL here would misattribute a missing path to a product change.
    if root is None or not os.path.isdir(os.path.join(root, "src")):
        return DriftResult(available=False, mismatches=[], checked=[])

    mismatches: list[str] = []
    checked: list[str] = []

    def read(rel: str) -> str | None:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            mismatches.append(f"missing source file: {rel}")
            return None
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    # 1. Services: every id and title must still be present, in order.
    site = read("src/config/site.ts")
    if site is not None:
        found = re.findall(r'\{\s*id:\s*"([^"]+)",\s*title:\s*"([^"]+)"', site)
        found_services = [(i, t) for i, t in found if i in SERVICES or i.islower()]
        # keep only the service block entries (contact methods use `label`)
        ids = [i for i, _ in found_services]
        if ids[: len(SERVICES)] != list(SERVICES):
            mismatches.append(
                f"service ids changed: source={ids[: len(SERVICES)]} mirrored={list(SERVICES)}"
            )
        else:
            for sid, title in found_services[: len(SERVICES)]:
                if SERVICES[sid] != title:
                    mismatches.append(
                        f"service title changed for {sid!r}: "
                        f"source={title!r} mirrored={SERVICES[sid]!r}"
                    )
        checked.append("services")

        for mid, label in CONTACT_METHODS.items():
            if f'id: "{mid}", label: "{label}"' not in site:
                mismatches.append(f"contact method {mid!r} label changed or removed")
        checked.append("contact_methods")

        if f'workingHours: "{WORKING_HOURS}"' not in site:
            mismatches.append("workingHours changed")
        checked.append("working_hours")

    # 2. Phone prefixes.
    phone = read("src/lib/phone.ts")
    if phone is not None:
        block = re.search(
            r"UZ_PHONE_PREFIXES\s*=\s*\[(.*?)\]", phone, re.S
        )
        if block is None:
            mismatches.append("UZ_PHONE_PREFIXES not found")
        else:
            src_prefixes = tuple(re.findall(r'"(\d+)"', block.group(1)))
            if src_prefixes != UZ_PHONE_PREFIXES:
                mismatches.append(
                    "phone prefixes changed: "
                    f"{sorted(set(src_prefixes) ^ set(UZ_PHONE_PREFIXES))} differ"
                )
        checked.append("phone_prefixes")

    # 3. The field labels a manager reads, straight out of the formatters.
    tele = read("src/lib/telegram.ts")
    if tele is not None:
        for label in ("Yangi ariza — ALCANA PRINT", "Ism:", "Telefon:", "Xizmat:",
                      "Bog'lanish:", "Loyiha haqida:", "Vaqt:", "Manba:", "Sahifa:"):
            if label not in tele:
                mismatches.append(f"web notification label missing: {label!r}")
        checked.append("web_message")

    bot = read("src/lib/telegram-bot.ts")
    if bot is not None:
        for label in ("Yangi ariza — Telegram bot", "Ism:", "Telefon:", "Xizmat:",
                      "Bog'lanish:", "Telegram:", "Loyiha haqida:", "Vaqt:"):
            if label not in bot:
                mismatches.append(f"bot notification label missing: {label!r}")
        if f'PHONE_TAG = "{PHONE_TAG}"' not in bot:
            mismatches.append("PHONE_TAG marker changed")
        if f'SERVICE_TAG = "{SERVICE_TAG}"' not in bot:
            mismatches.append("SERVICE_TAG marker changed")
        checked.append("bot_message")

    # 4. The group really is a one-way sink.
    hook = read("src/app/api/telegram/webhook/route.ts")
    if hook is not None:
        if 'message.chat?.type !== "private"' not in hook:
            mismatches.append(
                "the group-silence guard changed — the bot may now act on group "
                "messages, which would invalidate this training material"
            )
        checked.append("group_silence")

    return DriftResult(
        available=True, mismatches=mismatches, checked=checked, source_path=root
    )
