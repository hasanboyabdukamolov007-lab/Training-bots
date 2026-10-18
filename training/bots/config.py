"""Configuration for the three manager bots.

Roles are fixed in code, not configuration: a trainee must be able to rely on
@..manager1 always teaching the same lesson. Each manager owns exactly one
scenario and one generator seed, so a session is reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from training.envfile import resolve_env

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
PLACEHOLDER_RE = re.compile(r"REPLACE_WITH|CHANGEME|^000000000:", re.IGNORECASE)


@dataclass(frozen=True)
class Role:
    """A manager's fixed teaching assignment."""

    bot_id: str
    display: str
    token_var: str
    scenario_id: str
    seed: int
    focus: str


#: Deterministic and distinct. Manager N teaches scenario N.
ROLES: tuple[Role, ...] = (
    Role(
        bot_id="TRAINING_MANAGER_01",
        display="Training Manager 1",
        token_var="TRAINING_MANAGER_01_BOT_TOKEN",
        scenario_id="S1",
        seed=101,
        focus="Reading a lead that arrived from the website form",
    ),
    Role(
        bot_id="TRAINING_MANAGER_02",
        display="Training Manager 2",
        token_var="TRAINING_MANAGER_02_BOT_TOKEN",
        scenario_id="S2",
        seed=102,
        focus="Understanding how the bot collected the lead",
    ),
    Role(
        bot_id="TRAINING_MANAGER_03",
        display="Training Manager 3",
        token_var="TRAINING_MANAGER_03_BOT_TOKEN",
        scenario_id="S3",
        seed=103,
        focus="Recognising a lead that never arrived",
    ),
)

ROLES_BY_ID = {r.bot_id: r for r in ROLES}
#: Short aliases accepted on the command line.
ALIASES = {"m1": "TRAINING_MANAGER_01", "1": "TRAINING_MANAGER_01",
           "m2": "TRAINING_MANAGER_02", "2": "TRAINING_MANAGER_02",
           "m3": "TRAINING_MANAGER_03", "3": "TRAINING_MANAGER_03"}


def resolve_role(name: str) -> Role:
    key = ALIASES.get(name.strip().lower(), name.strip().upper())
    if key not in ROLES_BY_ID:
        raise KeyError(
            f"unknown manager {name!r}. use one of "
            f"{[r.bot_id for r in ROLES]} or m1/m2/m3"
        )
    return ROLES_BY_ID[key]


@dataclass
class BotConfig:
    """One bot's resolved configuration. `token` is never logged or serialised."""

    role: Role
    token: str
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __repr__(self) -> str:  # defensive: keep the token out of tracebacks
        return (f"BotConfig(role={self.role.bot_id}, token=<redacted>, "
                f"errors={self.errors})")


@dataclass
class RuntimeConfig:
    """Shared settings plus the three bots."""

    environment: str = ""
    dry_run: bool = True
    group_id: int | None = None
    allowed_chat_ids: frozenset[int] = frozenset()
    forbidden_chat_ids: frozenset[int] = frozenset()
    poll_timeout: int = 25
    bots: list[BotConfig] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def runnable(self) -> list[BotConfig]:
        return [b for b in self.bots if b.ok]

    def is_chat_allowed(self, chat_id: int, chat_type: str) -> tuple[bool, str]:
        """Whether this bot may reply in a chat.

        A private chat is where a trainee talks to the bot, so it is allowed.
        Any group must be explicitly allowlisted. The forbidden list wins over
        everything, so the production group can be named once and never reached.
        """
        if chat_id in self.forbidden_chat_ids:
            return False, "chat is on TRAINING_FORBIDDEN_CHAT_IDS"
        if chat_type == "private":
            return True, "private chat"
        if chat_id in self.allowed_chat_ids:
            return True, "chat is allowlisted"
        return False, "group chat is not in TRAINING_ALLOWED_CHAT_IDS"


def _parse_ids(raw: str) -> tuple[frozenset[int], list[str]]:
    out: set[int] = set()
    bad: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            bad.append(part)
    return frozenset(out), bad


def _parse_bool(raw: str, default: bool) -> bool:
    """Only an explicit, unambiguous false disables dry run."""
    value = raw.strip().lower()
    if value in ("false", "0", "no", "off"):
        return False
    if value in ("true", "1", "yes", "on"):
        return True
    return default


def load(env_file: str = ".env", env: dict[str, str] | None = None,
         require_group: bool = False) -> RuntimeConfig:
    """Builds and validates the runtime configuration.

    Never raises: problems are collected so the caller can report all of them
    at once instead of one per run. A bot with a bad token is marked not-ok and
    the other two still start.
    """
    e = env if env is not None else resolve_env(env_file)
    cfg = RuntimeConfig()

    cfg.environment = e.get("TRAINING_ENVIRONMENT", "").strip()
    if cfg.environment != "training":
        cfg.errors.append(
            "TRAINING_ENVIRONMENT must be exactly 'training' (got "
            f"{cfg.environment or 'unset'!r}) — refusing to start"
        )

    # Dry run is on unless explicitly turned off. A typo leaves it on.
    cfg.dry_run = _parse_bool(e.get("TRAINING_DRY_RUN", ""), default=True)

    raw_group = e.get("TRAINING_MANAGER_GROUP_ID", "").strip()
    if raw_group and raw_group != "-1000000000000":
        try:
            cfg.group_id = int(raw_group)
        except ValueError:
            cfg.errors.append(f"TRAINING_MANAGER_GROUP_ID is not an integer: {raw_group!r}")
    elif raw_group == "-1000000000000":
        if require_group:
            cfg.errors.append("TRAINING_MANAGER_GROUP_ID is still the placeholder")
    elif require_group:
        cfg.errors.append("TRAINING_MANAGER_GROUP_ID is not set")

    cfg.allowed_chat_ids, bad_allow = _parse_ids(e.get("TRAINING_ALLOWED_CHAT_IDS", ""))
    for b in bad_allow:
        cfg.errors.append(f"TRAINING_ALLOWED_CHAT_IDS contains a non-integer: {b!r}")

    cfg.forbidden_chat_ids, bad_deny = _parse_ids(e.get("TRAINING_FORBIDDEN_CHAT_IDS", ""))
    for b in bad_deny:
        cfg.errors.append(f"TRAINING_FORBIDDEN_CHAT_IDS contains a non-integer: {b!r}")

    if cfg.group_id is not None:
        if cfg.group_id in cfg.forbidden_chat_ids:
            cfg.errors.append(
                "TRAINING_MANAGER_GROUP_ID is on TRAINING_FORBIDDEN_CHAT_IDS — refusing"
            )
        elif cfg.group_id not in cfg.allowed_chat_ids:
            cfg.errors.append(
                "TRAINING_MANAGER_GROUP_ID is not in TRAINING_ALLOWED_CHAT_IDS"
            )

    raw_timeout = e.get("TRAINING_POLL_TIMEOUT", "").strip()
    if raw_timeout:
        try:
            cfg.poll_timeout = max(0, min(60, int(raw_timeout)))
        except ValueError:
            cfg.errors.append(f"TRAINING_POLL_TIMEOUT is not an integer: {raw_timeout!r}")

    # A production token must never be usable here.
    prod_token = e.get("TELEGRAM_BOT_TOKEN", "").strip()

    seen: dict[str, str] = {}
    for role in ROLES:
        token = e.get(role.token_var, "").strip()
        problems: list[str] = []
        if not token:
            problems.append(f"{role.token_var} is not set")
        elif PLACEHOLDER_RE.search(token):
            problems.append(f"{role.token_var} still holds a placeholder")
        elif not TOKEN_RE.match(token):
            problems.append(f"{role.token_var} is not shaped like a BotFather token")
        else:
            if prod_token and token == prod_token:
                problems.append(
                    f"{role.token_var} equals TELEGRAM_BOT_TOKEN (production) — refusing"
                )
            if token in seen:
                problems.append(
                    f"{role.token_var} is the same token as {seen[token]}; "
                    "each manager needs its own bot"
                )
            else:
                seen[token] = role.token_var
        cfg.bots.append(BotConfig(role=role, token=token, errors=problems))

    return cfg
