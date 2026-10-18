# Roadmap

What this subsystem cannot teach today, in the order worth building. Each item
says what it would unlock for training, because that is the only reason it
appears here.

Nothing below is required for the current three scenarios to be useful, and
nothing below has been built. These are proposals, as the brief asked —
not work in progress.

## Priority 1 — persist the lead (unblocks almost everything else)

**Problem.** Nothing is stored. A lead exists only as a group message, so a
failed delivery loses it except as a log line (`route.ts:246`), and no training
scenario can be about a lead's history because there is none.

**Smallest useful change.** Write each lead to a durable store on receipt,
before the Telegram post, and give it an id shown in the group message.

**Unlocks for training:** recovering a lead after a delivery failure; referring
to a specific lead by id; any scenario that needs a lead to still exist a minute
later. It is a precondition for every item below.

**Cost.** This is the one genuinely architectural change. The app is currently
stateless by deliberate design for Vercel (`telegram-bot.ts:14`), and adding a
store means choosing one and handling its failure modes. Everything else on this
list is small by comparison.

## Priority 2 — make delivery failure non-silent

**Problem.** A customer is thanked even when the group post fails
(`route.ts:259`), so they believe they are in the queue when nobody has seen
them. Today a manager can only be taught to believe the customer.

**Smallest useful change.** Retry with backoff beyond the current two attempts,
and alert a second channel when delivery ultimately fails.

**Unlocks for training:** S3 becomes a scenario with a correct recovery action
instead of only an awareness lesson.

## Priority 3 — acknowledge a lead in the group

**Problem.** The group is one-way; the bot ignores it (`route.ts:95`). Two
managers cannot tell whether either has picked a lead up, and S3's last step
exists only to teach that typing in the group does nothing.

**Smallest useful change.** One inline button on the group notification —
"I'll take this" — recording who pressed it and when, and editing the message to
show it. This needs Priority 1 to have somewhere to record it.

**Unlocks for training:** claiming a lead; avoiding duplicate contact; the first
scenario where a manager does something in Telegram rather than only reading.
This is the single highest-value addition for day-to-day work.

## Priority 4 — first-response timing

**Problem.** No timestamps are kept beyond the one printed in the message, so
"how long did that take" is unanswerable.

**Smallest useful change.** With Priority 1 and 3 in place, record received-at
and claimed-at and report the gap.

**Unlocks for training:** a leader-facing scenario using real measured numbers.
The specification's §11 leader bot needs this; without it there is nothing
truthful for a leader to review.

## Priority 5 — Russian and English interface

**Problem.** The product is Uzbek-only. The specification asked for all three
languages to be preserved; only Uzbek exists to preserve
([`../AUDIT.md`](../AUDIT.md) §3). Customers already write in Russian and
English, and the bot answers only in Uzbek.

**Smallest useful change.** Extract `botMessages` and `validationMessages` into
per-language maps, pick from the Telegram user's `language_code`, default to
Uzbek.

**Unlocks for training:** scenarios in the language each trainee works in.

## Explicitly not proposed

These were in the original specification. They are not recommended, because
nothing in the audit suggests this business needs them, and each would be a
substantial new product rather than an extension:

- a ticket system with statuses, assignment and reassignment
- an SLA engine with due dates, overdue detection and escalation
- internal notes, complaint handling, merge/split, saved views
- a role model with manager/administrator/leader permissions
- five separate manager bots — Telegram bots cannot see each other's group
  messages, so they cannot model a team interacting ([`../AUDIT.md`](../AUDIT.md) §3)

A business that telephones its customers within working hours may simply not
need a ticket queue. If one is wanted later, Priority 1 and 3 are its
foundation, and they are worth doing on their own merits either way.
