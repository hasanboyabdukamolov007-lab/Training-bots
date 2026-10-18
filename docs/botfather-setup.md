# Setup: five training bots, test group, and verification

Do these steps in order. Nothing here requires you to paste a token into source
code, into a chat, or into this repository.

> **Important:** this guide gets your *environment* ready. It does not make the
> training subsystem work — that is blocked on the production bot, see
> [`../AUDIT.md`](../AUDIT.md). You can complete these steps now so the
> environment is waiting when the application exists.

## Step 1 — Create the five bots in @BotFather

In Telegram, open [@BotFather](https://t.me/BotFather) and run `/newbot` five
times. Each time you are asked for a display name, then a username.

| # | Display name to enter | Username | Logical role |
|---|---|---|---|
| 1 | `Training Manager 1` | your choice, must end in `bot` | `TRAINING_MANAGER_01` |
| 2 | `Training Manager 2` | your choice, must end in `bot` | `TRAINING_MANAGER_02` |
| 3 | `Training Manager 3` | your choice, must end in `bot` | `TRAINING_MANAGER_03` |
| 4 | `Training Administrator` | your choice, must end in `bot` | `TRAINING_ADMIN_01` |
| 5 | `Training Leader` | your choice, must end in `bot` | `TRAINING_LEADER_01` |

Usernames are globally unique and most obvious ones are taken. Do not assume any
particular username is free — BotFather will tell you, and you simply try
another. A prefix tied to your own org works well, e.g.
`acme_training_mgr1_bot`. Whatever you pick, record which username maps to which
logical role; the role is what the code uses, the username is only for humans.

Recommended per-bot hygiene, still in BotFather:

- `/setdescription` — mark each one clearly, e.g.
  `TEST/TRAINING BOT — synthetic data only. Not a real support channel.`
- `/setjoingroups` → **Enable** for all five (they must be able to join the test group).
- `/setprivacy` → **Disable** privacy mode *only if* a scenario needs the bot to
  read all group messages. Leave it **Enabled** otherwise. See the limitation note below.

BotFather shows each token once, in the form `<digits>:<35-ish chars>`. Treat it
like a password.

## Step 2 — Put the tokens in `.env` (never in code, never in Git)

```bash
cp .env.example .env
```

Open `.env` in an editor and replace each placeholder with the matching token.
`.env` is already listed in `.gitignore`, so it will not be committed.

If you prefer a secrets manager over a dotfile, every variable in `.env.example`
can instead be supplied as a normal process environment variable; the verifier
reads the process environment first and the file second.

**If a token is ever exposed** — committed, pasted into a chat, or printed in a
log — revoke it immediately with `/revoke` in BotFather and issue a new one. A
leaked token lets anyone fully control that bot.

## Step 3 — Create the dedicated test group

1. Create a **new** Telegram group. Do not reuse any group that production uses.
2. Name it so nobody can mistake it, e.g. `[TEST] Manager Training`.
3. Add all five training bots: group → *Add members* → search each bot's username.
   A bot cannot add itself, and you cannot be added on its behalf; this is manual
   by design.
4. Add only the employees who are being trained. No real customers.
5. Upgrade it to a supergroup if Telegram has not already (it happens
   automatically when the group grows or when you set a username). Supergroup IDs
   start with `-100`.

### Granting rights

Give a training bot administrator rights **only** if a scenario genuinely needs
them. A bot cannot grant itself rights, and a valid token proves identity only —
never permission. Promote via group → *Administrators* → *Add admin*.

A reasonable default: leave all five as ordinary members, and promote only
`Training Administrator` if an admin-level scenario requires it. Keep Telegram
group permissions separate from the application's own role model; they are not
the same thing and should not be conflated.

## Step 4 — Find the group's numeric ID

Pick whichever is easiest:

- **Telegram Web** — open the group at `web.telegram.org`; the URL contains the
  ID. Prefix with `-100` to form the supergroup ID if it is not already there.
- **Export** — group → *Export chat history* shows the ID in the metadata.
- **From the API** — once a bot is in the group, send one message in the group,
  then read it back:

  ```bash
  # replace $T with one bot's token; this is read-only
  curl -s "https://api.telegram.org/bot$T/getUpdates" | python3 -m json.tool | grep -A3 '"chat"'
  ```

  The `chat.id` is the value you want. (`getUpdates` conflicts with a running
  webhook; only use it before the application is live.)

Put the ID in `.env` as **both** `TRAINING_MANAGER_GROUP_ID` and an entry in
`TRAINING_ALLOWED_CHAT_IDS`. The verifier refuses to contact a group that is not
in the allowlist, so a typo fails closed rather than messaging a random chat.

## Step 5 — Verify

```bash
python3 scripts/verify_training_bots.py
```

Requires Python 3.9+ and nothing else — no dependencies to install. It makes only
read-only calls (`getMe`, `getChat`, `getChatMember`), **sends no messages**, and
changes nothing. Run it as often as you like.

It checks, and reports each as `PASS` / `FAIL` / `BLOCKED` / `NOT TESTED`:

1. `TRAINING_ENVIRONMENT` is exactly `training` — otherwise it exits before any
   network call.
2. The group ID is set, numeric, and not the example placeholder.
3. The group ID appears in `TRAINING_ALLOWED_CHAT_IDS`.
4. Each of the five tokens is present, correctly shaped, and not a placeholder.
5. Each token resolves to a real bot via `getMe`, reporting its `@username` and id.
6. The five tokens are **five distinct bots** — reusing one token across two
   roles is reported as a failure.
7. The chat is a group or supergroup.
8. Each bot is actually a member, with its real status and actual admin rights
   read from `getChatMember` — never assumed from the token.

Exit status is `0` only when everything needed passed. A `PASS` here means the
environment is correctly configured; it is not a test run and asserts nothing
about the application.

To check the verifier itself without any network at all:

```bash
python3 scripts/test_verify_training_bots.py
```

## Telegram limitations you cannot configure away

These are platform behaviours, not gaps in this setup:

- **Bots cannot see each other's messages in a group.** The five training bots
  cannot observe or respond to one another. Every manager-to-manager scenario
  (hand-off, concurrent claim, reassignment) must be driven through the
  application's service layer, not through the group chat.
- **A bot cannot start a private chat** with a person or another bot; the other
  side must message it first.
- **With privacy mode on** (the default), a bot in a group receives only commands
  and replies directed at it — not all messages.
- **A bot cannot add itself to a group or promote itself.** Steps 3 and the
  rights grant are necessarily manual.
- A valid token tells you *who* a bot is, never *what it may do*.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `TRAINING_ENVIRONMENT guard FAIL` | Set `TRAINING_ENVIRONMENT=training` in `.env`. The guard is deliberate; do not remove it. |
| `still holds a placeholder` | You copied `.env.example` but did not replace that value. |
| `not shaped like a BotFather token` | Partial copy/paste. Re-copy the whole `digits:chars` string. |
| `Unauthorized` on `getMe` | Token wrong or revoked. Re-issue with `/token` in BotFather. |
| `same bot as TRAINING_MANAGER_0x` | Two roles share one token. Each role needs its own bot. |
| `group id is NOT in TRAINING_ALLOWED_CHAT_IDS` | Add the ID to the allowlist. Failing closed here is intentional. |
| `chat not found` on `getChat` | Wrong ID, missing `-100` prefix, or the bot is not in the group. |
| `status=left` / `status=kicked` | Add (or re-add) that bot to the group. |
| `network error: Tunnel connection failed` | Your network blocks `api.telegram.org`. Run the verifier from a host that can reach it. |
