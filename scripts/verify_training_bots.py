#!/usr/bin/env python3
"""Verify the five training bot tokens, identities, and test-group access.

Read-only: issues only getMe, getChat and getChatMember. Sends no messages,
posts nothing, and changes nothing. Safe to run repeatedly.

Usage:
    python3 scripts/verify_training_bots.py            # reads .env, then os.environ
    python3 scripts/verify_training_bots.py --env-file path/to/.env

Exit status: 0 if every check passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org"
TIMEOUT = 20

# logical role -> env var holding its token
ROLES: dict[str, str] = {
    "TRAINING_MANAGER_01": "TRAINING_MANAGER_01_BOT_TOKEN",
    "TRAINING_MANAGER_02": "TRAINING_MANAGER_02_BOT_TOKEN",
    "TRAINING_MANAGER_03": "TRAINING_MANAGER_03_BOT_TOKEN",
    "TRAINING_ADMIN_01": "TRAINING_ADMIN_01_BOT_TOKEN",
    "TRAINING_LEADER_01": "TRAINING_LEADER_01_BOT_TOKEN",
}

DISPLAY = {
    "TRAINING_MANAGER_01": "Training Manager 1",
    "TRAINING_MANAGER_02": "Training Manager 2",
    "TRAINING_MANAGER_03": "Training Manager 3",
    "TRAINING_ADMIN_01": "Training Administrator",
    "TRAINING_LEADER_01": "Training Leader",
}

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
PLACEHOLDER_RE = re.compile(r"REPLACE_WITH|^000000000:|CHANGEME", re.IGNORECASE)

PASS, FAIL, BLOCKED, SKIP = "PASS", "FAIL", "BLOCKED", "NOT TESTED"


class Report:
    """Collects check results. Never stores token material."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, scope: str, check: str, status: str, detail: str = "") -> None:
        self.rows.append((scope, check, status, redact(detail)))

    @property
    def ok(self) -> bool:
        return all(s == PASS or s == SKIP for _, _, s, _ in self.rows)

    def render(self) -> str:
        w1 = max(len(r[0]) for r in self.rows)
        w2 = max(len(r[1]) for r in self.rows)
        out = []
        for scope, check, status, detail in self.rows:
            line = f"  [{status:^10}] {scope:<{w1}}  {check:<{w2}}"
            if detail:
                line += f"  — {detail}"
            out.append(line)
        return "\n".join(out)


_SECRETS: list[str] = []


def remember_secret(value: str) -> None:
    """Register a token so it can never appear in output."""
    if value and value not in _SECRETS:
        _SECRETS.append(value)


def redact(text: str) -> str:
    """Strip any known token, and any token-shaped substring, from text."""
    for s in _SECRETS:
        text = text.replace(s, "<redacted-token>")
        head = s.split(":", 1)[0]
        if head:
            text = text.replace(head, "<redacted-id>")
    # belt-and-braces: anything that still looks like a token
    return re.sub(r"\d{5,}:[A-Za-z0-9_-]{30,}", "<redacted-token>", text)


# The canonical .env parser lives in training/envfile.py. Imported rather than
# duplicated, with a sys.path nudge so this file still runs as a plain script
# from anywhere in the repo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from training.envfile import load_env_file  # noqa: E402


def call(token: str, method: str, **params: object) -> tuple[bool, object]:
    """One Telegram API call. Returns (ok, result-or-error-string)."""
    url = f"{API}/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            return False, f"HTTP {exc.code}"
        return False, str(body.get("description", f"HTTP {exc.code}"))
    except urllib.error.URLError as exc:
        return False, f"network error: {exc.reason}"
    except json.JSONDecodeError:
        return False, "malformed response from Telegram"
    if not body.get("ok"):
        return False, str(body.get("description", "unknown API error"))
    return True, body.get("result")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", default=".env", help="path to env file (default: .env)")
    args = ap.parse_args()

    file_env = load_env_file(args.env_file)

    def get(key: str) -> str:
        # explicit process env wins over the file
        return (os.environ.get(key) or file_env.get(key) or "").strip()

    rep = Report()
    print("Training bot verification — read-only (getMe / getChat / getChatMember)")
    print(f"env file: {args.env_file}"
          f"{'' if os.path.isfile(args.env_file) else ' (absent; using process environment)'}\n")

    # --- 1. environment guard ------------------------------------------------
    env_name = get("TRAINING_ENVIRONMENT")
    if env_name == "training":
        rep.add("config", "TRAINING_ENVIRONMENT guard", PASS, "training")
    elif not env_name:
        rep.add("config", "TRAINING_ENVIRONMENT guard", FAIL, "not set; refusing to proceed")
    else:
        rep.add("config", "TRAINING_ENVIRONMENT guard", FAIL,
                f"must be 'training', got {env_name!r}; refusing to proceed")

    if env_name != "training":
        print(rep.render())
        print("\nRESULT: FAIL — environment guard rejected the configuration.")
        print("No Telegram API call was made.")
        return 1

    # --- 2. group id + allowlist --------------------------------------------
    raw_group = get("TRAINING_MANAGER_GROUP_ID")
    allowed_raw = get("TRAINING_ALLOWED_CHAT_IDS")
    allowed = {c.strip() for c in allowed_raw.split(",") if c.strip()}

    group_id: int | None = None
    if not raw_group:
        rep.add("config", "TRAINING_MANAGER_GROUP_ID", FAIL, "not set")
    elif PLACEHOLDER_RE.search(raw_group) or raw_group == "-1000000000000":
        rep.add("config", "TRAINING_MANAGER_GROUP_ID", FAIL,
                "still the placeholder value from .env.example")
    else:
        try:
            group_id = int(raw_group)
            rep.add("config", "TRAINING_MANAGER_GROUP_ID", PASS, raw_group)
        except ValueError:
            rep.add("config", "TRAINING_MANAGER_GROUP_ID", FAIL,
                    f"not an integer: {raw_group!r}")

    if not allowed:
        rep.add("config", "chat allowlist", FAIL, "TRAINING_ALLOWED_CHAT_IDS is empty")
        group_id = None
    elif group_id is not None and str(group_id) not in allowed:
        rep.add("config", "chat allowlist", FAIL,
                "group id is NOT in TRAINING_ALLOWED_CHAT_IDS; refusing to touch it")
        group_id = None
    elif group_id is not None:
        rep.add("config", "chat allowlist", PASS, f"{len(allowed)} chat(s) allowed")
    else:
        rep.add("config", "chat allowlist", SKIP,
                "group id invalid, so allowlist membership was not evaluated")

    # --- 3. tokens -> identities --------------------------------------------
    identities: dict[str, dict] = {}
    seen: dict[int, str] = {}

    for role, var in ROLES.items():
        token = get(var)
        label = f"{role} ({DISPLAY[role]})"

        if not token:
            rep.add(label, "token present", FAIL, f"{var} not set")
            continue
        if PLACEHOLDER_RE.search(token):
            rep.add(label, "token present", FAIL, f"{var} still holds a placeholder")
            continue
        remember_secret(token)
        if not TOKEN_RE.match(token):
            rep.add(label, "token format", FAIL,
                    f"{var} is not shaped like a BotFather token")
            continue
        rep.add(label, "token format", PASS)

        ok, result = call(token, "getMe")
        if not ok:
            rep.add(label, "identity (getMe)", FAIL, str(result))
            continue
        assert isinstance(result, dict)
        identities[role] = result
        bot_id = int(result["id"])
        uname = result.get("username", "?")
        rep.add(label, "identity (getMe)", PASS, f"@{uname} (id {bot_id})")

        if bot_id in seen:
            rep.add(label, "distinct identity", FAIL,
                    f"same bot as {seen[bot_id]} — each role needs its own bot")
        else:
            seen[bot_id] = role
            rep.add(label, "distinct identity", PASS)

    if len(ROLES) != len(identities):
        rep.add("summary", "all five roles resolved", FAIL,
                f"{len(identities)}/{len(ROLES)} tokens resolved to a bot")
    else:
        rep.add("summary", "all five roles resolved", PASS)

    # --- 4. group access + rights -------------------------------------------
    if group_id is None:
        rep.add("group", "membership & rights", BLOCKED,
                "no allowlisted group id; nothing was contacted")
    elif not identities:
        rep.add("group", "membership & rights", BLOCKED, "no working token to query with")
    else:
        probe_role = next(iter(identities))
        probe_token = get(ROLES[probe_role])
        ok, chat = call(probe_token, "getChat", chat_id=group_id)
        if not ok:
            rep.add("group", "reachable (getChat)", FAIL, str(chat))
        else:
            assert isinstance(chat, dict)
            ctype = chat.get("type", "?")
            title = chat.get("title", "(untitled)")
            rep.add("group", "reachable (getChat)", PASS, f"{ctype}: {title}")
            if ctype not in ("group", "supergroup"):
                rep.add("group", "chat is a group", FAIL,
                        f"type is {ctype!r}; a group or supergroup is required")
            else:
                rep.add("group", "chat is a group", PASS, ctype)

            for role, me in identities.items():
                token = get(ROLES[role])
                ok, member = call(token, "getChatMember",
                                  chat_id=group_id, user_id=int(me["id"]))
                label = f"{role} ({DISPLAY[role]})"
                if not ok:
                    rep.add(label, "in test group", FAIL, str(member))
                    continue
                assert isinstance(member, dict)
                status = member.get("status", "?")
                if status in ("left", "kicked"):
                    rep.add(label, "in test group", FAIL,
                            f"status={status} — add this bot to the group")
                    continue
                rep.add(label, "in test group", PASS, f"status={status}")
                # rights are reported, never assumed
                if status == "administrator":
                    rights = sorted(
                        k for k, v in member.items()
                        if k.startswith("can_") and v is True
                    )
                    rep.add(label, "admin rights", PASS,
                            ", ".join(rights) if rights else "administrator, no extra rights")
                else:
                    rep.add(label, "admin rights", SKIP,
                            "not an administrator (fine unless a scenario needs it)")

    print(rep.render())
    print()
    if rep.ok:
        print("RESULT: PASS — configuration and group access verified.")
        print("No message was sent. Verified state is a precondition, not a test run.")
        return 0
    print("RESULT: FAIL — see the rows above. Fix them before any scenario runs.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
