# The ALCANA PRINT lead workflow, as implemented

Authoritative description of what the production system does, read from
`hasanboyabdukamolov007-lab/Alcana-taplink-page` at commit `9c701bb`. Every
claim cites the file and line it came from, and
`training/production.py:check_drift()` re-verifies the load-bearing ones against
the source on every training run.

This document describes **only what exists**. For what the training
specification assumed and the product does not have, see [`../AUDIT.md`](../AUDIT.md).

## 1. The workflow in one sentence

> A lead arrives → the app posts **one HTML message** into the manager group →
> a human manager reads it and **telephones the customer**.

There is no ticket, no status, no assignment and no audit trail. Nothing is
stored anywhere. The group message is the only artefact.

## 2. Two intake paths

### Path A — the website form

`POST /api/lead` (`src/app/api/lead/route.ts`)

1. Rate limit: 5 submissions per IP per 10 minutes (`lib/rate-limit.ts`).
2. Requires `Content-Type: application/json`; body capped at 8 KiB.
3. Validation by zod (`lib/lead-schema.ts`), which also **normalises the phone**
   to E.164 and rejects two bot signals:
   - a filled honeypot field named `company` (must stay empty);
   - a form submitted in under 1500 ms (`MIN_FORM_FILL_MS`).
   Bot rejections return a neutral, success-shaped response so a script is not
   told which trap it hit.
4. On success → `notifyNewLead()` → `sendTelegramMessage()`.

### Path B — the Telegram bot conversation

`@alcana_lead_bot`, four steps, in the customer's **private** chat
(`src/app/api/telegram/webhook/route.ts`, prompts in `lib/telegram-bot.ts`):

| Step | Bot asks | Customer does | Mechanism |
|---|---|---|---|
| 1 | greeting + "📱 Kontakt ulashish" | sends `/start` | reply keyboard, `request_contact` (`telegram-bot.ts:122`) |
| 2 | "Qaysi xizmat kerak?" | shares contact card | inline keyboard, `callback_data: svc:<id>` (`telegram-bot.ts:114`) |
| 3 | "Loyihangiz haqida qisqacha yozing" | taps a service | `force_reply` (`route.ts:210`) |
| 4 | confirmation | replies with details | posts to the manager group (`route.ts:228`) |

**Webhook authentication:** the secret token Telegram echoes in
`x-telegram-bot-api-secret-token`, compared in constant time (`route.ts:276`).
Without `TELEGRAM_WEBHOOK_SECRET` set, every update is refused with 503 — the
URL would otherwise be world-writable.

**The webhook always answers 200** for any update it has seen, including ones it
cannot act on, because Telegram retries non-2xx and a retry would send the
customer a duplicate (`route.ts:19-30`).

### Statelessness

There is **no session store** (`telegram-bot.ts:14`). On Vercel each webhook
call may land on a different instance. Instead each prompt prints the answers so
far, and the next step parses them back out of the message the customer replied
to (`readPrompt()`, `telegram-bot.ts:99`), keyed on two markers:

- `📞` `PHONE_TAG` — the phone
- `🧩` `SERVICE_TAG` — the service

A customer can therefore leave mid-conversation and resume an hour later, across
a redeploy, and still complete the flow.

### Contact-card validation

A Telegram contact can be forwarded from somebody else's card, so the webhook
rejects a contact whose `user_id` is not the sender's (`route.ts:115-121`), then
normalises the number and rejects what it cannot parse.

## 3. The collected fields — the complete list

### Web form (`lib/lead-schema.ts:79`)

| Field | Required | Rules |
|---|---|---|
| `name` | yes | 2–60 chars; letters of any script (Cyrillic accepted), plus `'ʻʼ`, space, dot, hyphen |
| `phone` | yes | normalised to E.164; prefix must be a dialable Uzbek one |
| `service` | yes | one of the 10 service ids |
| `contactMethod` | yes | `phone` or `telegram` |
| `message` | no | ≤ 1000 chars; empty becomes absent |
| `consent` | yes | must be literally `true` |
| `company` | — | honeypot; must be empty |
| `elapsedMs` | no | < 1500 ms ⇒ treated as a script |
| `source` | no | ≤ 120 chars, e.g. `utm_source` |

### Bot conversation (`BotLead`, `telegram-bot.ts:129`)

`name` (from the contact card, or "Mijoz"), `phone`, `service`, `details`
(≤ 1000 chars, "—" if the customer sent nothing), optional `handle`
(@username), `telegramUserId`.

The bot never asks for a contact method — see §5.

### The ten services (`config/site.ts:123`)

`banner`, `hajmli-harflar`, `lightbox`, `peshtoq`, `plyonka`, `stend`,
`tablichka`, `chop-etish`, `neon`, `boshqa`.

### Phone handling (`lib/phone.ts`)

Accepts `+998XXXXXXXXX`, `998XXXXXXXXX` or `XXXXXXXXX` with any spacing,
dashes, dots or parentheses. The two-digit prefix must be one of 29 issued
mobile or regional codes — so `+998 10 …` is rejected as a typo even though the
length is right. `formatUzPhone()` groups E.164 for display:
`+998901234567` → `+998 90 123 45 67`.

## 4. Manager-group delivery

Both paths converge on one `sendMessage` to `TELEGRAM_MANAGER_CHAT_ID`, with
`parse_mode: "HTML"` and `disable_web_page_preview: true`. If
`TELEGRAM_MESSAGE_THREAD_ID` is set, it goes into that forum topic.

**All customer-supplied text is HTML-escaped first** (`telegram.ts:20`), so a
name containing `<b>` appears literally rather than as formatting or a broken
message.

Retry policy (`telegram.ts:131`): at most **2 attempts**, 300 ms apart.
A 4xx is final and is not retried — a wrong chat id will not fix itself.

### The notification a manager reads

Web form (`formatLeadMessage`, `telegram.ts:55`):

```
🟢 Yangi ariza — ALCANA PRINT

👤 Ism:        <name>
📞 Telefon:    +998 90 123 45 67     ← grouped for reading
🧩 Xizmat:     <service title>
📲 Bog'lanish: Telefon qo'ng'irog'i | Telegram orqali

💬 Loyiha haqida:   (only when a message was given)
<message>

🕒 Vaqt:   dd/mm/yyyy, HH:MM (Toshkent)
🔗 Manba:  (only when a source was given)
📄 Sahifa: (only when a page url was given)

☎️ +998901234567                      ← bare E.164: tappable to dial
```

Bot (`formatBotLeadMessage`, `telegram-bot.ts:140`) — same fields, with three
real differences:

1. heading is `🤖 Yangi ariza — Telegram bot`;
2. **the phone is not grouped** — `formatBotLeadMessage` does not call
   `formatUzPhone`;
3. `📲 Bog'lanish` is **hardcoded** to `Telegram orqali` (`telegram-bot.ts:147`);
4. it may carry `💬 Telegram: @handle`, and never carries `Manba`/`Sahifa`.

## 5. What a manager can and cannot do

**Cannot do anything in Telegram.** The group message carries no buttons and no
inline keyboard, and the bot ignores the group entirely:

```ts
// src/app/api/telegram/webhook/route.ts:93-95
// Only private chats run the flow — the bot is also a member of the managers'
// group, and must stay silent there.
if (message.chat?.type !== "private") return;
```

Typing `taken`, `/done` or a reply under a notification does nothing at all —
nothing is parsed, recorded or acknowledged. Callbacks exist in this codebase
only in the customer's private chat, for service selection.

**Follow-up happens outside the bot**, by phone or Telegram, using the numbers
in `siteConfig.contacts.phones`. Working hours:
`Dushanba — Shanba: 09:00 – 19:00` (`config/site.ts:261`).

The customer is told exactly this (`managersReply()`, `telegram-bot.ts:61`): the
sales managers will contact them on the listed numbers, and they may call
themselves.

## 6. Observable delivery failures

This is the only silent failure in the system, and it matters.

When the group post fails (`route.ts:242-257`):

1. The lead is written to the **runtime log** via `console.error`, as
   `[bot] group delivery failed: <reason> {"name","phone","service","details","receivedAt"}`.
   Everything needed to call the customer back is in that line.
2. **The customer is thanked anyway** — `managersReply()` is sent after the
   failure branch, unconditionally.

So a customer can hold a confirmation message saying managers will be in touch
while **no manager ever saw the lead**. There is no queue and no retry beyond
the two attempts. Recovery means someone reading the deployment logs.

Consequences for a manager: if a customer says they already applied and you have
no record of it, believe them. Never tell a customer they did not submit
anything.

Other failure shapes:

| Symptom | Cause |
|---|---|
| Nothing arrives at all, ever | `TELEGRAM_WEBHOOK_SECRET` unset ⇒ every update 503s |
| Nothing arrives from the website | Telegram env incomplete ⇒ `/api/lead` returns the delivery error to the visitor |
| `chat not found` in the logs | wrong `TELEGRAM_MANAGER_CHAT_ID`, or the bot was removed from the group |
| Customer sees "texnik xatolik" | `sendTelegramMessage` exhausted both attempts |
| Form silently "succeeds" but nothing arrives | honeypot or <1500 ms ⇒ treated as a bot, by design |

## 7. Health check

`GET /api/health` exists, and `getBotInfo()` (`telegram.ts:222`) calls `getMe`
so a deployment can be verified without submitting a test lead. It returns only
the bot's public username — never the token.
