# Fantasy NBA Copilot v2

## Read first

For current status, **read `docs/PROJECT_STATE.md` and the latest entry of
`SESSION_NOTES.md`**. Those are kept current; this file describes
durable design + working rules. As of 2026-05-17 all five product
tabs ship + Players v2 detail experience + eval dashboard live.
Agent has 15 tools (not 13). See `PROJECT_STATE.md` for the inventory.

## What this is
A public Fantasy NBA copilot. Users connect a Yahoo Fantasy Basketball league via OAuth and chat with an AI that knows their roster, league rules, free agents, projections, schedules, injuries, and live NBA news. Not a personal tool — built to ship to other users.

## Architecture
Next.js frontend ↔ FastAPI backend (Postgres + Alembic). A LangChain `deepagents` deep agent with sub-agents and a virtual filesystem orchestrates work; sub-agents call tools that read from Postgres. A deterministic projection engine owns all numeric output — the LLM never estimates stats. APScheduler runs tiered, active-user-aware sync of Yahoo + NBA + news. Auth is Yahoo OAuth 2.0 → JWT in HTTP-only cookies. All agent runs are traced in LangSmith.

## Core rules (non-negotiable)
- The LLM never estimates a stat. Numbers come from the projection cache only.
- Every DB read is scoped to `(user_id, league_key)`. No global state.
- Yahoo OAuth redirect URI is HTTPS only — ngrok locally.
- Projections are cached, not stored forever. Stale-flag + recompute pattern.
- Team-cascade invalidation: a player's injury, return, trade, or coaching change invalidates EVERY teammate's projection.
- Sync transactions are split per concern; one Yahoo error never wipes a roster.
- Instantiate the deep agent once at app start. Never reconstruct per request.
- Soft-delete users + leagues; hard-delete transient sync data.
- Every new capability gets its own sub-agent. Don't bloat the main agent.

## Working rules (every session)
- The SessionStart hook runs `git status`, `git log --oneline -10`, `git diff --stat`. Read the output before doing anything.
- Read this file (`CLAUDE.md`), the user's `MEMORY.md`, AND `SESSION_NOTES.md` at session start. Skim the last 3 entries — that's where you find what was in flight.
- One change at a time. Found a second issue? Propose a separate task.
- Never commit without showing me the diff first.
- Never push to main without explicit confirmation.
- Never create branches with auto-generated names. Real names only: `feature/yahoo-oauth`, `fix/news-sync-timeout`.
- Never create files I haven't asked for, especially `.md` files outside `docs/`.
- If unclear, ask. Don't guess.
- Verify before claiming done — show real test output and (for UI) screenshots.
- Propose new skills, never auto-create them.
- **Before any commit:** run `bash scripts/smoke.sh` and show the output. If it doesn't pass, the work isn't done. See `.claude/skills/before-commit/SKILL.md` for the full ritual.
- **Verification standard:** "did I prove it works end-to-end, against real data, on the actual running stack?" — not "did the function I changed return the right value in isolation."

## How we work (read carefully — these patterns matter)
This section exists because new sessions tend to feel worse than long-running ones. The user wants every session to feel the same. Follow these patterns deliberately.

- **Plan in numbered sub-steps before non-trivial work.** Tell the user the plan, then narrate each sub-step as you do it. Do NOT charge through silently.
- **Show real command output, not assertions.** "Smoke test passed" without the actual output is not enough. Paste the lines.
- **If something looks off, STOP and ask.** Don't guess your way through. The cost of a clarifying question is tiny; the cost of a wrong assumption that compounds is large.
- **Each phase ends in a committable working state.** No half-finished phases. If you can't ship X tonight, scope down to a smaller X that ships clean.
- **For UI changes, verify visually.** Use Playwright via the MCP — navigate, screenshot, look at it. "It compiles" is not verification.
- **For backend changes that touch the agent or DB, show real responses.** Hit `/api/chat` with curl, paste the actual reply. Query Postgres, show row counts before + after.
- **The user is not a programmer.** Explain *why* before *what* on big decisions. Use plain English. Avoid acronym soup. When you must use a term, define it inline.
- **Be honest about tradeoffs.** Yes-manship is worse than disagreement. If a request is ambitious for the time available, say so and propose a smaller version. If a path you're about to take has a downside, surface it before committing.
- **One change per commit.** Bundling unrelated changes into one commit makes future sessions confused about what was intentional.
- **End each working session with `/wrap-session`.** It updates SESSION_NOTES.md so the next session can pick up cleanly. (See `.claude/skills/wrap-session/SKILL.md`.)

## User context (durable facts about the person you're working with)
- **Not a programmer.** Has product instincts, not engineering ones. Prefers explanations of *why* over *what*. Code is yours to write; UX trade-offs are joint.
- **Hates being surprised.** If you're about to do anything destructive, ask first. If you find a problem, name it before fixing it. Don't silently rewrite their decisions.
- **Wants narration, not silence.** Long stretches of tool calls without text feel like Claude went away. Short status lines between major steps are a feature, not noise.
- **Reads screenshots.** When testing UI, take screenshots and reference them. Don't just say "it looks good."
- **Trusts you to push back on bad ideas.** If they propose something that conflicts with a hard rule (e.g. "let the LLM estimate this stat"), say no and explain why.
- **Long working sessions, real product ambition.** This is going to ship. Treat it like a real product, not a toy.

## Local dev
- DB: `docker compose up -d` (Postgres 16)
- Backend: `cd backend && uvicorn app.main:app --reload --reload-dir app --port 8000`
- Frontend: `cd frontend && npm run dev`
- Tunnel (Phase 2+): `ngrok http 8000` — paste URL into Yahoo dev app + `backend/.env`
- Replay mode (off-season testing): set `APP_MODE=replay` and `AS_OF_DATE=YYYY-MM-DD` in `backend/.env`

## Tech stack
- Backend: FastAPI + SQLAlchemy (async) + asyncpg + Alembic + Pydantic + httpx
- Agent: `deepagents` + `langchain-anthropic` + LangSmith tracing
- LLM: Anthropic Claude (latest Opus / Sonnet)
- DB: Postgres 16 (Docker locally, Neon for prod)
- Frontend: Next.js (App Router) + React + Tailwind + shadcn/ui
- Auth: Yahoo OAuth 2.0 → JWT in HTTP-only cookies
- Scheduler: APScheduler (tiered, active-user-aware)

## Sub-agents
`roster_analyst`, `waiver_analyst`, `trade_evaluator`, `trade_suggester`, `matchup_analyst`, `news_analyst`, `historical_analyst`. Each gets its own focused prompt + minimal tool list. All runs traced in LangSmith automatically.

## Yahoo API gotchas (the ones that bite)
- Use `/players;player_keys=.../stats;type=X` — `;out=stats;type=X` silently ignores `type`.
- `scoring_type` field drives prompt + projection model. Raw values: `point`, `headpoint`, `head`, `roto`.
- Refresh tokens expire after ~60 days inactivity → reconnect UX is mandatory.
- `xoauth_yahoo_guid` is no longer reliably returned in the token response — fetch GUID via `/users;use_login=1` instead.
- Game key for 2025–26: `466`.
- Off-season is the default state for half the year. Always handle it.

## League types
Yahoo's raw `scoring_type` values (verified 2026-05 against live API):
- `point` — season-long total fantasy points
- `headpoint` — head-to-head points (uses `stat_modifiers`)
- `head` — head-to-head categories (uses `stat_categories`)
- `roto` — rotisserie

Stored as-is in `leagues.scoring_type`. The agent + projection engine map these
to behavior (prompt selection, projection model). Older docs may say
`head2head_points` / `head2head_categories` — those are NOT what Yahoo returns.

## Where docs live
- `docs/decisions/` — ADRs (architecture decision records)
- `docs/EVAL_HARNESS.md` — design + operating manual for the eval harness (what it is, intent taxonomy, snapshot strategy, generated vs promoted cases, the `eval-author` skill, weekly digests). Read before touching `app/evals/`.
- `HANDOFF.md` (added later) — original migration context

## Eval harness (status: E0 + E1 ✅ — 6 cases, 24/24 passing)
- Code at `backend/app/evals/`. Cases at `app/evals/cases/{manual,promoted,generated}/`. Topic contracts at `app/evals/probes/` (Phase E4).
- `schema.py` is the single source of truth for case shape — Pydantic-validated. Every case has a structured `intent` block (question_type / complexity / domain / answer_shape).
- `loader.py` parses YAML → `EvalCase`.
- **Process eval only** (see `docs/EVAL_HARNESS.md` §4): the runner invokes the real agent against the live local DB and asserts on what the agent *did* (tools called, arguments, phrases to avoid, cost/latency budgets) — NOT on specific output content. The harness has no snapshot/frozen-state machinery; we decided against it because every bug class reduces to wrong-tool / wrong-args / hallucinated-synthesis, all catchable in live mode.
- **The load-bearing trick**: `response_contains_none` is how we catch synthesis bugs. List specific never-OK phrases ("Dolphins", "category coverage", "I don't have"). When we discover a new failure mode, add it to the relevant case's `response_contains_none` — don't reach for frozen state.
- **Severity tiers** (§6): each assertion is `critical` (default for behavioral checks) or `warning` (default for budgets). Verdicts: 🟢 PASS / 🟡 SOFT_PASS (criticals clean, warning drift) / 🔴 FAIL (any critical failed) / 💥 ERROR.
- **Hybrid case sources** (§13):
  - Generated (volume, Opus-authored via `eval-author` skill): behavior-only assertions via topic contracts in `app/evals/probes/`.
  - Promoted (rare, from real LangSmith chats via promoter).
- **Self-reference mitigation**: generator uses Opus; agent under test uses Sonnet.
- **Monitoring floor**: weekly auto-digest in `app/evals/digests/`. ~5 min/week.
- **Cost policy** (§14): tiered runs — smoke subset on every commit (pennies), domain-filtered during dev, full suite nightly + on-demand pre-merge (~$10–15/day at maturity). Don't run full suite on every commit.
- Phased build: E0 (schema) ✅ → E1 (live runner + severity + 6 cases) ✅ → E2 (Postgres results + LangSmith) → E3 (promoter) → E4 (eval-author skill) → E5 (dashboard).

## Parallel work
Use the built-in `Agent(isolation: "worktree")` for any parallelizable work. Don't manually create branches.
