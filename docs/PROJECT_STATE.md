# Fantasy Copilot v2 — Project state

> Single source of truth for "where are we, what's shipped, what's planned,
> what's missing." Read this before authoring eval cases, planning UI work,
> or scoping new features. Update whenever scope shifts.

_Last updated: 2026-05-17_

---

## App shape (tabs)

| Tab | Status | Latest commit | What it does |
|-----|--------|---------------|--------------|
| **Chat** | ✅ Shipped (Phase 6/7) | — | Conversation UI, agent w/ 15 tools, AsyncPostgresSaver persistence |
| **Team** | ✅ Shipped v1 | `68f2d1f` | Per-date roster grid, projection / actual fps, status badges, slot what-if swap |
| **Players** | ✅ Shipped v2 | `07a4e5d` | Search/filter/sort + click-row drawer (stats / schedule / history / news) + multi-player compare. Date range arbitrary across 365 days back, 90 days ahead. |
| **Waivers** | ✅ Shipped v1 | `3a6892f` | Top pickups + drop candidates + paired-swap suggestions over a chosen window |
| **League** | ✅ Shipped v1 | `6dddd27` | Full standings table + scoring rules + league settings |
| **Trades** | ✅ Shipped v1 | `32b7cfa` | Dual-roster trade builder with delta + verdict; reuses cached per-game projections |
| **Eval** (admin) | ✅ Shipped (E5/E6/E7) | `13a5606` | `/eval` admin dashboard: runs, cases, regressions, case detail. Gated by `ADMIN_USER_IDS`. |

---

## Agent capabilities (current tool inventory — 15 tools)

| Tool | Returns | Notes |
|------|---------|-------|
| `get_league_summary` | high-level league info | scoring type, current week, teams |
| `get_league_rules` | full rules in plain English | waiver mechanics, FAAB, trades, playoffs |
| `get_my_roster` | user's roster | scoped to current league |
| `get_team_roster(team_or_manager)` | another team's roster | resolves by team name OR manager |
| `find_player(name)` | identity + ownership + season stats | case/diacritic insensitive |
| `get_player_projection(name, horizon)` | projected value + status + ownership | per_game OR season_total |
| `top_projected_free_agents` | ranked FA list | minutes × PPM × availability |
| `get_free_agents` | FA pool listing | broader than the top-N tool |
| `get_top_players_overall` | league-wide leaderboard | by projected value |
| `get_top_by_stat(stat)` | leaderboard by single stat | rebounds, assists, etc. |
| `compare_players([names])` | side-by-side comparison | projections + season stats |
| `get_team_strength(team_or_manager)` | per-stat contribution + rank | descriptive in points leagues |
| **`get_injury_status([names])`** | bulk status, status_full, injury_note | replaces most `search_recent_news` calls |
| **`get_player_schedule([names], days_ahead)`** | bulk schedule + B2B count | per-player games_count + back_to_back_count |
| `search_recent_news(query)` | Tavily-backed web search | fallback for genuinely-news-needed cases |

---

## Backend services + data layer

### Postgres tables (high-level)

| Table | Purpose |
|-------|---------|
| `users`, `leagues`, `teams`, `roster_players`, `free_agents` | identity + roster snapshots |
| `players` | NBA player identity + `status` / `status_full` / `injury_note` / `image_url` / `percent_owned` / `percent_started` |
| `player_stats` | Yahoo-sourced season + last_7/14/30 totals (long format) |
| `nba_game_logs` | per-player per-game box scores (populated on-demand from Yahoo's per-date stats endpoint, cached forever) |
| `nba_schedule` | NBA game schedule with tipoff_at — backfilled 2025-10-21 → 2026-04-15 from ESPN |
| `news_items` | injury / status news (Tavily + scheduled ingest) |
| `projection_cache` | per-(player, league, horizon=per_game/season_total) cached engine output |
| `projection_history` | daily snapshots for trend analytics |
| **`player_ownership_events`** | new — one row per ownership change (draft / add / drop / trade) sourced from Yahoo |
| `eval_runs`, `eval_case_results` | eval harness persistence |
| `conversations` | LangGraph AsyncPostgresSaver state |

### Sync jobs (APScheduler + on-demand)

- `sync_yahoo` — rosters / FAs / teams / standings (daily, with split-tx isolation)
- `sync_schedule` (`backfill_schedule` for past) — ESPN scoreboard, 14d lookahead daily
- `sync_stats` — Yahoo per-coverage stats (season + windows)
- `sync_news` — news ingestion
- `sync_transactions` — Yahoo draft results + post-draft transactions → `player_ownership_events`. Runs on first player-ownership endpoint call per league; idempotent.
- `freshness` — bootstraps initial sync on user OAuth completion
- `compute_analysis` (projection engine) — points / categories valuator → `projection_cache`

### Key endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET /api/team/{league_id}?date=` | Team tab (per-date roster + actuals + projection) |
| `GET /api/players/{league_id}` | Players list with filters/sort/search |
| `GET /api/players/{league_id}/{player_id}?start=&end=` | Player detail over arbitrary date range |
| `GET /api/players/{league_id}/{player_id}/ownership` | Player's ownership timeline in league |
| `GET /api/waivers/{league_id}?days_ahead=` | Pickups + drops + paired swaps |
| `GET /api/league/{league_id}` | League tab (standings + rules + settings) |
| `GET /api/trades/{league_id}` | Trade builder data (my team + partners + projections) |
| `GET /api/admin/evals/*` | Admin-only eval dashboard endpoints (gated by `ADMIN_USER_IDS`) |

---

## Operating principles (load-bearing)

1. **Process-only eval assertions.** Test BEHAVIOR (tool routing, hallucination guards, vocabulary clusters) — never specific numbers, ranks, or player names as required output. Numbers come from tools; the LLM never estimates a stat.

2. **Cases encode the complete-answer vision, not minimum routing.** Use minimal `must_call_tools` + rich `response_contains_any` clusters + `min_response_chars`. See memory: `feedback_case_authoring.md`.

3. **Cases authored ahead of capabilities.** Write for the world we want. Note gaps in the description and let cases fail until the tool ships.

4. **Claude proposes, Itamar approves.** No autonomous case edits. Every YAML diff goes through human review. See EVAL_HARNESS §13.

5. **Surgical per-change runs, full-suite on command.** When a single tool changes, run only the cases that exercise it. Full-suite is opt-in. See EVAL_HARNESS §15.

6. **Build features first, improvement loop later.** All 5 tabs + eval dashboard now shipped — improvement loop is unlocked. See memory: `feedback_build_order.md`.

7. **Read-only Yahoo today.** Write scope (`fspt-w`) deferred — see BACKLOG → Yahoo write scope.

8. **Local-only what-if affordances** — Team slot swap and Trades sums are local-only previews until the write scope lands.

---

## Yahoo API gotchas (re-learned this session)

These bit us today; baking them into memory so the next session doesn't:

1. **HTTP 999 without `User-Agent`.** Every Yahoo Fantasy request must send `User-Agent: fantasy-copilot/1.0` or Yahoo rejects with `999 Unknown` and no body. Already added to every connector call.

2. **NBA stat_id 2 = MIN, NOT 8.** Stat_id 8 is FT%. Easy to confuse because 8 looks like a "minutes-ish" small integer.

3. **`Infinity` values in JSONB-bound responses.** Yahoo emits `"Infinity"` for rate stats on 0/0 attempts (e.g. FT% when a player took zero FTs). Python's `float("Infinity")` returns `inf`, and Postgres JSONB rejects it. `_stats_to_box` filters NaN/Inf before writing.

4. **Per-date stats endpoint requires `;date=YYYY-MM-DD` as a path segment**, not a query param. `stats;type=date;date=2026-03-08` works.

5. **Transactions are not the whole ownership story.** `/league/{key}/transactions` returns only post-draft moves. Drafted-and-never-traded players have ZERO transactions. Must also pull `/league/{key}/draftresults` for initial team assignments.

6. **`movement_type: "trade"` is a real movement.** Don't filter to `{add, drop}` only — trades carry source_team_key and destination_team_key.

7. **Access tokens last 1h.** Call `get_fresh_access_token(db, user)` before any sustained fan-out (per-date stats etc.) — it refreshes if needed and rotates the refresh token.

8. **Schedule is forward-only.** `sync_schedule` runs daily and only pulls the next 14 days. For past-date opponent lookups we backfilled 2025-10-21 → 2026-04-15 once via `backfill_schedule`. The backfill is idempotent — re-runnable.

---

## Eval harness — phase status

| Phase | What | Status |
|-------|------|--------|
| E0 | Schema + loader (yaml → EvalCase) | ✅ |
| E1 | Runner + assertions + severity tiers | ✅ |
| E1.6 | Drop snapshots — process-only assertions | ✅ |
| E2 | Postgres persistence + LangSmith routing | ✅ |
| E2.1 | First broaden — 4 new cases | ✅ |
| E2.2 | `eval_stats.py` read-only CLI | ✅ |
| E2.3 | Doc rewrite — §13 / §15 / §16 + §9 phase plan | ✅ (`dd75030`) |
| E3 | `inspect_trace.py` | ✅ (`e8a3ffa`) |
| E4 | Seed-coverage case batch | ✅ — 40 cases on disk, 14 with run history |
| **E5** | Admin gate (`ADMIN_USER_IDS` + `require_admin`) | ✅ (`13a5606`) |
| **E6** | `/api/admin/evals/*` endpoints | ✅ (`13a5606`) |
| **E7** | `/eval` frontend (4 views — landing/runs/cases/case-detail) | ✅ (`13a5606`) |
| E8 | Cron + weekly digest | 🗓️ Deferred |

---

## Dev infrastructure / how to run

```
Backend:  /Users/itamarsaacks/Desktop/fantasy_copilot_v2/backend
          .venv/bin/uvicorn app.main:app --reload --port 8000
          ADMIN_USER_IDS=1 in backend/.env makes user 1 admin
Frontend: /Users/itamarsaacks/Desktop/fantasy_copilot_v2/frontend
          npm run dev  → http://localhost:3000
ngrok:    sensually-april-unclad.ngrok-free.dev → frontend (Yahoo OAuth uses this)
Postgres: localhost:5432 (Docker)
```

**Mobile / Remote Control:** see memory `remote_control_workflow.md`. TL;DR: `claude remote-control --spawn=worktree --name "Fantasy Copilot"` on the Mac, scan QR with Claude iOS app, sessions run on the Mac with per-session git worktrees.

---

## Where to look next

- `docs/BACKLOG.md` — per-tab list of pending improvements (the actual roadmap)
- `docs/EVAL_HARNESS.md` — eval harness design + operating manual
- `docs/SESSION_2026-05-17.md` — last session's full log
- `docs/decisions/0001-stack-and-architecture.md` — initial ADR
- `backend/app/agent/tools/` — all 15 agent tools
- `backend/app/api/routes/` — every HTTP endpoint
- `backend/app/services/player_history.py` — per-date stats cache (foundation for Players v2)
- `backend/app/jobs/sync_transactions.py` — draft + transactions → ownership events
- `frontend/src/components/players/` — player drawer + horizontal timeline
- `frontend/src/app/(app)/eval/` — admin dashboard pages
