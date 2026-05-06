---
name: before-commit
description: Use BEFORE any git commit on this project. Mandatory verification ritual that catches "I tested the new thing in isolation but didn't notice I broke something else." Auto-invoke whenever about to run git commit, git push, or `gh pr create`.
---

# Before commit — verification ritual

This is the gate every commit must pass. No exceptions.

## Why this exists

Without this ritual, every change risks shipping with hidden integration breakage. Isolation tests prove "the thing I changed does what I changed it to do." They do NOT prove the rest of the app still works. This ritual closes that gap.

## Mandatory steps

### 1. Run the smoke test

```bash
bash scripts/smoke.sh
```

It must exit 0. The script verifies the actual running stack:
- backend boots and `/health` responds
- Postgres is reachable
- all critical routes are registered
- JWT minting works (catches env/secret breakage)
- chat agent answers a real question, calling at least one tool

If it fails: **fix the failure before anything else.** Do not commit "around" a smoke failure.

Show the user the last ~10 lines of output.

### 2. Run the phase-specific manual check

The smoke test cannot exercise everything. Pick whichever applies:

| You touched... | Manual check |
|---|---|
| OAuth / auth callback / cookies | User completes browser OAuth flow, pastes callback JSON. Confirm `ok: true` AND grep uvicorn logs for the expected post-callback behavior (initial sync, etc.). |
| A new agent tool | Ask the agent a real question that should trigger the tool. Paste reply + `tool_calls` count. Tool count must be ≥ 1 if the question requires it. |
| Frontend / UI | Take a screenshot of each affected page. Attach or describe. |
| A sync job | Run via `/admin/sync-now` (or the relevant admin endpoint). Paste row counts before AND after. |
| A migration | Confirm `alembic upgrade head` exited clean. Run a sync that touches new columns. Query the DB and show the new columns are populated. |
| The freshness controller / scheduler | Wait one tick interval (~70s in live mode). Grep logs for the expected tick output. |
| Connector / Yahoo API call | Make the actual call against live Yahoo + show the parsed response shape. |

### 3. Show `git diff --cached --stat`

The user always sees what's about to be committed.

### 4. Confirm working rules were followed

- No auto-named branches (no `claude/inspiring-…`).
- No `.md` files created outside `docs/` unless explicitly requested.
- No new dependencies without telling the user.
- No `--no-verify`, `--force`, or other safety bypasses.

### 5. Commit message MUST include

- One-line summary of what changed.
- Bulleted list of substantive changes.
- The verification commands run + real output excerpts (counts, sample replies). This is the durable handoff between sessions.
- Known acceptable trade-offs or follow-up items, if any.

### 6. Push only after explicit user approval

After the commit lands locally, ASK: "push to main?" Wait for an explicit yes. Never push automatically.

## Anti-patterns (red flags — these mean you are NOT done)

| Thought | Reality |
|---|---|
| "I tested the new function in isolation" | Not enough. Run the smoke test. |
| "The endpoint returned 200" | Check the response body. 200 with empty data is a regression. |
| "Imports succeed" | That's not a verification. |
| "It's a small change, smoke test is overkill" | Especially then. Small changes break things in surprising places. |
| "The unit test passes" | Unit tests don't catch middleware / cookie / dependency wiring breakage. |
| "I'll run the smoke test after committing" | No. The commit is the gate. |
| "It worked when I called the function directly via Python" | Different code path than HTTP. Doesn't count. |

## When the smoke test itself needs to change

If you add a new critical route, sub-agent, or sync job, **update `scripts/smoke.sh` in the same commit** so the gate stays meaningful. Don't grandfather new surfaces past the gate.
