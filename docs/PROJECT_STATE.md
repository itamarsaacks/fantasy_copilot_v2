# Fantasy Copilot v2 — Project state

> Single source of truth for "where are we, what's shipped, what's planned,
> what's missing." Updated whenever scope shifts. Read this before authoring
> eval cases, planning UI work, or scoping new features.

_Last updated: 2026-05-12_

---

## App shape (tabs)

| Tab | Status | What it does |
|-----|--------|--------------|
| **Chat** | ✅ Shipped | Conversation UI, agent w/ 13 tools, AsyncPostgresSaver persistence |
| **Team** | ⏳ Placeholder (Phase 8 part 2) | Roster grid by position, projections per player, what-if swap simulator |
| **League** | ⏳ Placeholder (Phase 8 part 3) | Standings table, rules, click any team → see their roster |
| **Players** | ⏳ Placeholder (Phase 8 part 3) | Search any NBA player → season stats, projection, ownership, recent news |
| **Waivers** | ⏳ Placeholder (Phase 8 part 3) | Roster-aware FA recs, paired with drop suggestions |
| **Trades** | ⏳ Placeholder (Phase 9) | Trade analyzer (any combination) + trade suggester (realistic offers to one partner) |

**Implication for evals:** the agent answers tab-flavored questions via chat *today* — "what's my roster" works because of `get_my_roster`, even though the Team tab is a placeholder. Cases can test agent behavior independent of tab UI.

---

## Agent capabilities (current tool inventory)

13 tools wired into the LangGraph agent:

| Tool | Returns | Notes |
|------|---------|-------|
| `get_league_summary` | high-level league info | scoring type, current week, teams |
| `get_league_rules` | full rules in plain English | waiver mechanics, FAAB, trades, playoffs |
| `get_my_roster` | user's roster | scoped to current league |
| `get_team_roster(team_or_manager)` | another team's roster | resolves by team name OR manager |
| `find_player(name)` | identity + ownership + season stats | case/diacritic insensitive |
| `get_player_projection(name, horizon)` | projected value + status + ownership | horizon = per_game OR season_total |
| `top_projected_free_agents` | ranked FA list | minutes × PPM × availability |
| `get_free_agents` | FA pool listing | broader than the top-N tool |
| `get_top_players_overall` | league-wide leaderboard | by projected value |
| `get_top_by_stat(stat)` | leaderboard by single stat | rebounds, assists, etc. |
| `compare_players([names])` | side-by-side comparison | projections + season stats |
| `get_team_strength(team_or_manager)` | per-stat contribution + rank | descriptive in points leagues |
| `search_recent_news(query)` | Tavily-backed web search | for STATUS info only — never stats |

---

## Known capability gaps (planned, not yet built)

These come up repeatedly in case authoring. Eval cases should be written for the **post-fix world** when the gap is short-term planned. For long-term gaps, note them in the case description.

| Gap | Tracked in | What it blocks |
|-----|-----------|----------------|
| **Weekly schedule tool** | BACKLOG #3 | "games this week", "B2B load", "matchup difficulty" — the single most useful piece of context for lineup decisions |
| **Injury status table** (daily-synced) | BACKLOG #1 | Currently every FA / start-sit question fires `search_recent_news` for status. A daily injury sync would let the agent query a fast table instead. ~$0.30 saved per FA chat. |
| **User feedback buttons** (👍/👎 on chat) | BACKLOG #2 | Captures bad/good signal from friends post-launch. Feeds the §15 triage loop in EVAL_HARNESS. |
| **Admin gate for /eval dashboard** | EVAL_HARNESS §16, Phase E5 | Required before sharing the app with friends. `ADMIN_EMAILS` env + `require_admin` dep. |
| **Eval dashboard frontend** | EVAL_HARNESS §16, Phase E7 | `/eval` Next.js route, admin-only, surfaces health + slices + case library + trigger button |

---

## Phase status (eval harness work)

| Phase | What | Status |
|-------|------|--------|
| E0 | Schema + loader (yaml → EvalCase) | ✅ Done |
| E1 | Runner + assertions + severity tiers | ✅ Done |
| E1.6 | Drop snapshots — process-only assertions | ✅ Done |
| E2 | Postgres persistence + LangSmith routing | ✅ Done |
| E2.1 | First broaden — 4 new cases | ✅ Done |
| E2.2 | `eval_stats.py` read-only CLI | ✅ Done |
| E2.3 | Doc rewrite — §13 / §15 / §16 + §9 phase plan | ✅ Done (commit `dd75030`) |
| E3 | `inspect_trace.py` — read LangSmith trace from CLI | ✅ Done (commit `e8a3ffa`) |
| E4 | **Seed-coverage case batch (~50–80 cases)** | 🚧 In progress — 5 new cases drafted, more coming |
| E5 | Admin gate via `ADMIN_EMAILS` env + `require_admin` | ⏳ Next |
| E6 | Dashboard backend — `/api/admin/evals/*` | ⏳ |
| E7 | Dashboard frontend — `/eval` route, 6 views | ⏳ |
| E8 | Cron + weekly digest | 🗓️ Deferred |

---

## Operating principles (load-bearing)

1. **Process-only eval assertions.** Test BEHAVIOR (tool routing, hallucination guards, vocabulary clusters) — never specific numbers, ranks, or player names as required output. Numbers come from tools; the LLM never estimates a stat.

2. **Cases encode the complete-answer vision, not minimum routing.** "Project Embiid this week" should test that the answer covers projection + availability + ownership context — via `must_call_tools` for the essential tool, plus rich `response_contains_any` vocabulary clusters, plus `min_response_chars` for depth.

3. **Cases authored ahead of capabilities.** Write the case for the world we want. When a tool is missing (schedule, injury table), note it in the description and let the case fail until the tool ships. The case is a *contract*, not a *test of today*.

4. **Claude proposes, Itamar approves.** No autonomous case edits. Every YAML diff goes through human review. See EVAL_HARNESS §13.

5. **Surgical per-change runs, full-suite on command.** When a single tool changes, run only the cases that exercise it. Full-suite is opt-in (cron + on-demand from dashboard). See EVAL_HARNESS §15.

---

## Where to look next

- `docs/EVAL_HARNESS.md` — design + operating manual for the eval harness (16 sections)
- `docs/BACKLOG.md` — prioritized backlog of capability gaps + post-launch features
- `docs/decisions/0001-stack-and-architecture.md` — initial ADR
- `backend/app/agent/tools/` — all 13 agent tools
- `backend/app/evals/cases/manual/` — eval case YAMLs (one per intent)
- `scripts/run_evals.py` — eval runner entrypoint
- `scripts/eval_stats.py` — read-only stats CLI
- `scripts/inspect_trace.py` — pretty-print a LangSmith trace (E3)
