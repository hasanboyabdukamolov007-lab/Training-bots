# The three manager bots

Executable Telegram runtimes for `TRAINING_MANAGER_01/02/03`. Each is a real
bot that polls `getUpdates`, answers commands, and teaches one scenario.

## What they are

Each bot is a **tutor a trainee talks to**, with a fixed assignment:

| Bot | Teaches | Seed |
|---|---|---|
| `TRAINING_MANAGER_01` | **S1** — Reading a lead from the website form | 101 |
| `TRAINING_MANAGER_02` | **S2** — Understanding how the bot collected the lead | 102 |
| `TRAINING_MANAGER_03` | **S3** — Recognising a lead that never arrived | 103 |

Roles live in code (`training/bots/config.py`), not configuration, so a trainee
can rely on manager 1 always teaching the same lesson. The seed is fixed, so
each bot always shows the same synthetic lead.

### What they are not

They are **not simulated colleagues**. Telegram bots cannot see each other's
messages in a group, so three bots cannot role-play a team handing work over
([`../AUDIT.md`](../AUDIT.md) §3). Each teaches one lesson, which is something
they genuinely can do. There is also nothing for them to act on: the production
bot ignores the manager group entirely.

## Commands

| Command | Does |
|---|---|
| `/start`, `/help` | who this bot is and what it teaches |
| `/whoami` | identity, scenario, seed, live counters |
| `/lead` | this bot's synthetic lead, as a manager would see it |
| `/scenario` | the lesson plan — objective, starting state, steps |
| `/next` | the next step: what should happen, why, and the common mistake |
| `/reset` | back to step 1 (per chat) |
| `/check` | runs the scenario for real and reports PASS/FAIL per step |

`/command@BotName` works too, which is how Telegram delivers commands in groups.
Progress is tracked per chat, so two trainees in private chats do not interfere.

## Running them

```bash
python3 -m training.bots status      # configuration and roles; exit 1 if not ready
python3 -m training.bots verify      # getMe for each token
python3 -m training.bots start-all   # all three
python3 -m training.bots start m1    # just one (m1/m2/m3 or the full id)
python3 -m training.bots self-test   # whole runtime, offline, no network
```

Python 3.9+, no dependencies. Ctrl-C or `SIGTERM` stops every bot cleanly and
releases its lock.

## Safety

**Dry run is on by default.** Nothing is transmitted until you set
`TRAINING_DRY_RUN=false` deliberately. A typo, an empty value or an unset
variable all leave dry run **on**; only an explicit `false`/`0`/`no`/`off`
turns it off. In dry run the bots still poll and still compute every reply —
they are logged as `reply.suppressed` instead of being sent, and the send never
reaches the HTTP transport at all.

Other guards, each with tests:

- `TRAINING_ENVIRONMENT` must be exactly `training`, or nothing starts.
- A group chat not in `TRAINING_ALLOWED_CHAT_IDS` is ignored — no reply, no post.
- A chat on `TRAINING_FORBIDDEN_CHAT_IDS` is refused outright, even if also
  allowlisted. Put your production group id there.
- A training token equal to `TELEGRAM_BOT_TOKEN` (production) is refused.
- Two managers sharing one token is refused.
- Private chats are allowed, because that is where a trainee talks to the bot.

## Failure isolation

A problem with one bot never touches the other two:

| Failure | Result |
|---|---|
| Missing, malformed, duplicated or placeholder token | that bot is skipped with a reason; the others start |
| Revoked token (`401`) | that bot fails `getMe`, does not poll, releases its lock |
| Webhook conflict (`409`) or other 4xx while polling | that bot stops with a permanent-error reason rather than spinning |
| 5xx or network error while polling | retries with backoff 1s → 2s → 5s → 10s → 30s |
| Malformed update | logged; the next update is still handled |
| Unexpected exception in a bot thread | caught at the thread boundary and logged as `crashed` |

## Duplicate polling

Telegram delivers each update once, so two pollers on one token split the
updates between them — a trainee gets half their replies, which looks exactly
like a broken bot. A lock in `$TMPDIR/training-bots-locks/` makes that
impossible: a second start on the same token is refused while the first lives.

The lock file is named with a **SHA-256 fingerprint of the token, never the
token**, and contains only a pid. A lock whose process is gone is treated as
stale and taken over, so a crash does not leave a bot unstartable.

## Logging

One JSON object per line on stderr, for example:

```json
{"ts":"2026-10-18T03:55:53+0000","level":"INFO","bot":"TRAINING_MANAGER_01",
 "event":"identity.verified","username":"selftest_m1_bot","bot_api_id":55,"scenario":"S1"}
{"ts":"2026-10-18T03:55:53+0000","level":"WARNING","bot":"TRAINING_MANAGER_01",
 "event":"chat.refused","chat_id":-100999,"chat_type":"supergroup",
 "reason":"group chat is not in TRAINING_ALLOWED_CHAT_IDS"}
```

Events: `identity.verified`, `identity.failed`, `identity.unreachable`,
`started`, `stopped`, `start.refused`, `crashed`, `poll.failed`, `poll.error`,
`update.failed`, `chat.refused`, `reply.sent`, `reply.suppressed`,
`reply.failed`, `skipped`, `start_all`, `signal`, `join.timeout`.

**Redaction is applied at the formatter, not the call site**, so a developer who
forgets cannot leak a token through this logger. It strips registered tokens,
their bot-id prefix, anything token-shaped, and tokens embedded in
`api.telegram.org/bot…/` URLs — recursively through nested dicts and lists.

## Test evidence

```
tests/test_bots.py                 121 checks  PASS   (offline, scripted transport)
tests/test_training.py              91 checks  PASS
scripts/test_verify_training_bots.py 22 checks PASS
python3 -m training.bots self-test   9 checks  PASS
```

Covered: configuration validation (including every rejection), token redaction,
startup, identity verification, per-bot failure isolation, permanent vs
transient API errors, malformed updates, safe shutdown and lock release,
test-group allowlisting, denylist precedence, duplicate-polling prevention and
stale-lock takeover, dry-run suppression, and command dispatch.

### NOT TESTED — live Telegram

**Live identity verification is `NOT TESTED`.** This build environment cannot
reach `api.telegram.org`:

```
$ curl -sS -o /dev/null -w "%{http_code}\n" --max-time 15 https://api.telegram.org/
curl: (56) CONNECT tunnel failed, response 403
000
```

`python3 -m training.bots verify` with well-formed tokens reports, per bot:

```
✗ TRAINING_MANAGER_01  URLError: <urlopen error Tunnel connection failed: 403 Forbidden>
```

So the HTTP transport, real `getMe`, real `getUpdates` long polling and real
`sendMessage` are **unverified**. Everything above them — the poll loop,
dispatch, guards, locking, logging and shutdown — is tested through an injected
transport. Run `verify` from your own machine to close that gap; expect
`✓ TRAINING_MANAGER_01  @yourbot (id 12345)`.
