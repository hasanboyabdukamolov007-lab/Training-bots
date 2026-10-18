# Repository Audit — Training Bots Subsystem

**Date:** 2026-10-18
**Production system audited:** `hasanboyabdukamolov007-lab/Alcana-taplink-page`
(commit `9c701bb`, 2026-09-18)
**Scope requested:** extend an existing Telegram customer-service bot with a
five-bot training/testing subsystem (3 managers, 1 administrator, 1 leader).

## 1. Summary

The production project exists, is real, and is in good health. It is **not** a
customer-service request-management system. It is a **lead-capture and
notification** system.

That distinction decides this whole task. The training specification is written
against a request-management product — statuses, assignment, SLA, internal
notes, complaints, escalation, search, audit. Essentially none of that exists
here, and the manager group is a one-way notification sink that the bot
deliberately ignores. Roughly **1 of the 15 required training scenarios** is
demonstrable against the real application today.

Baseline health, measured not assumed:

| Check | Command | Result |
|---|---|---|
| Typecheck | `npx tsc --noEmit` | **clean**, exit 0 |
| Tests | `npx vitest run` | **175 passed**, 13 files, 1.70s |
| Install | `npm ci` | clean |

The code is well-commented, zod-validated, HTML-escaped, rate-limited, and has
genuine test coverage. Nothing below is a criticism of it.

## 2. What the production system actually does

A Next.js 16 / React 19 link-in-bio page for ALCANA PRINT, with Telegram lead
delivery. No database, no ORM, no persistence of any kind.

### Two intake paths, one destination

**Path A — web form:** `POST /api/lead` (`src/app/api/lead/route.ts`)
→ zod validation (`lib/lead-schema.ts`), rate limit 5/IP/10min
(`lib/rate-limit.ts`) → `notifyNewLead()` → `sendTelegramMessage()`.

**Path B — the bot conversation:** `@alcana_lead_bot`, a 4-step private chat
(`src/app/api/telegram/webhook/route.ts` + `lib/telegram-bot.ts`):

1. `/start` → reply keyboard with `request_contact`
2. contact shared → inline keyboard of services (`svc:<id>` callback data)
3. service tapped → `force_reply` prompt for project details
4. details replied → confirm to customer, post to manager group

**Both paths end at the same place:** a single `sendMessage` with
`parse_mode: "HTML"` to `TELEGRAM_MANAGER_CHAT_ID`, optionally inside a forum
topic via `TELEGRAM_MESSAGE_THREAD_ID`.

### The manager-group workflow, documented exactly as asked (§20)

> A lead arrives → the app posts **one HTML message** into the manager chat →
> a human manager reads it and **telephones the customer**.

That is the entire workflow. Specifically:

- The group message carries **no buttons, no inline keyboard, no callbacks**.
  Callbacks exist in this codebase only in the *customer's private chat*, for
  service selection.
- **The bot is deliberately silent in the group.**
  `src/app/api/telegram/webhook/route.ts:95` — `if (message.chat?.type !== "private") return;`
  with the comment *"the bot is also a member of the managers' group, and must
  stay silent there."* Group messages are read and discarded.
- Managers take **no action in Telegram**. There is nothing to press, reply to,
  or change. The follow-up happens by phone, using the numbers in
  `siteConfig.contacts.phones`.
- Delivery failure is handled by logging the lead to stderr
  (`route.ts:246`) so it is recoverable by hand. There is no queue and no retry
  beyond `sendTelegramMessage`'s single retry on 5xx/network.

### Statelessness is a deliberate design choice

`lib/telegram-bot.ts:14` — *"no server-side session store: on Vercel each
webhook call can land on a different instance."* Conversation state is
re-derived by parsing the bot's own prior message text, using `📞` and `🧩`
markers (`readPrompt()`). This survives cold starts and redeploys.

The consequence for this task: **nothing is ever stored.** There is no row to
assign, transition, search, audit, or report on.

## 3. Gap analysis against the training specification

| Spec requirement | Present? | Evidence |
|---|---|---|
| Request/ticket entity | **No** | no model; `grep -ri ticket\|requestId src/` → 0 files |
| Persistent request ID | **No** | nothing is stored; group `message_id` is the only handle |
| Database / datastore | **No** | no ORM or DB dependency in `package.json` |
| Roles (manager/admin/leader) | **No** | `role` appears only as ARIA attributes in JSX |
| Request statuses | **No** | `status` is React form state and HTTP codes only |
| Accept / claim a request | **No** | `grep -ri claim` → 0 files |
| Assignment / reassignment | **No** | `grep -ri assign` → 0 files |
| Internal notes | **No** | no such concept |
| Priority | **No** | `priority` appears only in `sitemap.ts` and one CSS comment |
| SLA / due dates / overdue | **No** | no scheduling, no timers, no stored timestamps |
| Complaints | **No** | `grep -ri complaint` → 0 files |
| Escalation | **No** | `grep -ri escalat` → 0 files |
| Reopen / cancel | **No** | `grep -ri reopen` → 0 files |
| Merge / split | **No** | not implemented |
| Search / saved views | **No** | nothing to search |
| Request timeline | **No** | no history |
| Audit log | **No** | `grep -ri audit` → 0 files |
| Attachment handling | **No** | webhook reads `text` and `contact` only |
| Customer notification | **Yes** | `managersReply()`, sent to the customer's private chat |
| Manager-group posting | **Yes** | one-way `sendMessage` to `TELEGRAM_MANAGER_CHAT_ID` |
| Callbacks | **Partial** | private chat only (`svc:<id>`); never in the group |
| Multi-language | **Partial** | the product is **Uzbek-only**; no RU/EN strings exist |

Note the last row: §12 and §14 require Uzbek, Russian and English. The product
ships Uzbek only. Preserving "existing Uzbek, Russian and English support" (§18)
is not possible, because RU and EN support does not exist to preserve.

### The five-bot premise does not fit this architecture

- The app reads **one** token, `TELEGRAM_BOT_TOKEN` (`lib/env.ts:13`). There is
  no notion of multiple bot identities, and no manager identity at all.
- Five training bots in the manager group would be **five silent members**. The
  app ignores group messages, so nothing they posted could affect anything.
- **Bots cannot see each other's messages in a Telegram group.** Even if the app
  listened, the bots could not observe or respond to one another, so every
  manager-to-manager scenario (§9: hand-off, concurrent claim, reassignment) is
  impossible over Telegram and would have to run through a service layer that
  does not exist.
- A valid token proves identity only, never permission.

## 4. Of the 15 required training scenarios (§13)

| # | Scenario | Buildable today |
|---|---|---|
| 1 | Processing a routine request | **Partial** — a lead notification can be demonstrated end-to-end |
| 3 | Responding to a customer | **Partial** — only as the real product does it: by telephone |
| 5 | Handling an attachment | No — attachments are not read |
| 12 | Using search and saved views | No — no search |
| 13 | Exporting request history | No — no history |
| 2, 4, 6–11, 14, 15 | claiming, info requests, internal notes, urgency, SLA, complaints, reassignment, completion, escalation, duplicates | **No** — none of these features exist |

## 5. Production isolation: achievable, and this is the good news

§5's isolation requirement **can** be satisfied cleanly, because the target chat
is entirely environment-driven:

- `TELEGRAM_MANAGER_CHAT_ID` is read per request from env (`lib/env.ts:19`),
  never hardcoded.
- `readTelegramEnv()` is injectable (`source` parameter), and `fetchImpl` is
  injectable throughout `lib/telegram.ts` — the existing tests already use this
  to assert against the network without touching it.
- `TELEGRAM_MESSAGE_THREAD_ID` allows a dedicated forum topic.

So a **separate deployment with separate env vars, a separate test bot token and
a separate test group** isolates test traffic from production without modifying
production code at all. No database needs separating, because there is no
database. This is the one part of the spec that fits this codebase well.

The startup check that "rejects production configuration" (§5) is implementable
as: refuse to run if the configured chat id equals the production one, and
refuse unless the chat id is in an explicit allowlist.

## 6. What this means

The specification assumes a product that does not exist here. Building the
subsystem as written would require first building a request-management
system — database, tickets, roles, statuses, assignment, SLA, notes, audit —
which is a far larger undertaking than the training harness, and is precisely
the "existing production bot" the spec says not to write (§18).

Two honest paths, which lead to very different amounts of work:

**A. Scope the training subsystem to the product that exists.** Train managers
on the real workflow: how a lead reaches the group, how to read every field,
the bot's 4-step conversation, what a delivery failure looks like in the logs,
and how to follow up by phone. Small, genuinely useful, buildable now, and it
teaches the actual product as §13 demands.

**B. Build the request-management layer first,** then the training subsystem on
top. This is what the spec describes, but it is a new product, not an
extension — and the training harness cannot precede it.

This audit stops here rather than guessing between them, because the two differ
by an order of magnitude in scope.

## 7. Safety: nothing was sent, nothing was changed

- **No Telegram message was sent.** §5/§20 forbid it until a test environment
  and allowlist are configured and verified. No token was supplied or requested.
- **The production repository was not modified.** It was cloned read-only;
  `npm ci` wrote only `node_modules`, which is git-ignored.
- No production chat id, token, or routing was touched.
- Note: `api.telegram.org` is unreachable from this build environment (proxy
  returns 403 on CONNECT), so no live Telegram call could be made from here
  regardless. Live verification must run from the owner's host.

## 8. Deliverable status

| Deliverable (§19) | Status |
|---|---|
| 1. Repository audit | **Done** — this file |
| 3. Environment variable template | **Done** — `.env.example` |
| 4. BotFather setup instructions | **Done** — `docs/botfather-setup.md` |
| 5. Adding bots to the test group | **Done** — `docs/botfather-setup.md` |
| 6. Group ID & permission verification | **Done** — `scripts/verify_training_bots.py`, 22 offline tests passing |
| 13. Production-isolation checks | **Partial** — env guard, chat allowlist, token/identity checks |
| 2. Architecture for five role bots | **Blocked** — pending the path A/B decision in §6 |
| 7. Synthetic request generator | **Blocked** — no request entity or store to generate into |
| 8/9. Training & admin/leader scenarios | **Blocked** — 14 of 15 scenarios reference absent features |
| 10. Automated test suite | **Blocked** — no workflow to assert against |
| 11. Visual dashboard | **Blocked** — no test records; §15 forbids hardcoded metrics |
| 12. Self-healing workflow | **Blocked** — no test suite to heal |

The verifier in `scripts/` is real, runnable, and useful under either path: it
validates that supplied tokens resolve to distinct bots and reports actual group
rights, using read-only calls only.
