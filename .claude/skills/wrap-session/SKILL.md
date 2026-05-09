---
name: wrap-session
description: Use at the END of a working session. Updates SESSION_NOTES.md and (if anything significant emerged) MEMORY.md so the next session can pick up cleanly. Auto-invoke when the user types `/wrap-session` or signals they're stopping for the day ("let's stop", "we're done for tonight", "wrapping up").
---

# Wrap session — leave a clean handoff for next time

Goal: write a SESSION_NOTES.md entry detailed enough that a fresh Claude with no memory of this conversation could resume work without asking the user "where were we?"

## Steps

### 1. Take stock
Run these in parallel:
- `git status --short`
- `git log --oneline -10` (so you can see what landed THIS session vs before)
- `git diff --stat` (if anything is uncommitted)

### 2. Identify session boundaries
Where did this session START? Look at the last commit before the session began (often visible in git reflog, or simply ask the user). Everything after that is "this session's work."

Decide:
- **What landed (committed and pushed)** — list by commit hash + one-line summary
- **What's in flight (uncommitted)** — what files, what's the rough state, is it safe to leave or should it commit
- **What got DECIDED but not yet built** — parked plans, scope changes
- **What got REJECTED** — paths the user said no to (worth recording so next session doesn't re-propose them)

### 3. Draft the new SESSION_NOTES.md entry

Use this exact format. Date in YYYY-MM-DD. Title is a short noun phrase.

```markdown
## YYYY-MM-DD — Short title of what this session was about

**Done this session:**
- Commit hash + one-line summary
- Commit hash + one-line summary
- Non-commit accomplishments (e.g. "diagnosed but didn't fix the X bug")

**Next session should consider:**
- Concrete options the user mentioned wanting to do next, ordered by priority
- Any deadlines or external dependencies

**In flight / uncommitted:**
- File paths + rough state. If safe to leave, say so. If it would be confusing
  to find tomorrow, suggest the user run /wrap-session to commit before stopping.

**Env state:**
- Postgres: up/down
- Backend uvicorn: running on what port, what mode (replay/live)
- Frontend: running on what port (only if it was running)
- ngrok: URL or "not running"
- Anything weird (e.g. "JWT_SECRET was rotated, browser cookies invalid")

**Open questions / parked decisions:**
- Things you and the user discussed but didn't decide

**User mood at session end:**
- Tired? Excited? Frustrated? About to do other things? This sets the tone
  for next session's opening.
```

### 4. Show the draft to the user

Show the full draft entry as a code block. Ask: "this is what I'll write to SESSION_NOTES.md — anything to add, change, or remove?"

**Wait for explicit approval before writing.**

### 5. Write SESSION_NOTES.md

After approval:
- Read the current SESSION_NOTES.md
- Insert the new entry at the top (above all existing entries)
- If there are now more than **5 entries**, remove the oldest. The git log is the durable record; SESSION_NOTES.md is a working surface, not an archive.

### 6. Consider a memory update

Did anything emerge this session that's a **durable preference** (e.g. "user prefers commits per phase, not per file" / "user wants screenshots before any UI commit") that's not already encoded in CLAUDE.md or memory?

If yes, propose a memory update — cite the moment it was established, propose the wording, ask before writing.

If no, skip this step. Most sessions don't produce new durable preferences.

### 7. Final check

Before declaring the session wrapped:
- Are there uncommitted changes that should be committed?
- If yes, ask: "Want me to commit these before we stop?"
- If the user says yes, follow the `before-commit` skill (smoke test + show diff + push only on approval).
- If the user says no, mention them in the SESSION_NOTES.md "In flight" section so they're not lost.

## Anti-patterns

- **Don't write SESSION_NOTES.md without showing the draft first.** The user knows what mattered tonight better than you do.
- **Don't summarize the session in vague terms ("worked on the agent").** Concrete commit hashes + one-liner each.
- **Don't pad the entry.** Five short bullets > ten verbose ones.
- **Don't propose memory updates for things that aren't durable.** A one-off task is not a preference.
- **Don't commit on the user's behalf without asking.** Even at end-of-session, commits are user-initiated.

## When to skip this skill

- Mid-session checkpoints (use it ONLY at the actual end).
- The user is in the middle of explaining something and you want to wrap unilaterally — don't.
- The user explicitly says "skip the wrap, just commit and push" — then follow `before-commit` directly.
