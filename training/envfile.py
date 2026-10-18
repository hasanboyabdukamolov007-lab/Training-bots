"""The one place a `.env` file is parsed.

Two near-identical parsers had grown up in `training/runner.py` and
`scripts/verify_training_bots.py`. Both now call this. Adding a third copy
would be the start of three subtly different notions of what `.env` means.

The file is parsed, never executed: a `.env` is configuration, and running it
as a shell script would let a stray backtick execute.
"""

from __future__ import annotations

import os


def load_env_file(path: str) -> dict[str, str]:
    """Reads `KEY=VALUE` lines. Missing file yields `{}` rather than raising.

    Blank lines and `#` comments are skipped; surrounding single or double
    quotes are stripped. `export KEY=VALUE` is accepted because people paste it.
    """
    values: dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def resolve_env(
    env_file: str = ".env",
    process_env: dict[str, str] | None = None,
    prefixes: tuple[str, ...] = ("TRAINING_", "ALCANA_"),
) -> dict[str, str]:
    """Merges the file with the process environment, process winning.

    Only `prefixes` are taken from the process environment, so an unrelated
    variable cannot quietly reconfigure a training run.
    """
    proc = os.environ if process_env is None else process_env
    merged = load_env_file(env_file)
    merged.update({
        k: v for k, v in proc.items() if any(k.startswith(p) for p in prefixes)
    })
    return merged
