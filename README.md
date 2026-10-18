# Training Bots — manager training & testing subsystem

Intended purpose: a five-bot Telegram subsystem (3 managers, 1 administrator,
1 leader) that demonstrates an existing customer-service bot's real workflow,
runs labelled synthetic requests in an isolated test environment, and trains
employees on the actual product.

## Status

The production system is **[`Alcana-taplink-page`](https://github.com/hasanboyabdukamolov007-lab/Alcana-taplink-page)**
(commit `9c701bb`), and it is a **lead-capture and notification** system — not a
request-management one. A lead arrives, the app posts one message into the
manager group, and a manager telephones the customer. There is no database, no
ticket, no status, no assignment and no SLA, and the bot deliberately ignores
the manager group entirely.

This subsystem therefore teaches **that** workflow, accurately, rather than a
ticket workflow the product does not have. Full findings in
[`AUDIT.md`](AUDIT.md); the workflow itself in
[`docs/alcana-workflow.md`](docs/alcana-workflow.md).

Three scenarios:

| | Scenario | Teaches |
|---|---|---|
| **S1** | Reading a lead from the website form | every field, which one decides the follow-up, why escaped markup is correct |
| **S2** | Understanding how the bot collected the lead | what the customer was actually asked, so you know what you must still ask |
| **S3** | Recognising a lead that never arrived | the one silent failure, and what a manager can and cannot do about it |

### Honesty mechanisms

This is a training tool, so being wrong is worse than being incomplete:

- **Every step records how it was executed** — `APPLICATION_INTEGRATION`
  (checked against the production source), `SIMULATED` (checked against the
  local reproduction), or `TELEGRAM_BOT_API` (a real Telegram call). The mode is
  reported next to every result and is never blurred.
- **A reproduction never stands in for the product.** Without
  `ALCANA_SOURCE_PATH`, integration steps report `NOT TESTED`, never `PASS`.
- **A drift check** reads the real source each run and confirms the seven fact
  groups the material depends on. Its own tests mutate a throwaway copy to prove
  it detects a renamed label, a changed service title, a dropped phone prefix and
  a removed group-silence guard.
- **`NOT TESTED` is excluded from the score** rather than counted as a pass.

## What is here

| Path | Purpose |
|---|---|
| [`AUDIT.md`](AUDIT.md) | Audit findings, gap analysis, Telegram platform limits |
| [`docs/alcana-workflow.md`](docs/alcana-workflow.md) | The production workflow, cited line by line |
| [`docs/training-guide.md`](docs/training-guide.md) | Running a session; reading the results |
| [`docs/botfather-setup.md`](docs/botfather-setup.md) | Test bot, test group, rights, verification |
| [`docs/roadmap.md`](docs/roadmap.md) | What cannot be taught yet, in build order |
| [`docs/audit-evidence.md`](docs/audit-evidence.md) | Raw reproducible command output |
| `training/production.py` | Mirrored product facts + the drift check |
| `training/leads.py` | Seeded synthetic lead generator |
| `training/render.py` | Faithful reproduction of both notification formats |
| `training/scenarios.py` | The three scenarios and their verification |
| `training/runner.py` | CLI, isolation guard, run reports |
| `training/modes.py` | Execution modes, audit log, token redaction |
| `training/envfile.py` | The single `.env` parser, used everywhere |
| `training/bots/` | **Executable runtimes for the three manager bots** |
| [`docs/manager-bots.md`](docs/manager-bots.md) | Running the manager bots; guards, isolation, logging |
| `tests/test_training.py` | 91 offline checks |
| `tests/test_bots.py` | 121 offline checks for the bot runtimes |
| `scripts/verify_training_bots.py` | Read-only verifier for tokens, identities, group access |
| `scripts/test_verify_training_bots.py` | 22 offline checks for the verifier |

Nothing posts to Telegram unless you pass `--post`, and that is refused unless
every isolation guard passes.

## The three manager bots

Each is a real Telegram bot a trainee talks to, teaching one scenario:
manager 1 → S1, manager 2 → S2, manager 3 → S3.

```bash
python3 -m training.bots status      # configuration and roles
python3 -m training.bots verify      # getMe for each token
python3 -m training.bots start-all   # start all three
python3 -m training.bots self-test   # whole runtime, offline
```

**Dry run is on by default** — nothing is transmitted until you set
`TRAINING_DRY_RUN=false` deliberately. Full details, guards and failure
isolation in [`docs/manager-bots.md`](docs/manager-bots.md).

## Quick start

Python 3.9+, no dependencies.

```bash
export ALCANA_SOURCE_PATH=/path/to/Alcana-taplink-page   # enables real verification
export TRAINING_ENVIRONMENT=training

python3 -m training.runner --teach     # walkthrough + verified scenarios
python3 -m training.runner --post      # also post to the configured test group
```

Set up the test bot and group first — [`docs/botfather-setup.md`](docs/botfather-setup.md) —
then verify with:

```bash
cp .env.example .env                   # fill in real tokens; .env is git-ignored
python3 scripts/verify_training_bots.py
```

Tests, both offline:

```bash
ALCANA_SOURCE_PATH=/path/to/Alcana-taplink-page python3 tests/test_training.py
python3 scripts/test_verify_training_bots.py
```

## Safety rules this code follows

- `TRAINING_ENVIRONMENT` must be exactly `training`, checked before any network call.
- A chat not in `TRAINING_ALLOWED_CHAT_IDS` is never contacted — it fails closed.
- Tokens are read from the environment or `.env`, never hardcoded, never committed,
  and scrubbed from all output including error messages.
- Posting is refused unless the environment is `training`, the target is in the
  allowlist, absent from `TRAINING_FORBIDDEN_CHAT_IDS`, and the token differs
  from the production one. The guard fails closed; all six refusals are tested.
- Synthetic phone numbers are structurally valid but unallocated
  (`+998 90 000 00 NN`) and must never be dialled.
- Every posted message carries a `TEST MODE — DO NOT ACTION` banner naming the
  run and lead id.
- The verifier's Telegram calls are read-only (`getMe`, `getChat`, `getChatMember`).
- Bot permissions are read from `getChatMember`, never inferred from a valid token.
- No message is sent until a test environment and allowlist are configured and verified.
