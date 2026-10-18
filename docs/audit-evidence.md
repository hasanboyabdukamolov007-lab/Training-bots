# Audit Evidence

Raw commands and their actual output, captured 2026-10-18 before any file was
created in this repository. Reproducible by re-running them on a fresh clone.

## Working tree is empty

```
$ ls -la
total 12
drwxr-xr-x 3 root root 4096 Oct 18 03:07 .
drwxr-xr-x 3 root root 4096 Oct 18 03:07 ..
drwxr-xr-x 7 root root 4096 Oct 18 03:07 .git

$ find . -path ./.git -prune -o -type f -print | wc -l
0
```

## No commits, no branches

```
$ git status --short
fatal: your current branch 'claude/focused-darwin-z0el2w' does not have any commits yet

$ git branch -a
(no output)

$ git log --oneline -15
fatal: your current branch 'claude/focused-darwin-z0el2w' does not have any commits yet

$ git ls-remote --heads origin
(no output)
```

## Remote confirms empty

```
$ git remote -v
origin	https://github.com/hasanboyabdukamolov007-lab/Training-bots (fetch)
origin	https://github.com/hasanboyabdukamolov007-lab/Training-bots (push)
```

GitHub API, `list_branches(hasanboyabdukamolov007-lab/Training-bots)`:

```json
[]
```

## No production bot identified elsewhere

`list_repos` for the account returned 8 repositories. None is identifiable as a
Telegram customer-service bot by name:

```
hasanboyabdukamolov007-lab/Training-bots              (public,  this repo, empty)
hasanboyabdukamolov007-lab/Alcana-Print-taplink       (private)
hasanboyabdukamolov007-lab/Language-learning-platforms(private)
hasanboyabdukamolov007-lab/alcana_taplink             (private)
hasanboyabdukamolov007-lab/Task-manager               (private)
hasanboyabdukamolov007-lab/Alcana-taplink-page        (private)
hasanboyabdukamolov007-lab/daily-motivational-shorts  (private)
hasanboyabdukamolov007-lab/hasanboy-fitness-os        (private)
```

This session is scoped to `training-bots` only. No other repository was opened,
and none was added to the session, because that was not requested. `Task-manager`
was the nearest-sounding candidate; the attempt to list it returned:

```
Access denied: repository "hasanboyabdukamolov007-lab/task-manager" is not
configured for this session. Allowed repositories: hasanboyabdukamolov007-lab/training-bots.
```

so its contents are unknown and no claim is made about it either way.

## Telegram API calls made during the audit

**None.** No token was present in the environment, none was requested, and §5/§20
of the specification forbid sending Telegram messages before the test environment
and chat allowlist are configured and verified.

---

# Second audit — the production system

After the first audit reported an empty repository, the owner identified
`hasanboyabdukamolov007-lab/Alcana-taplink-page`. It was added to the session
and cloned read-only at commit `9c701bb` (2026-09-18).

## Baseline health (measured)

```
$ npm ci
(clean)

$ npx tsc --noEmit
(no output, exit 0)

$ npx vitest run
 Test Files  13 passed (13)
      Tests  175 passed (175)
   Duration  1.70s
```

## Absence of request-management features

```
$ for t in assign claim escalat reopen complaint ticket requestId audit \
           "internal note" prisma drizzle sqlite postgres admin; do
    echo "$t -> $(grep -riIl "$t" src/ scripts/ | wc -l) files"
  done
assign        -> 0 files
claim         -> 0 files
escalat       -> 0 files
reopen        -> 0 files
complaint     -> 0 files
ticket        -> 0 files
requestId     -> 0 files
audit         -> 0 files
internal note -> 0 files
prisma        -> 0 files
drizzle       -> 0 files
sqlite        -> 0 files
postgres      -> 0 files
admin         -> 0 files
```

No database or ORM dependency:

```
$ grep -iE "prisma|drizzle|sequelize|typeorm|mongoose|sqlite|redis|kysely" package.json
(no matches)
```

The terms that *did* match were false positives, confirmed in context:

```
$ grep -riIn -E "\bsla\b|priority|\brole\b" src/ scripts/
src/components/lead-form.tsx:168:  <p role="status" ...     # ARIA, not a user role
src/components/lead-form.tsx:354:  <p ... role="alert" ...  # ARIA
src/components/sticky-call-bar.tsx:8: * ... in the agreed priority:   # a comment
src/app/sitemap.ts:11:      priority: 1,                   # sitemap XML priority
```

`status` matches are React form state (`lead-form.tsx:41` `type Status =`) and
HTTP status codes. No request status model exists.

## The bot is silent in the manager group

`src/app/api/telegram/webhook/route.ts:93-95`:

```ts
// Only private chats run the flow — the bot is also a member of the managers'
// group, and must stay silent there.
if (message.chat?.type !== "private") return;
```

## Configured environment variables of the production system

```
$ grep -E "^[A-Z_]+=" .env.example | cut -d= -f1
TELEGRAM_BOT_TOKEN
TELEGRAM_MANAGER_CHAT_ID
TELEGRAM_WEBHOOK_SECRET
NEXT_PUBLIC_PHONE
... (remaining NEXT_PUBLIC_* are page content: phones, socials, address, URLs)
```

One bot token. No per-manager identity, and no role configuration.

## Telegram API calls made during this audit

**None.** `api.telegram.org` is additionally unreachable from this environment:

```
$ curl -sS -o /dev/null -w "%{http_code}\n" --max-time 15 https://api.telegram.org/
curl: (56) CONNECT tunnel failed, response 403
000
```

## Production repository modifications

None. The clone is read-only; `npm ci` wrote only the git-ignored
`node_modules/`.
