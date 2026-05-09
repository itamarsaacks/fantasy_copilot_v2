---
name: start-session
description: Use at the START of any new Claude Code session in this project. Brings the new session up to speed on where the project is, what was last in flight, and the working style. Auto-invoke when the user types `/start-session` or asks for a status report at session start.
---

# Start session — orient before doing anything

Goal: in 60 seconds, this session knows everything the previous session knew. No "where were we?" friction.

## Steps (do them in order, narrate each one)

### 1. Read the durable context
- `.claude/CLAUDE.md` — architecture + working rules + how-we-work patterns
- `MEMORY.md` (auto-loaded by harness)
- `SESSION_NOTES.md` — read the most recent entry carefully. That's where you find what was in flight when the last session ended.

### 2. Check repo state
Run these in parallel via the Bash tool:
- `git status --short`
- `git log --oneline -15`
- `git diff --stat` (if status shows uncommitted changes)

If there are uncommitted changes, find out what they are before assuming. The previous session may have intentionally left work in progress that the new session should continue.

### 3. Check infrastructure state
Quick health checks (parallel):
- `docker ps --filter name=fantasy_copilot_v2_db --format "{{.Names}} {{.Status}}"` — Postgres container
- `ps aux | grep -E "(uvicorn app.main|next dev|ngrok)" | grep -v grep | head -5` — backend, frontend, tunnel
- `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health` — backend reachable

If anything is down, **report it but don't start it without asking.** The user might have stopped things deliberately.

### 4. Run the smoke test (only if backend + DB are up)
```bash
bash scripts/smoke.sh
```

If it passes, great. If it fails, that's the most important thing to surface — the previous session may have left a regression. **Fix nothing yet — just report.**

### 5. Report to the user

Format the report tightly. Example:

```
Status check —

**Last commit:** abc1234 — Phase 8.6 conversation memory + analyst tools (2 days ago)
**Uncommitted:** clean / 3 files modified in src/components/team/ (work-in-progress per session notes)
**Last session left in flight:** [from SESSION_NOTES.md, the "Next session should consider" + "In flight" sections]
**Env:** Postgres ✓, uvicorn ✓ on :8000, frontend ✓ on :3000, ngrok ✓
**Smoke test:** ✓ 5/5 green / ✗ failed at step 4 (chat agent — see output below)

What do you want to work on?
```

Then wait for the user to direct you. Do not propose work unprompted.

## Anti-patterns

- **Don't start coding before the report.** Even if the user typed "/start-session and let's do X", give the report first. It takes 30 seconds and catches surprises.
- **Don't start any service the user didn't ask you to start.** If uvicorn is down, surface that fact. Don't auto-restart it.
- **Don't summarize SESSION_NOTES.md from a high level.** Quote the relevant lines. The user wrote them; they know the words.
- **Don't skip the smoke test if the stack is up.** It's cheap and catches "the previous session left a regression that nobody noticed yet."

## When to skip this skill

- The session is already in progress (this is for fresh starts only).
- The user explicitly says "skip the status check, just do X."
- This session has already run /start-session within the last few turns.
