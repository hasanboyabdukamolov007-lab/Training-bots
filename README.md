# Training Bots — manager training & testing subsystem

Intended purpose: a five-bot Telegram subsystem (3 managers, 1 administrator,
1 leader) that demonstrates an existing customer-service bot's real workflow,
runs labelled synthetic requests in an isolated test environment, and trains
employees on the actual product.

## Current status: awaiting a scoping decision

The production system has been located and audited:
**[`Alcana-taplink-page`](https://github.com/hasanboyabdukamolov007-lab/Alcana-taplink-page)**
(commit `9c701bb`). It is real, clean, and healthy — 175 tests pass, typecheck
clean.

It is, however, a **lead-capture and notification** system, not a
customer-service **request-management** system. The manager group is a one-way
notification sink that the bot deliberately ignores
(`webhook/route.ts:95` — *"must stay silent there"*). There is no database, no
request entity, no roles, no statuses, no assignment, no SLA, no internal notes,
no escalation, and no audit log. Managers read a notification and telephone the
customer; they take no action in Telegram at all.

Consequently **1 of the 15 required training scenarios** is demonstrable against
the real product. Read [`AUDIT.md`](AUDIT.md) for the full gap analysis and the
documented manager-group workflow.

Two paths, differing by an order of magnitude in scope:

- **A — scope the training to the product that exists.** Teach the real
  workflow: how a lead reaches the group, how to read each field, the bot's
  4-step conversation, delivery failures, phone follow-up. Small, useful,
  buildable now.
- **B — build the request-management layer first,** then train on it. This is
  what the specification describes, but it is a new product rather than an
  extension.

No work has been committed toward either until that is decided.

## What is here and working today

The environment-setup pieces, which are useful under either path above:

| File | Purpose |
|---|---|
| [`AUDIT.md`](AUDIT.md) | Audit findings, Telegram platform analysis, per-deliverable status |
| [`docs/audit-evidence.md`](docs/audit-evidence.md) | Raw, reproducible command output from both audits |
| [`.env.example`](.env.example) | Exact configuration template, placeholders only |
| [`docs/botfather-setup.md`](docs/botfather-setup.md) | Creating the five bots, the test group, rights, and verification |
| [`scripts/verify_training_bots.py`](scripts/verify_training_bots.py) | Read-only verifier for tokens, identities, group access |
| [`scripts/test_verify_training_bots.py`](scripts/test_verify_training_bots.py) | Offline tests for the verifier (22 checks, no network) |

Nothing here sends a Telegram message.

## Quick start

```bash
cp .env.example .env            # then fill in real tokens; .env is git-ignored
python3 scripts/verify_training_bots.py
```

Python 3.9+, no dependencies. See [`docs/botfather-setup.md`](docs/botfather-setup.md)
for the full walkthrough.

To test the verifier itself with no network access:

```bash
python3 scripts/test_verify_training_bots.py
```

## Safety rules this code follows

- `TRAINING_ENVIRONMENT` must be exactly `training`, checked before any network call.
- A chat not in `TRAINING_ALLOWED_CHAT_IDS` is never contacted — it fails closed.
- Tokens are read from the environment or `.env`, never hardcoded, never committed,
  and scrubbed from all output including error messages.
- All Telegram calls are read-only (`getMe`, `getChat`, `getChatMember`).
- Bot permissions are read from `getChatMember`, never inferred from a valid token.
- No message is sent until a test environment and allowlist are configured and verified.
