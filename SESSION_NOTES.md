# Session notes

Rolling log of what was just done + what's next + what's in flight. Update at
the END of each session via `/wrap-session`. Read at the START of each session.

Keep the **5 most recent entries**. Older entries get pruned. The git log is
the durable record of what shipped; this file is the human-readable
"where are we right now."

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
