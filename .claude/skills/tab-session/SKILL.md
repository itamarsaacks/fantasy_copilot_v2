---
name: tab-session
description: Use at the start of a per-tab implementation session in the reformation roadmap (Chat / Games / League / My Team / Players / Trades+Waiver). Every per-tab session opens identically — read the durable context, confirm the right branch, run smoke baseline, then work the tab's plan file. Auto-invoke when the user types `/tab-session <tab>` or starts work on any `feature/<tab>-tab` branch.
---

# Tab session — orient identically every time

Goal: every per-tab session (Chat mentions, Games, League, My Team, Players, Trades+Waiver) begins with the same ritual so the work feels continuous across tabs and across days. No "this session feels different from yesterday's."

This skill complements `/start-session` (the generic project-orient skill). Use this one when the task is a specific tab from the reformation roadmap.

## Inputs

The user calls `/tab-session <tab>` where `<tab>` is one of:
- `chat-mentions`
- `games`
- `league`
- `my-team`
- `players`
- `trades-waiver`

The corresponding branch is `feature/<tab>-tab` (or `feature/chat-mentions` for the first one).
The corresponding plan file lives at `docs/plans/<tab>.md`.

## Steps (do them in order, narrate each one)

### 1. Read the durable context (in this exact order)

1. `.claude/CLAUDE.md` — architecture + working rules
2. `docs/PROJECT_STATE.md` — current tab inventory + sync jobs + tool inventory
3. `SESSION_NOTES.md` — most recent 3 entries
4. **The master plan**: `~/.claude/plans/joyful-bubbling-dream.md` — the reformation roadmap. Section §2 (data foundation) and §3 (shared primitives) are the foundation every tab depends on. Section §4 has this tab's one-paragraph summary. Section §5 is this skill, restated.
5. **The tab's plan file**: `docs/plans/<tab>.md` (if it doesn't exist yet, the first thing this session does is draft it — see step 6).

### 2. Confirm the branch

```bash
git status
git branch --show-current
```

Acceptance: current branch is `feature/<tab>-tab`. NOT `main`. NOT a worktree path. If we're on the wrong branch, switch (`git checkout feature/<tab>-tab` or `git checkout -b feature/<tab>-tab` if it doesn't exist). Never work on `main` directly.

### 3. Check infrastructure (parallel, via Bash)

- `docker ps --filter name=fantasy_copilot_v2_db --format "{{.Names}} {{.Status}}"`
- `ps aux | grep -E "(uvicorn app.main|next dev|ngrok)" | grep -v grep | head -5`
- `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health`

If anything is down, report — don't auto-start.

### 4. Run smoke test as baseline

```bash
bash scripts/smoke.sh
```

Paste the output. If green: baseline established. If red: that is the most important finding — report it and stop. Do NOT start tab work on top of a red baseline.

### 5. Confirm replay mode is active (or live mode is intended)

Show `backend/.env` `APP_MODE` and `AS_OF_DATE` values. For most tab work during the reformation, replay mode with `AS_OF_DATE=2026-03-15` is correct (regular season is over IRL). For chat / mentions tab and any user-flow testing, live mode is fine.

### 6. Read or draft the tab plan file

If `docs/plans/<tab>.md` exists, read it and report the "what's next" section.

If it doesn't exist, draft it now using the master plan §4 paragraph for this tab as the seed. Structure:

```
# Tab plan — <tab>

## Context
Why this tab, what it does, link back to master plan §4.

## Data-foundation prerequisites
Which §2 items must be in place before this tab can ship. Confirm each is done.

## Shared primitives used
Which §3 items this tab consumes (DateToggle, PlayerAvatar, etc.).

## Net new code in this tab
- Backend endpoints (path + return shape)
- Frontend components (file paths)
- Agent tools (only if tab needs new ones; most don't)

## Phases (one committable phase per row)
| # | Phase | Deliverable | Smoke check |
|---|---|---|---|

## Verification
Replay-mode URLs to hit + expected output (per master plan §6).

## Out of scope
What this tab deliberately doesn't do.
```

Show the draft to the user, get approval, then save to `docs/plans/<tab>.md`.

### 7. Report to the user

Format tightly:

```
Tab session — <tab>

**Branch:** feature/<tab>-tab ✓
**Mode:** replay / live (APP_MODE=…, AS_OF_DATE=…)
**Smoke:** ✓ green / ✗ failed at step N
**Plan file:** docs/plans/<tab>.md ✓ (existing) | drafted (new — awaiting approval)
**Data-foundation prereqs:** ✓ all in place / ✗ missing X, Y (block on these first)
**Next phase per plan:** Phase N — <one line>

Ready to start Phase N?
```

## Working rules during the session

These are non-negotiable. They come from `.claude/CLAUDE.md` "How we work" but are repeated here because every tab session needs them top-of-mind.

- **One change at a time.** Found a second issue? Propose a separate task (`mcp__ccd_session__spawn_task` or note in `SESSION_NOTES.md`).
- **Single branch, single working tree.** NO `--spawn=worktree`. NO `git worktree add`.
- **Narrate before each step.** A 1-2 line "I'm about to X because Y" before running tools. Long silent stretches make sessions feel absent.
- **Show real command output.** No `| tail`, no "smoke test passed" without the lines. Paste verbatim.
- **Ask if unclear.** Don't guess product intent. A clarifying question costs seconds; a wrong assumption costs hours.
- **UI changes need visual verification.** Use Playwright/Claude_Preview to navigate the new screen, screenshot it, attach. Don't claim "it compiles" as proof.
- **Backend changes need real proof.** Write the migration, run it (`alembic upgrade head`), query the table with psql or `\dt`, paste the rows.
- **Each phase ends in a committable working state.** If a phase can't ship clean, scope down the phase.
- **No commit without showing diff first.** `git diff` before `git commit`. Wait for user approval unless they've said "go" on this phase.
- **Never push to main.** Always to the feature branch. PR-style merging is the user's decision.

## At session end

1. Run `bash scripts/smoke.sh`. Must pass. If it doesn't, the session isn't done — the work isn't shippable.
2. Run `/wrap-session` to update `SESSION_NOTES.md` + `PROJECT_STATE.md`.
3. Commit on the feature branch. Show diff first.
4. Summary back to the user:
   - What phases landed
   - What's left in the tab plan
   - What the next session should pick up (in flight items, deferred questions)

## Anti-patterns to avoid

- Starting Phase N+1 before Phase N is committed and smoke-passing.
- Bundling "while I was in there" refactors into a tab's commit history. File a spawn task instead.
- Reading the plan file once and never re-checking. Plan files evolve mid-session — re-read after big decisions.
- Treating the master plan as immutable. If a tab session uncovers a flaw in the master plan (`~/.claude/plans/joyful-bubbling-dream.md`), edit it. Master plan is living.
- Working on `main`. Hard rule.
- Skipping the smoke baseline because "it'll pass." It will not always pass. Skipping it loses 15 minutes diagnosing later.

## Acceptance test for the skill

A fresh Claude session, opening any `feature/<tab>-tab` branch and invoking this skill, produces a first message in the format of Step 7 — same shape, same sections, same "Ready to start Phase N?" hand-off. The user shouldn't be able to tell which day it is or which tab is being worked. Every session feels like the previous session continued.
