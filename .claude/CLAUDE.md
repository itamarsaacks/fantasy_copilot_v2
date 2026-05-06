# Fantasy NBA Copilot v2

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
- Read this file (`CLAUDE.md`) and the user's `MEMORY.md` at session start.
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
- `HANDOFF.md` (added later) — original migration context

## Parallel work
Use the built-in `Agent(isolation: "worktree")` for any parallelizable work. Don't manually create branches.
