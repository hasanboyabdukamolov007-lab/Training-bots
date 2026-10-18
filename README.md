# Training Bots — manager training & testing subsystem

Intended purpose: a five-bot Telegram subsystem (3 managers, 1 administrator,
1 leader) that demonstrates an existing customer-service bot's real workflow,
runs labelled synthetic requests in an isolated test environment, and trains
employees on the actual product.

## Current status: blocked on the production system

**This repository was empty.** There is no customer-service bot here to extend,
demonstrate, or train anyone on. The audit that the specification requires as
step one found zero files and zero commits.

Read [`AUDIT.md`](AUDIT.md) for the finding, what it blocks and why, and
[`docs/audit-evidence.md`](docs/audit-evidence.md) for the raw command output.

The training subsystem cannot be built against an application that is not
present: there is no request model to create, no manager group routing to
exercise, no status machine to transition, no roles to enforce, and no product
for employees to learn. Implementing it anyway would mean inventing a workflow
and then training staff on a fiction — which the specification explicitly
forbids (§3, §8, §13, §18).

**To unblock:** point this at the real project — either name the repository that
holds the production bot so it can be audited and extended, or build the
customer-service bot first and add this subsystem afterwards.

## What is here and working today

Only the pieces that genuinely do not depend on the unknown application:

| File | Purpose |
|---|---|
| [`AUDIT.md`](AUDIT.md) | Audit findings, Telegram platform analysis, per-deliverable status |
| [`docs/audit-evidence.md`](docs/audit-evidence.md) | Raw, reproducible command output |
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
