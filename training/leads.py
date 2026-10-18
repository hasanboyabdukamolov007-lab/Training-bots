"""Seeded generator for synthetic leads.

A "lead" here is exactly what production handles — name, phone, service,
contact method, optional free-text message — and nothing more. There is no
request id, status or assignee in the product, so none is invented here. The
`test_id` below is a *training* label, not a product field: it exists so a
message in the test group can be traced back to the run that produced it.

Phone numbers are structurally valid Uzbek numbers (so they exercise the real
validator) but use the subscriber block `000 00 NN`, which is not allocated.
They must never be dialled.

Names, companies and project text are invented. No historical customer data is
read, and nothing here reaches a real customer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from training.production import (
    MESSAGE_MAX,
    SERVICES,
    normalize_uz_phone,
)

#: Visible on every synthetic lead so it cannot be mistaken for a real one.
TEST_MARKER = "[TEST]"

TASHKENT = timezone(timedelta(hours=5))

_FIRST = ("Dilshod", "Nigora", "Rustam", "Zuhra", "Jasur", "Malika", "Bekzod",
          "Gulnora", "Sardor", "Kamola", "Tohir", "Shahnoza")
_LAST = ("Karimov", "Yusupova", "Tursunov", "Saidova", "Ergashev", "Qodirova",
         "Mirzayev", "Abdullayeva")

#: The UI is Uzbek-only, but the message field accepts any script and the name
#: pattern explicitly permits Cyrillic (lead-schema.ts:26). Managers therefore
#: do see Russian and English text from customers — so the generator produces it.
_PROJECT_TEXT = {
    "uz": (
        "Do'kon peshtoqi uchun banner kerak, o'lcham 3x1 metr.",
        "Ofis uchun hajmli harflar, yoniq bo'lsin. Muddat 2 hafta.",
        "Lightbox kerak, ichidan yoritilgan. Narxini bilsam bo'ladimi?",
        "Avtomobilga orakal plyonka yopishtirish kerak.",
        "Ko'rgazma uchun stend kerak, 10-15 sentyabr kunlari.",
    ),
    "ru": (
        "Нужен баннер на фасад магазина, размер 3х1 метр.",
        "Объёмные буквы с подсветкой для офиса. Сроки — две недели.",
        "Интересует лайтбокс с внутренней подсветкой. Сколько стоит?",
    ),
    "en": (
        "We need a 3x1 m banner for a shopfront. What is the lead time?",
        "Looking for illuminated channel letters for an office reception.",
        "Need UV printing for 20 A1 posters, matte finish.",
    ),
}

_NO_DETAIL = "—"  # what the bot tells customers to send when they do not know


@dataclass
class Lead:
    """A synthetic lead in the shape production actually delivers."""

    test_id: str
    name: str
    phone: str
    service: str
    contact_method: str
    message: str | None = None
    source: str | None = None
    page_url: str | None = None
    #: Telegram @username, present only on the bot path.
    handle: str | None = None
    #: "web" (the form) or "bot" (the 4-step conversation).
    channel: str = "web"
    received_at: datetime = field(default_factory=lambda: datetime.now(TASHKENT))
    #: Which training situation this lead was built for.
    kind: str = "routine"
    language: str = "uz"

    def __post_init__(self) -> None:
        if normalize_uz_phone(self.phone) is None:
            raise ValueError(f"synthetic phone is not a valid Uzbek number: {self.phone!r}")
        if self.service not in SERVICES:
            raise ValueError(f"unknown service id: {self.service!r}")
        if self.message is not None and len(self.message) > MESSAGE_MAX:
            raise ValueError("synthetic message exceeds the production limit")


def _phone(rng: random.Random) -> str:
    """A valid-but-unallocated number: +998 90 000 00 NN."""
    return f"+99890000{rng.randint(0, 99):04d}"


def _name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def generate(
    seed: int = 1,
    count: int = 6,
    kinds: tuple[str, ...] | None = None,
) -> list[Lead]:
    """Produces a reproducible batch. The same seed always yields the same leads.

    `kinds` selects situations. Only situations the product can actually
    exhibit are available — there is no "overdue" or "escalated" lead, because
    production has no such concept.
    """
    available = {
        "routine": _routine,
        "no_details": _no_details,
        "long_message": _long_message,
        "html_injection": _html_injection,
        "bot_channel": _bot_channel,
        "telegram_callback": _telegram_preferred,
    }
    chosen = kinds or tuple(available)
    for k in chosen:
        if k not in available:
            raise ValueError(
                f"unknown lead kind {k!r}. available: {sorted(available)}. "
                "Kinds such as 'overdue' or 'escalated' do not exist because "
                "the production system has no such states."
            )

    rng = random.Random(seed)
    out: list[Lead] = []
    for i in range(count):
        kind = chosen[i % len(chosen)]
        out.append(available[kind](rng, seed, i))
    return out


def _base(rng: random.Random, seed: int, i: int, **over: object) -> Lead:
    lang = str(over.pop("language", rng.choice(("uz", "uz", "ru", "en"))))
    kwargs: dict[str, object] = {
        "test_id": f"{TEST_MARKER} S{seed}-{i + 1:02d}",
        "name": _name(rng),
        "phone": _phone(rng),
        "service": rng.choice(list(SERVICES)),
        "contact_method": "phone",
        "message": rng.choice(_PROJECT_TEXT[lang]),
        "language": lang,
        "received_at": datetime.now(TASHKENT) - timedelta(minutes=rng.randint(0, 240)),
    }
    kwargs.update(over)
    return Lead(**kwargs)  # type: ignore[arg-type]


def _routine(rng: random.Random, seed: int, i: int) -> Lead:
    """The common case: every field present, customer wants a phone call."""
    return _base(rng, seed, i, kind="routine", source="instagram")


def _no_details(rng: random.Random, seed: int, i: int) -> Lead:
    """The customer sent the bot's "—" because they did not know the details.

    Teaches: the manager must ask the questions the form could not.
    """
    return _base(rng, seed, i, kind="no_details", channel="bot",
                 message=_NO_DETAIL, handle="test_user", contact_method="telegram")


def _long_message(rng: random.Random, seed: int, i: int) -> Lead:
    """At the 1000-character limit, so wrapping in the group can be seen."""
    body = ("Peshtoq uchun to'liq brending kerak. " * 40)[:MESSAGE_MAX]
    return _base(rng, seed, i, kind="long_message", message=body, language="uz")


def _html_injection(rng: random.Random, seed: int, i: int) -> Lead:
    """A name containing markup.

    Production escapes it (telegram.ts:20). Teaches a manager that angle
    brackets appearing literally in the group are correct behaviour, not a bug.
    """
    return _base(rng, seed, i, kind="html_injection",
                 name="Olim <b>Test</b> & Co", language="uz")


def _bot_channel(rng: random.Random, seed: int, i: int) -> Lead:
    """Arrived through the 4-step bot conversation rather than the web form."""
    return _base(rng, seed, i, kind="bot_channel", channel="bot",
                 handle="test_customer", contact_method="telegram")


def _telegram_preferred(rng: random.Random, seed: int, i: int) -> Lead:
    """Web form, but the customer asked to be contacted on Telegram.

    Teaches: contact method decides *how* to follow up; it is the one field
    that changes the manager's next action.
    """
    return _base(rng, seed, i, kind="telegram_callback",
                 contact_method="telegram", source="utm_source=telegram")
