# ADR 0001 — Stack and core architecture

**Status:** Accepted
**Date:** 2026-05-06

## Context

We are rebuilding the Fantasy NBA Copilot from scratch in a clean repo. The previous version shipped to production but accumulated structural problems: SQLite locking under concurrent sync, hand-wired LangGraph agent that grew hard to extend, no replay mode for off-season testing, and ad-hoc background jobs running on a fixed cron schedule regardless of user activity.

This ADR records the foundational choices for v2.

## Decisions

### Backend — FastAPI + SQLAlchemy (async) + Alembic
Async-first because Yahoo + NBA + LLM calls are all network-bound. Alembic for versioned migrations instead of inline DDL.

### Database — Postgres 16
SQLite locking caused real production pain. Postgres handles concurrent writes, provides `JSONB` and `TIMESTAMPTZ` natively, and supports the analytics queries we plan to build. Local via Docker Compose; production target is Neon (serverless Postgres, generous free tier). SQLAlchemy keeps the code DB-agnostic.

### Agent — `deepagents` + LangChain + LangSmith
The previous flat-agent design with 13 tools was struggling with multi-step reasoning. Switching to a deep-agent pattern: a top-level orchestrator, focused sub-agents per cognitive task (waiver, trade, matchup, news, historical, roster), and a virtual filesystem for sub-agents to share intermediate work. LangSmith tracing comes free with the LangChain stack.

### LLM — Anthropic Claude
Best-in-class tool use, which is the dominant cost driver for agent quality. Default to the latest Opus / Sonnet.

### Frontend — Next.js (App Router) + React + Tailwind + shadcn/ui
Already what the previous frontend used; works well; rich ecosystem. shadcn/ui gives us copy-paste components we own, no version drift.

### Auth — Yahoo OAuth 2.0 → JWT in HTTP-only cookies
Required by Yahoo. JWT is the boring, secure default for SPA-style flows. Refresh tokens stored in DB, never sent to the browser.

### Scheduler — APScheduler, tiered + active-user-aware
The previous fixed-cron approach burned compute when no one was using the app. New design: each sync tier has its own freshness threshold and only runs for users seen in the last ~10 minutes. Game-log restatements re-sync the prior day in the morning. News sync only runs during the season.

### Projections — cached, not stored forever
A `projection_cache` table holds one row per (player, league), overwritten when invalidated. A separate `projection_history` table gets a daily snapshot for trend analytics. Invalidation is event-driven: any change to a player's stats, news, role, or any teammate's status (cascade) flips a `stale` flag; a background worker drains the queue.

### Off-season — replay mode from day one
With `APP_MODE=replay` and `AS_OF_DATE=YYYY-MM-DD`, the connector layer serves recorded fixtures and the rest of the app behaves as if it's an in-season day. Lets us develop and test every feature during the off-season. Same code path runs in `live` mode against real APIs when the season returns.

## Consequences

- Local dev requires Docker (for Postgres). One extra dependency vs. SQLite.
- Postgres connection strings differ between local + Neon — managed via `DATABASE_URL` env var.
- All datetime handling uses `TIMESTAMPTZ` and goes through an `as_of_now()` helper that respects `AS_OF_DATE` in replay mode. Direct `datetime.now()` calls are forbidden in domain code.
- LangSmith costs scale with traffic. Mitigation: sample traces in production, gate by env var.
- Sub-agent-first means more boilerplate per capability, but better debuggability and prompt quality.

## Alternatives considered

- **Stay on SQLite + WAL mode** — would patch some lock issues but not the analytics or scaling story.
- **Anthropic Agent SDK directly instead of LangChain** — simpler, but the deep-agent ecosystem is currently more mature in LangChain.
- **Last-season replay instead of current-season snapshot** — would not include the user's actual league, less useful for end-to-end testing.

## Revisit when

- Postgres concurrent-write contention shows up under real user load.
- LangChain version churn becomes a maintenance burden.
- Anthropic Agent SDK gains feature parity with `deepagents`.
