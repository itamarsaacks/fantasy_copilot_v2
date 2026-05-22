# Session notes

Rolling log of what was just done + what's next + what's in flight. Update at
the END of each session via `/wrap-session`. Read at the START of each session.

Keep the **5 most recent entries**. Older entries get pruned. The git log is
the durable record of what shipped; this file is the human-readable
"where are we right now."

---

## 2026-05-22b — Phase A: backfills + APScheduler wiring

Continues 2026-05-22 (entry below). After the foundation landed on main as
`b511c5f` + the agent-date fix `34bfa4a`, this turn ran the one-shot backfills
and wired the new sync tiers into APScheduler.

**Done this turn:**

- **APScheduler wiring** in `backend/app/jobs/freshness.py` — three new tiers
  registered in `start()`, gated by `is_replay_mode()`:
    - `game_logs_nightly` — daily at ~3am ET (8am UTC approx, DST-tolerant)
    - `game_logs_live` — every 30 min; the job short-circuits on non-game days
    - `standings_sweeper` — every 5 min, drains
      `standings_cache_invalidations`
  `_next_3am_et_utc()` helper computes the next-day anchor.
- **Bug fix** in `sync_game_logs.get_active_player_set` — original SQL union
  subquery referenced a column name that didn't exist; replaced with three
  scalar queries + Python-side set union. Same result, ~600 ids at NBA scale
  so the round-trips are immaterial.
- **Bug fix** in `sync_game_logs.sync_logs_for_date` — was calling
  `fetch_and_cache_logs(db, user, player, ...)` but the helper takes
  keyword-only args. Fixed to use `get_fresh_access_token(db, user)` then
  pass `access_token=…`.
- **One-shot backfills run** (in this order):
    1. `python -m scripts.backfill_espn_player_ids` — 30 ESPN team rosters
       walked. **537 / 719 Yahoo players matched** (518 exact + 19 fuzzy);
       522 headshots queued; 182 unmatched (mostly mid-season trades —
       Yahoo's stale `nba_team_abbr` doesn't match ESPN's roster).
    2. `python -m scripts.download_headshots` — converted ESPN CDN headshots
       to WebP at 192 + 384 (~6 MB total), wrote to
       `frontend/public/headshots/`, set `players.headshot_path`.
    3. `python -m app.jobs.sync_game_logs backfill --from 2026-03-14 --to 2026-03-15`
       — populated game logs for the replay-date neighborhood.

**Verified live (replay mode):**

- `resolve_today() == 2026-03-15`
- Smoke 5/5 green, chat agent uses 1 tool, replies coherent
- Chat: "What NBA games happened today? Who won?" → 7 games with
  scores + winners
- `nba_game_logs` for 3/14 = ~500+ rows (was 0 pre-backfill)
- Both backfill scripts exit cleanly + are idempotent (re-running is a no-op)

**Known follow-ups (intentional, NOT in this commit):**

- Live-mode Yahoo fallback in `players.py:683` + `team.py:329` is still
  present — per master plan §2.3 it stays until production has a full
  season backfilled. Once that runs, delete + tighten
  `check_forbidden_sources.sh` (the `yahoo_in_routes` block → error).
- 182 unmatched ESPN ids — mostly traded players. The nightly reconcile
  retries them; manual matching is the long tail.
- The 3/14-3/15 backfill is intentionally narrow. Run
  `python -m app.jobs.sync_game_logs backfill --from 2026-03-01 --to 2026-03-15`
  to widen — it takes ~15 min and makes drawer / standings views richer.

**Next session — recommended:**

1. Open `/tab-session chat-mentions` — the first tab session. Prereqs are
   all in place (headshots downloaded, components built, agent prompt
   knows about chips).
2. Or: do the wider game-logs backfill first if you want more historical
   data in drawers / Players-tab compare views before building chat UI.

---

## 2026-05-22 — Data foundation reformation prep (master plan + Steps 1–9 + frontend primitives)

**Done this session:** Shipped on main as `b511c5f`. Subsequent commit `34bfa4a`
injects current date into agent system prompt. Original session-summary kept
below for context.

This was a planning + scaffolding session. The user requested a major reformation
of the app — 6 new tabs, Postgres-as-source-of-truth at request time, point-in-time
roster reconstruction, replay-mode-aware date chokepoint, headshots+logos
everywhere, clickable player chips in chat. The whole roadmap landed as a master
plan in `~/.claude/plans/joyful-bubbling-dream.md`. All 9 data-foundation steps
were scaffolded so per-tab sessions can focus on UX polish.

**Master plan delivered:** `~/.claude/plans/joyful-bubbling-dream.md`
  - §1 Context · §2 Data foundation (allow-list, schema, services, jobs, endpoints, agent tools)
  - §3 Shared frontend primitives · §4 Tab roadmap · §5 tab-session skill spec
  - §6 Replay-mode test plan · §7 Non-goals · §8 Risks

**Step 0 — session-workflow skill:**
- `.claude/skills/tab-session/SKILL.md` — every per-tab session reads this first

**Step 1 — `resolve_today()` chokepoint:**
- `backend/app/services/clock.py` (new) — `resolve_today()` + `is_replay_mode()`
- `scripts/check_forbidden_sources.sh` (new) — CI guard: no `date.today()`, no
  `stats.nba.com`, no `basketball-reference.com`
- 6 call sites migrated (schedule.py, team.py ×2, players.py, waivers.py,
  sync_schedule.py, sync_stats.py, player_history.py)
- Verified: `resolve_today()` returns `2026-03-15` in replay mode ✓

**Step 2 — Player ID backfill + headshot pipeline:**
- `Player.espn_player_id` + `espn_player_id_confidence` + `headshot_path` added to model
- `alembic/versions/e5f6a7b8c9d0_espn_player_id_and_headshot_path.py` (new)
- `backend/scripts/backfill_espn_player_ids.py` (new) — walks 30 ESPN team rosters
- `backend/scripts/download_headshots.py` (new) — WebP conversion to
  `frontend/public/headshots/`. Requires Pillow.

**Step 3 — `sync_game_logs` job + invalidations:**
- `backend/app/jobs/sync_game_logs.py` (new) — tiered (live 30-min during NBA
  evenings, nightly 3am ET, backfill CLI). Reuses `player_history.fetch_and_cache_logs`.
- Active-player set computed via union of rostered + transacted + FA
- Marks projections stale via `invalidate_for_players` after each batch
- Enqueues `StandingsCacheInvalidation` rows

**Step 4 — `roster_at()`:**
- `backend/app/services/roster_history.py` (new) — replays draft +
  `PlayerOwnershipEvent` rows to reconstruct any team's roster on any date.
  Falls back to live `RosterPlayer` when no events exist for a team.

**Step 5 — Postgres-only read paths:**
- `backend/app/services/game_logs.py` (new) — `get_logs_for_player`,
  `get_logs_for_players_on_date`. Both read `nba_game_logs` only.
- `players.py:683` and `team.py:329` rewritten to prefer DB, fall back to Yahoo
  ONLY in live mode + only when DB is empty for that date. Replay mode = strict.
- After production backfill runs, the fallback gets deleted (see CI guard).

**Step 6 — Projection invalidation + per-date projections:**
- `backend/app/services/projection_invalidation.py` (new) — `invalidate_for_player(s)`
- `backend/app/services/projection_window.py` (new) — `project_fps_on_date`,
  `project_fps_for_window`. Formula: `per_game × games_on_date` (no new math).

**Step 7 — Standings cache + sweeper:**
- `StandingsDailyCache`, `StandingsCacheInvalidation`, `BackfillCursor` models added
- `alembic/versions/f6a7b8c9d0e1_data_foundation_tables.py` (new) — also adds
  `nba_game_logs.did_not_play` + `source` columns
- `backend/app/services/standings.py` (new) — `standings_at(league_id, date)` +
  `sweep_standings_invalidations()` (drain every 5 min via APScheduler — needs
  wiring in `freshness.py` in a follow-up).

**Step 8 — New endpoints:**
- `backend/app/api/routes/games.py` (new) — `/api/games`, `/api/games/{id}/box`
- `backend/app/api/routes/foundation.py` (new) — `/api/standings`,
  `/api/teams/{team_id}/roster`, `/api/waiver-planner/candidates`,
  `/api/team/simulate`
- Both routers registered in `backend/app/main.py`

**Step 9 — Six new agent tools:**
- `backend/app/agent/tools/date_aware.py` (new) — `get_games_on_date`,
  `get_standings_on_date`, `get_team_roster_on_date`, `get_player_box_on_date`,
  `simulate_lineup`, `find_fas_playing_on_dates`
- Registered in `ALL_TOOLS` (now 21 tools)
- Prompt-level rule added: agent doesn't use `write_file`/`edit_file`/`execute`
  (deepagents doesn't expose a toggle; prompt constraint is the v1 mitigation)

**Frontend primitives (master plan §3):**
- `frontend/src/lib/date-utils.ts` (new) — consolidated date helpers
- `frontend/src/lib/render-with-mentions.tsx` (new) — chat-reply chip post-processor
- `frontend/src/components/shared/team-logo.tsx`
- `frontend/src/components/shared/player-avatar.tsx`
- `frontend/src/components/shared/player-chip.tsx`
- `frontend/src/components/shared/date-toggle.tsx`
- `frontend/src/components/shared/calendar-multi-picker.tsx`
- `frontend/src/components/shared/nested-tabs.tsx`
- `frontend/src/lib/hooks/use-active-league.ts` — REWRITTEN as module-level
  store (preserves localStorage + chat-reset null-transition guard). Mirrors
  pattern in `use-chat-state.ts`. Should eliminate the latent race in every
  other consumer.
- `frontend/public/nba-logos/` + `frontend/public/headshots/` (empty dirs)

**Tab plan stubs landed in `docs/plans/`:**
chat-mentions, players, games, my-team, league, trades-waiver. Each has
Context, Prereqs, Phases, Verification, Out-of-scope sections so the per-tab
session opens cleanly.

**Branch state:** Everything sits uncommitted on `feature/data-foundation`.
No migrations have been run (Docker daemon was off during the session).
No smoke test was run for the same reason.

**Next session should:**

1. Start Docker + Postgres: `docker compose up -d`
2. Start backend: `cd backend && uvicorn app.main:app --reload --port 8000`
3. Run migrations: `cd backend && alembic upgrade head` — confirms the two
   new migrations (`e5f6a7b8c9d0`, `f6a7b8c9d0e1`) apply clean
4. Run forbidden-sources CI guard: `bash scripts/check_forbidden_sources.sh`
5. Run smoke test: `bash scripts/smoke.sh`
6. **Decide commit strategy:** all of this as one foundation commit, or
   per-step commits? My recommendation: one commit "Data foundation
   reformation Steps 1–9 + shared primitives" so the master plan is
   land-or-revert atomic. The diff is large but the changes are coherent.
7. Backfill steps (long-running, one-shot):
   - `cd backend && python -m scripts.backfill_espn_player_ids`
   - `cd backend && python -m scripts.download_headshots` (needs Pillow installed)
   - `cd backend && python -m app.jobs.sync_game_logs backfill --from 2026-03-01 --to 2026-03-15`
8. Then open `/tab-session chat-mentions` to start the first per-tab session.

**In flight / known gaps:**
- `freshness.py` doesn't yet schedule the new `sync_game_logs` tiers or the
  standings sweeper — wire them in a follow-up. (The job is invokable via
  CLI today, just not auto-scheduled.)
- NBA team logo SVGs in `frontend/public/nba-logos/` are not committed
  (TeamLogo falls back to colored monogram). Source: Wikimedia Commons; the
  per-tab sessions can add them as needed.
- Headshots are not pre-downloaded (PlayerAvatar falls back to initials).
- `useActiveLeague` rewrite is in place but the existing consumers
  (Conversation, etc.) should be smoke-tested for the chat-reset bug since
  the underlying `checkLeagueChanged` guard now sits on top of a different
  state shape.
- Live-mode Yahoo fallback in `players.py` and `team.py` is intentional
  for transition. Remove + tighten CI guard once production backfill runs.

---

## 2026-05-17 → 2026-05-18 — Five product tabs + eval dashboard + Players v2 detail experience all shipped

**Done this session:** (full log in `docs/SESSION_2026-05-17.md`, 18 commits, HEAD `07a4e5d`)

Product tabs — every one of them shipped v1 in this session:
- **Team tab** (`8eface1`, `68f2d1f`) — per-date roster, projection / actual fps from Yahoo, what-if slot swap
- **Players tab v1 then v2** (`d50a614` → `07a4e5d`) — searchable list → click-row drawer with arbitrary date-range stats + projection + game log + news + ownership timeline + multi-player compare
- **Waivers tab** (`0bc950c`, `3a6892f`) — pickup recommendations + drop candidates + paired-swap cards over a window selector
- **League tab** (`6dddd27`) — standings + scoring rules + settings
- **Trades tab** (`32b7cfa`) — dual-roster trade builder with fps delta + verdict

Eval dashboard (E5/E6/E7) all shipped in `13a5606`:
- `ADMIN_USER_IDS=1` env + `require_admin` dep
- `/api/admin/evals/*` endpoints (summary, runs, runs/{id}, cases, cases/{id}, regressions)
- `/eval` frontend (4 routes — landing, run detail, case library, case detail)
- Sidebar shows "Admin → Eval" only when `is_admin=true`

Players v2 deep dive (5 passes after first user feedback) — fixed data correctness AND UX:
- Pass 1 `71170e3`: Draft results sync — drafted-and-never-traded players now show from draft day. Yahoo's `/transactions` is post-draft only; needed `/draftresults` too.
- Pass 2 `2d29075`: ESPN schedule backfill (1243 games / 177 days, 2025-10-21 → 2026-04-15). Re-linked 243 stale game logs. OPP column now populates.
- Pass 3 `f227910`: Horizontal `HorizontalOwnershipTimeline` with per-team color palette, today marker, click-to-set-range.
- Pass 4+5 `07a4e5d`: Hover-revealed "+ Compare" button per row, prefetch-on-hover (drawer ~50ms instead of ~1.7s cold).

Infrastructure:
- `unaccent` extension migration (`c3d4e5f6a7b8`) — diacritic-insensitive name search
- `player_ownership_events` table + migration (`d4e5f6a7b8c9`)
- New service `app/services/player_history.py` — Yahoo per-date stats cache → `nba_game_logs`, with off-day placeholder rows for zero-round-trip subsequent loads
- New sync `app/jobs/sync_transactions.py` — draft + transactions → ownership events
- New `backfill_schedule()` in `app/jobs/sync_schedule.py` for past-season schedule
- `User-Agent: fantasy-copilot/1.0` added to every Yahoo connector call (Yahoo returns HTTP 999 without it)

Docs:
- Rewrote `docs/PROJECT_STATE.md` (was stale from 5/12)
- Rewrote `docs/BACKLOG.md` per-tab convention (most "not built" items now shipped — remaining items are polish + Stage 2 stuff)
- New memory: `yahoo_gotchas.md` (User-Agent, stat IDs, Infinity in JSONB, draft+transactions both needed, refresh tokens, concurrency caps)
- New memory: `remote_control_workflow.md` (iPhone setup)
- Updated `MEMORY.md` index

Mobile workflow:
- Itamar set up Claude Code Remote Control on his iPhone. Daily-start command:
  ```bash
  cd /Users/itamarsaacks/Desktop/fantasy_copilot_v2
  claude remote-control --spawn=worktree --name "Fantasy Copilot"
  ```
  See memory `remote_control_workflow.md` for full setup + the `unset ANTHROPIC_API_KEY` requirement.

**Next session should consider (priority order):**

1. **Polish the new tabs based on user feedback** — Itamar will give a list of tweaks per tab. The biggest known items: per-segment stats card on Players timeline (clicking a segment surfaces inline summary), season-overall vs period toggle on Stats tab, Team tab "other things i want to fix" that weren't enumerated yet.
2. **Background nightly game-log backfill** — biggest remaining perf win for the Players drawer (`docs/BACKLOG.md` → Global section).
3. **Eval improvement loop** — the build-everything-first gate is lifted. Two known borderline misses from 5/12 (`injury_screen_fa_list`, `start_sit_tonight`) plus a full-suite refresh would surface real regressions before the season starts.
4. **Team tab Stage 2** — opponent defensive ratings to replace the ±3% home factor with real opp-strength data.

**In flight / uncommitted at session end:**
- This wrap commit (SESSION_NOTES + PROJECT_STATE + BACKLOG + SESSION_2026-05-17 + memory updates).
- Finder-duplicate noise in repo root: `frontend/*  2.*` files. Untracked, ignored, but should be cleaned up. `git clean -fd` from the v2 path will wipe them; verify nothing important first.
- Smoke test NOT run for these doc-only changes.

**Env state at session end:**
- Postgres: running (Docker)
- Backend uvicorn: running on :8000
- Frontend npm dev: running on :3000
- ngrok: running, tunnel `sensually-april-unclad.ngrok-free.dev` → frontend
- Claude Code Remote Control: configured. Requires `unset ANTHROPIC_API_KEY` in any shell that wants to launch a Remote Control session, because Yahoo OAuth → claude.ai is required (API key auth is rejected).

**Open questions / parked decisions:**
- Whether the Trade tab's "+ Compare" parallel needs a similar button — deferred to user feedback.
- Per-team color palette is hash-based (`team_id % 12`); for a 12-team league this never collides but a >12-team league would. Acceptable for now.
- 83-pt Bam Adebayo game on 2026-03-10 in the cached data looks like a Yahoo data glitch (high FTA count, unrealistic). We pass it through; not our problem.
- The 5-min `staleTime` on ownership timeline is a guess. Adjust if it feels stale during use.

**User mood at session end:**
Tired but satisfied. We went from "Team-tab tweaks tomorrow" at the start to ~18 commits ending with all five tabs + eval dashboard live and a working iPhone Remote Control. He's set up to start the next session from anywhere.

---

## 2026-05-10 — Eval harness design + foundation scaffolded

**Done this session:**
- Decided to build an eval harness next, before any new feature work — rationale: every phase shipped without it requires manual re-testing, and the season starts in October. Eval-first means October features ship on a tested foundation.
- Wrote `docs/EVAL_HARNESS.md` — full design + operating manual (12 sections originally, +1 added later)
- Read user-provided Medium article on intent detection. Concluded: classifier-in-front-of-LLM approach doesn't fit our tool-calling architecture, but stole 3 useful ideas — structured intent taxonomy, explicit clarification-needed cases, per-intent metric slicing. Folded into the doc.
- Designed and added §13 (Automated case generation) — hybrid model: generated cases (deterministic GT, ~70% of surface) + promoted cases (opinionated GT, real-chat origin). Generator restricted to questions answerable from snapshot DB. Self-reference mitigation: Opus generates, Sonnet runs.
- Decided weekly digest is the monitoring floor (~5 min/week, not zero). Auto-written to `app/evals/digests/`.
- Added `langsmith_trace_id`, `langsmith_thread_id`, `agent_thread_id` to result schema (§7).
- Scaffolded `backend/app/evals/` — schema.py (Pydantic, single source of truth for case shape), loader.py, README.md, dir tree (cases/{manual,promoted,generated}, snapshots, probes, runner, digests).
- Wrote first manual case: `cases/manual/waiver_days_offseason.yaml` with 4 phrasings. Validates clean through the loader. Negative tests (clarif intent without clarif assertion, both message fields set) reject as expected.
- Updated `.claude/CLAUDE.md` — added pointer to `docs/EVAL_HARNESS.md` and a new "Eval harness" section recapping current status + hybrid model + self-reference mitigation + monitoring floor + phase progress (E0 ✅).

**Next session should consider (priority order):**
1. **Phase E1 — runner + first snapshot.** Snapshot capture script (dump Postgres tables + record Yahoo responses for one league at frozen `AS_OF_DATE`). Runner skeleton that loads a snapshot, instantiates the agent, runs each phrasing, evaluates assertions, prints pass/fail to console. Capture `offseason_2026_05` snapshot. Requires Docker + backend running.
2. Phase E2 — Postgres `eval_runs` + `eval_case_results` tables, persistence, LangSmith trace/thread ID capture
3. Phase E3 — promoter (LangSmith trace → case YAML, interactive)
4. Phase E3.5 — `eval-author` skill + first probe (`league_rules`) + first 30 generated cases. **This is the unlock — after this, no more manual case authoring for factual topics.**

**In flight / uncommitted:**
- `.claude/CLAUDE.md` — modified (eval harness section added)
- `docs/EVAL_HARNESS.md` — new file (~750 lines, the design doc)
- `backend/app/evals/` — new directory tree with schema.py, loader.py, README.md, one starter case YAML
- All safe to leave overnight. Suggest committing tomorrow morning before starting Phase E1, as one commit titled "Phase E0: eval harness foundation — design doc + schema + loader."
- No smoke test run because no app code changed. Schema is validated locally via Python import.

**Env state:**
- Postgres: stopped (Docker down)
- Backend uvicorn: stopped
- Frontend: stopped
- ngrok: stopped
- Nothing weird with credentials or rotated secrets

**Open questions / parked decisions:**
- Whether snapshot capture should record Tavily news responses too, or stub web search out entirely during eval runs. Current plan in §4 says record them; might revisit when building.
- Who triggers the daily/weekly cron run? Local cron, GitHub Action, or part of the backend's APScheduler? Defer until E2.
- Whether to also generate cases for cross-league behavior (e.g. user has 2 leagues) — currently snapshots are per-league. Defer until we have a 2nd snapshot.

**User mood at session end:**
- Engaged, thinking ahead about long-term test strategy. Pushed back on "build it manually" idea and asked for an automated `eval-author` skill — wants the harness to scale without their attention. Receptive to honest tradeoff explanations (deterministic GT only, weekly digest as monitoring floor). Stopping for the night, will continue tomorrow.

---

## 2026-05-09 — Phase 8 frontend complete + memory + continuity scaffolding

**Done this session:**
- `0800631` Phase 8 part 1 — Next.js scaffold, Tailwind v4 + shadcn/ui, sidebar shell, chat tab with Playfair/Inter/JetBrains Mono, working chat against the agent
- `352a1f2` Phase 8.1 — real Yahoo OAuth from the frontend (ngrok tunnels port 3000 not 8000, Next.js proxies `/auth/*` `/api/*` `/admin/*` `/health` to backend), `/login` page, Base UI bug fixes (nested buttons, asChild, dropdown group), `/api/chat` rename to dodge frontend page collision
- `2877235` Phase 8.6 — LangGraph PostgresSaver memory, conversations table, 4 new analyst tools (top_players_overall, top_by_stat, compare_players, team_strength), recent-chats sidebar, "+" new-chat button, prompt nudges
- `07f0126` Continuity scaffolding — SESSION_NOTES.md, /start-session and /wrap-session skills, "How we work" + "User context" sections in CLAUDE.md

**Next session should consider:**
- The user wants to break the chat in real conversations and send a list of failures. Treat that list as the spec for the next round of agent improvements.
- Phase 9 candidates (pick ONE — don't bundle): NBA per-game logs sync (unlocks date-range queries + recent-form trends), Yahoo transactions sync (unlocks ownership timeline + "while I owned him" stats), trade analyzer/suggester (needs projections + roster simulation; partly built), background news ingestion sub-agent.
- Frontend Phase 8 part 2/3: Team page with roster grid, Players search, League standings, Trades, Waivers. Currently they're placeholder pages.

**In flight / uncommitted:**
- Nothing. Tree is clean, all four commits pushed to main.

**Env state:**
- Postgres: stopped (Docker Desktop quit by user)
- Backend uvicorn: stopped
- Frontend: still running on :3000 (PID 38975) — harmless, will idle
- ngrok: stopped
- Yahoo dev app redirect URI: still `https://sensually-april-unclad.ngrok-free.dev/auth/yahoo/callback` — when user restarts ngrok, it'll likely give a different URL on the free tier and they'll need to update Yahoo + `backend/.env`

**Open questions / parked decisions:**
- Whether new sessions actually feel better with the continuity scaffolding — pending the user testing it tomorrow.
- Whether to migrate ngrok free → Cloudflare Tunnel (free + fixed URL) before pushing more frontend work that requires repeated OAuth.
- Sub-agent split (waiver_analyst, trade_evaluator) — deferred until the main agent's tool list clearly clusters by domain.
- Eval suite for the agent — discussed conceptually, not built. Worth building once we have ~3 user-reported failures to encode as regression tests.

**User mood at session end:**
- Asked for the continuity tools because new sessions had been frustrating. Tone was "fix this before we keep going." Wants to test fresh-session behavior tomorrow morning. Ready to stop tonight.

---

<!-- New entries go ABOVE this line. Old entries below get pruned when there are >5. -->
