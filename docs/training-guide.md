# Running the training

How to use the subsystem, for whoever runs a session. The workflow being taught
is documented in [`alcana-workflow.md`](alcana-workflow.md).

## What this teaches, and what it cannot

Three scenarios, covering the product as it exists:

| | Scenario | Teaches |
|---|---|---|
| **S1** | Reading a lead from the website form | every field, which one decides the follow-up, why escaped markup is correct |
| **S2** | Understanding how the bot collected the lead | what the customer was actually asked, so you know what you must still ask |
| **S3** | Recognising a lead that never arrived | the one silent failure, and what a manager can and cannot do about it |

It does **not** teach claiming, assignment, statuses, priorities, SLAs, internal
notes, complaints, escalation or reopening, because the product has none of
those. See [`../AUDIT.md`](../AUDIT.md) §3 and [`roadmap.md`](roadmap.md).

## Quick start

No dependencies; Python 3.9+.

```bash
# point at a checkout of the production repo so claims can be verified
export ALCANA_SOURCE_PATH=/path/to/Alcana-taplink-page
export TRAINING_ENVIRONMENT=training

python3 -m training.runner                 # run all three scenarios
python3 -m training.runner --teach         # with the manager-facing walkthrough
python3 -m training.runner --scenario S2   # one scenario
python3 -m training.runner --seed 7        # a different, reproducible lead set
```

Nothing leaves the machine unless you pass `--post`.

## Reading the result

Every step reports how it was actually carried out. **The mode matters more than
the status:**

| Mode | Means | Weight |
|---|---|---|
| `APPLICATION_INTEGRATION` | checked against the production source on disk | real evidence about the product |
| `SIMULATED` | checked against the local reproduction | demonstrates the workflow; proves nothing about production |
| `TELEGRAM_BOT_API` | a real call to api.telegram.org with the test token | real evidence about Telegram |
| `AUTHORIZED_TEST_ACCOUNT` | needs a human-operated account | not automated here |

Statuses are `PASS`, `FAIL`, `BLOCKED`, `NOT TESTED`. **`NOT TESTED` steps are
excluded from the score** rather than counted as passes.

Without `ALCANA_SOURCE_PATH`, every `APPLICATION_INTEGRATION` step reports
`NOT TESTED` — never `PASS`. A reproduction is never allowed to stand in for the
product.

### The drift check

Each run first reads the production source and confirms the seven fact groups
the training depends on: service ids and titles, contact-method labels, working
hours, phone prefixes, the web notification labels, the bot notification labels
and markers, and the group-silence guard.

If any has changed, the run says so and the material should be corrected before
teaching from it. A changed group-silence guard is the most serious: it would
mean the bot now acts on group messages, which would invalidate S3 entirely.

Reports are written to `var/training-runs/<run-id>.json` (git-ignored) with every
step, its mode, expected and actual outcome. Tokens are stripped from every
field.

## Running a session with employees

1. Set up the test bot and group once — [`botfather-setup.md`](botfather-setup.md).
2. Verify the environment: `python3 scripts/verify_training_bots.py`.
3. Walk through the material together:
   ```bash
   python3 -m training.runner --teach
   ```
   For each step this prints what should happen, **why**, and the common mistake.
4. Optionally post the synthetic notifications into the test group so people see
   them in Telegram, where they will really meet them:
   ```bash
   python3 -m training.runner --post
   ```
5. Have each trainee read a posted lead and say out loud: which channel, which
   service, which number to dial, and whether to call or message. S1 step 4 is
   the one that matters — the contact method decides the action.

### Keeping trainee actions separate from the system's

Everything this subsystem posts is wrapped in an unmissable banner naming the
run id and the synthetic lead id:

```
⚠️ TEST MODE — SYNTHETIC LEAD, DO NOT ACTION
run <id> · [TEST] S1-01 · do not dial this number
──────────────────
🟢 Yangi ariza — ALCANA PRINT
...
```

Anything a trainee types in the group is plainly their own. Note that the real
bot ignores group messages entirely, so trainees typing in the group cannot
affect anything — which is itself S3's final lesson.

## Synthetic leads

Seeded and reproducible: the same `--seed` always yields the same leads, so a
session can be repeated exactly or a failure re-examined.

Available situations — all of them things the product can genuinely produce:
`routine`, `no_details`, `long_message`, `html_injection`, `bot_channel`,
`telegram_callback`. Asking for a kind the product cannot exhibit (`overdue`,
`escalated`) is an error, not an empty result.

**The phone numbers are deliberately unallocated** — `+998 90 000 00 NN`. They
are structurally valid, so they exercise the real validator, but they are not
issued numbers. Never dial one. Names and project text are invented; no
historical customer data is read.

Customer-typed content is generated in Uzbek, Russian and English. The product's
own interface is Uzbek-only, but the message field accepts any script and the
name pattern explicitly permits Cyrillic (`lead-schema.ts:26`), so managers do
see Russian and English from customers.

## Safety

`--post` is refused unless **every** one of these holds:

- `TRAINING_ENVIRONMENT` is exactly `training`
- `TRAINING_MANAGER_GROUP_ID` is set, numeric, and not the placeholder
- that id appears in `TRAINING_ALLOWED_CHAT_IDS`
- that id does **not** appear in `TRAINING_FORBIDDEN_CHAT_IDS`
- the training token is set and is not a placeholder
- the training token is **not** equal to `TELEGRAM_BOT_TOKEN` (production)

Put your production group id in `TRAINING_FORBIDDEN_CHAT_IDS` and your
production bot token in the environment as `TELEGRAM_BOT_TOKEN`, and the last
two rules make posting as production, or into the production group, impossible.

The guard fails closed: any single unmet condition refuses the whole run and
nothing is sent. All six refusals are covered by tests.

## Tests

```bash
ALCANA_SOURCE_PATH=/path/to/Alcana-taplink-page python3 tests/test_training.py
python3 scripts/test_verify_training_bots.py
```

Both run offline. The second needs no production checkout. The drift check's own
negative tests mutate a throwaway copy of the production source to prove the
check actually detects a renamed label, a changed service title, a dropped phone
prefix and a removed group-silence guard.
