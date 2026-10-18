# Repository Audit — Training Bots Subsystem

**Date:** 2026-10-18
**Scope requested:** extend an existing Telegram customer-service bot with a five-bot
training/testing subsystem (3 managers, 1 administrator, 1 leader).

## 1. Headline finding: there is no existing project to extend

The audit required by the task specification was performed first, before any
implementation. Result:

| Audit question | Finding |
|---|---|
| Existing repository contents | **Empty.** Zero files, zero commits. |
| Remote branches | **None.** `git ls-remote --heads origin` returns nothing; GitHub API `list_branches` returns `[]`. |
| Documentation | None. |
| Dependencies / manifest | None. No `requirements.txt`, `package.json`, `pyproject.toml`, lockfile, or Dockerfile. |
| Telegram handlers | None. |
| Request lifecycle | Not implemented. |
| Database / schema / migrations | None. |
| Roles & permissions model | None. |
| Manager-group configuration | None. |
| Existing tests | None. |
| Existing test/demo/synthetic-data mode | None. |

Verification commands and their actual output are recorded in
[`docs/audit-evidence.md`](docs/audit-evidence.md).

The repository `hasanboyabdukamolov007-lab/Training-bots` was created empty
(pushed_at 2026-10-18T03:07Z, same timestamp as this session's container start)
and contains no production system.

## 2. Why this blocks most of the requested work

The specification defines the training subsystem *relative to an existing
application*. It is explicit that the subsystem must use the real thing and must
not invent workflows:

- §3: "Do not assume that any feature exists merely because it appears in a specification."
- §7: "Use the actual request-to-manager-group workflow wherever possible."
- §8: "The bots must not merely post example messages. They should use the actual
  application workflow or an explicitly identified test adapter, and verify the
  resulting state."
- §13: "The training system should teach the actual existing product, not invent
  unsupported workflows."
- §18: "Preserve the existing project and all current functionality. ... Do not
  rewrite the production bot from scratch."

With no application present there is nothing to post into a manager group,
no status model to transition, no roles to enforce, no notifications to verify,
and no product for employees to be trained on. Building these now would mean
inventing a production workflow and then "training" staff on a fiction — the
specific outcome §13 forbids. It would also contradict §18, since there is no
existing project to preserve or extend.

Therefore the audit stops short of implementing §7–§16 and reports the blocker,
as §5 and §20 require.

## 3. What was NOT done, and deliberately so

- **No Telegram messages were sent.** §5 and §20 forbid this until a test
  environment and chat allowlist are configured and verified. Neither exists yet.
  No token has been supplied to this session, and none was requested.
- **No production bot was scaffolded.** Inventing one would make every later
  "PASS" meaningless.
- **No synthetic requests were generated**, since there is no request model,
  no isolated datastore, and no verified test group to route them to.
- **No other repository was read.** This session is scoped to `Training-bots`
  only; the account's other repositories were listed but not opened, and none
  were added, because that was not requested.

## 4. Production/test isolation: cannot yet be established

§5 requires a verified-isolated datastore, separate configuration, a dedicated
test group, test-only tokens, a chat allowlist, and a startup check that
*rejects production configuration*. The last item is currently unimplementable in
a meaningful way: rejecting production config requires knowing what production
config looks like, which requires the production system.

Per §5 ("If test and production environments cannot be reliably separated, stop
and report the blocker before sending any Telegram message") this is reported
rather than approximated.

## 5. Telegram platform constraints (app-independent, confirmed)

These hold regardless of the missing application and shape the final design:

- A bot cannot initiate a private conversation with a user or another bot; the
  other party must message first. Five tokens therefore do **not** yield five
  agents able to reproduce arbitrary human manager actions.
- By default a bot in a group has privacy mode enabled and receives only
  commands and replies addressed to it, not all group messages.
- Bots do not see other bots' messages in groups. **This is the decisive
  constraint for this design:** the five training bots cannot observe or react to
  each other in the test group. Any manager-to-manager interaction (hand-off,
  concurrent claim, reassignment) must be driven through the application service
  layer, not through Telegram.
- A bot cannot add itself to a group, and cannot grant itself administrator
  rights. Both are manual owner actions.
- A valid token proves identity only — never permissions. Rights must be read
  via `getChatMember`, not assumed.

Consequence: the realistic execution-mode split for the requested scenarios is
mostly `APPLICATION_INTEGRATION`, with `TELEGRAM_BOT_API` limited to identity
checks, group posting, and callback handling on a bot's own messages.

## 6. Recommended next step

Point this subsystem at the real project. Either:

1. **The production bot lives in another repository** — name it and it can be
   added to this session, audited properly, and extended as specified; or
2. **The production bot does not exist yet** — then the correct order is to build
   the customer-service bot first and add the training subsystem afterwards. A
   training harness cannot precede the product it trains on.

## 7. What was delivered in the meantime

Only the pieces that are genuinely independent of the unknown application, and
that you need in hand before any of the rest can run:

| Deliverable (spec §) | File | Status |
|---|---|---|
| Repository audit (§3, D1) | this file, `docs/audit-evidence.md` | Done |
| Environment variable template (§6, D3) | `.env.example` | Done |
| BotFather setup instructions (§6, D4) | `docs/botfather-setup.md` | Done |
| Adding bots to the test group (§6, D5) | `docs/botfather-setup.md` | Done |
| Group ID & permission verification procedure (§7, D6) | `docs/botfather-setup.md`, `scripts/verify_training_bots.py` | Done |
| Telegram capability analysis (§4) | §5 above | Done |
| Architecture for the five bots (§2, D2) | — | **Blocked** — depends on the real app's handlers, roles and request model |
| Synthetic request generator (§12, D7) | — | **Blocked** — no request model or isolated store |
| Training scenarios (§8–§11, §13, D8/D9) | — | **Blocked** — no product workflow to teach |
| Automated test suite (§14, D10) | — | **Blocked** — nothing to assert against |
| Dashboard (§15, D11) | — | **Blocked** — no test records to display; §15 forbids hardcoded metrics |
| Self-healing workflow (§16, D12) | — | **Blocked** — no test suite to heal |
| Production-isolation checks (§5, D13) | partial — token/identity/allowlist checks only | **Partial**, see §4 |

The verification tool is real and runnable today: it validates that five supplied
tokens resolve to five *distinct* bot identities, checks the configured group
against the allowlist, and reports each bot's actual membership and rights. It
performs read-only Telegram API calls (`getMe`, `getChat`, `getChatMember`) and
sends no messages.
