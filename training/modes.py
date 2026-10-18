"""Execution modes and the audit log.

Every recorded step says *how* it was executed, so a reader can never mistake a
reproduction for a live integration. This is the distinction the brief calls for
and it is enforced by type, not by convention: a step without a mode cannot be
recorded.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Mode(str, Enum):
    """How a training step was actually carried out."""

    #: Rendered locally from a faithful reproduction of production's formatter.
    #: Nothing left this machine. Teaches the workflow; proves nothing about it.
    SIMULATED = "SIMULATED"

    #: Checked against the real production source files on disk — the labels,
    #: service ids and markers a manager will see were read out of the shipped
    #: code, not from memory.
    APPLICATION_INTEGRATION = "APPLICATION_INTEGRATION"

    #: A real call to api.telegram.org with a test token.
    TELEGRAM_BOT_API = "TELEGRAM_BOT_API"

    #: Required a human-operated Telegram account; not automated here.
    AUTHORIZED_TEST_ACCOUNT = "AUTHORIZED_TEST_ACCOUNT"


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_TESTED = "NOT TESTED"


_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")


def redact(text: str) -> str:
    """Remove anything token-shaped. Applied to every audit field."""
    return _TOKEN_RE.sub("<redacted-token>", text)


@dataclass
class Step:
    """One recorded action inside a scenario."""

    scenario_id: str
    step: str
    mode: Mode
    status: Status
    expected: str = ""
    actual: str = ""
    explanation: str = ""
    lead_id: str = ""
    telegram_ref: str = ""
    error: str = ""
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        d["status"] = self.status.value
        for k, v in d.items():
            if isinstance(v, str):
                d[k] = redact(v)
        return d


@dataclass
class RunLog:
    """A whole training run. Diagnostics only — never a production audit trail."""

    run_id: str
    steps: list[Step] = field(default_factory=list)

    def record(self, step: Step) -> Step:
        self.steps.append(step)
        return step

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Status}
        for step in self.steps:
            out[step.status.value] += 1
        return out

    def score(self) -> tuple[int, int]:
        """(passed, attempted). NOT TESTED steps are not attempts."""
        attempted = [s for s in self.steps if s.status is not Status.NOT_TESTED]
        passed = [s for s in attempted if s.status is Status.PASS]
        return len(passed), len(attempted)

    def to_dict(self) -> dict[str, Any]:
        passed, attempted = self.score()
        return {
            "run_id": self.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": self.counts(),
            "score": {"passed": passed, "attempted": attempted},
            "modes": {
                m.value: sum(1 for s in self.steps if s.mode is m) for m in Mode
            },
            "steps": [s.to_dict() for s in self.steps],
        }

    def write(self, directory: str) -> str:
        """Writes the run as JSON. Test output only; never production data."""
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{self.run_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        return path
