#!/usr/bin/env python3
"""Offline tests for verify_training_bots.py.

No network access required, so these run anywhere — including environments
where api.telegram.org is unreachable. Run: python3 scripts/test_verify_training_bots.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    spec = importlib.util.spec_from_file_location(
        "verify_training_bots", os.path.join(HERE, "verify_training_bots.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_training_bots"] = mod
    spec.loader.exec_module(mod)
    return mod


v = load()
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [  PASS  ] {name}")
    else:
        print(f"  [  FAIL  ] {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


print("offline tests for verify_training_bots\n")

# --- redaction -------------------------------------------------------------
tok = "123456789:AAFakeTokenForTestingOnly_NotRealXYZ12"
v.remember_secret(tok)
red = v.redact(f"Unauthorized for {tok}")
check("registered token is redacted", "AAFake" not in red and "<redacted-token>" in red, red)
check(
    "unregistered token-shaped string is redacted",
    "ZZUnreg" not in v.redact("oops 999888777:ZZUnregTokenShapedStringHere1234567"),
)
check("ordinary text survives redaction", "hello world" in v.redact("hello world"))

# --- token format ----------------------------------------------------------
check("valid token shape accepted", bool(v.TOKEN_RE.match(tok)))
check("garbage token shape rejected", not v.TOKEN_RE.match("not-a-token"))
check("placeholder detected", bool(v.PLACEHOLDER_RE.search("000000000:REPLACE_WITH_TOKEN")))
check("real-looking token not flagged as placeholder", not v.PLACEHOLDER_RE.search(tok))

# --- role table ------------------------------------------------------------
check("five logical roles defined", len(v.ROLES) == 5, str(len(v.ROLES)))
check("every role has a display name", set(v.ROLES) == set(v.DISPLAY))

# --- env file parsing ------------------------------------------------------
with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
    fh.write('# comment\nTRAINING_ENVIRONMENT=training\nQUOTED="-100123"\nBLANK=\n')
    path = fh.name
parsed = v.load_env_file(path)
os.unlink(path)
check("env parser reads keys", parsed.get("TRAINING_ENVIRONMENT") == "training", str(parsed))
check("env parser strips quotes", parsed.get("QUOTED") == "-100123", str(parsed))
check("env parser skips comments", "# comment" not in parsed)
check("missing env file yields empty dict", v.load_env_file("/nonexistent/x.env") == {})

# --- duplicate identity detection -----------------------------------------
seen: dict[int, str] = {}
dupes: list[tuple[str, str]] = []
for role, bot_id in [("M01", 111), ("M02", 111), ("M03", 222), ("A01", 333), ("L01", 444)]:
    if bot_id in seen:
        dupes.append((role, seen[bot_id]))
    else:
        seen[bot_id] = role
check("duplicate bot flagged", dupes == [("M02", "M01")], str(dupes))
check("distinct bots counted", len(seen) == 4, str(len(seen)))

# --- allowlist enforcement -------------------------------------------------
def allowed_ok(gid: int, raw: str) -> bool:
    s = {c.strip() for c in raw.split(",") if c.strip()}
    return bool(s) and str(gid) in s


check("allowlisted group accepted", allowed_ok(-1001234567890, "-1001234567890"))
check("non-allowlisted group refused", not allowed_ok(-1001234567890, "-1009999999999"))
check("empty allowlist refuses everything", not allowed_ok(-1001234567890, ""))
check("multi-entry allowlist works", allowed_ok(-100222, "-100111, -100222 ,-100333"))

# --- report status roll-up -------------------------------------------------
r = v.Report()
r.add("x", "c", v.PASS)
r.add("y", "d", v.SKIP)
check("PASS+NOT TESTED rolls up to ok", r.ok)
r.add("z", "e", v.FAIL)
check("any FAIL rolls up to not-ok", not r.ok)
r2 = v.Report()
r2.add("x", "c", v.BLOCKED)
check("BLOCKED rolls up to not-ok", not r2.ok)

print()
if failures:
    print(f"RESULT: FAIL — {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("RESULT: PASS — all offline checks passed.")
