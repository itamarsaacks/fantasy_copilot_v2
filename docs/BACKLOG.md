# Backlog

> Things we want to do but haven't yet. Captured here so they survive across
> sessions instead of living in chat scrollback.
>
> Ordered by priority (top = next). Each item has: problem, sketch, what
> success looks like, and which session surfaced it.

---

## 1. Injury status pipeline (priority: HIGH)

**Surfaced:** Phase E2 full-suite eval run on 2026-05-12. The harness caught
the agent firing `search_recent_news` 3 times for a single "best free agents"
question — slow, expensive (~$0.10 per news call), and non-deterministic.

**Problem:** Agent over-relies on web search for injury context that should
already be in the DB. Every FA recommendation, every start/sit question, the
agent reaches for Tavily instead of querying structured data we could just
sync once per day.

**Product behavior we want:**

1. For FA recommendations: suggest **healthy players first**; flag
   injured-but-valuable as secondary signal; scan news **only** if the user
   asks explicitly or our DB row is stale (>24h)
2. For "is X playing tonight": query the injury table directly
3. For "any news on X": this is the case where web search IS appropriate

**Sketch:**

```
injury_status (new table)
├── player_id        FK to players
├── status           "active" | "questionable" | "gtd" | "out" | "ir" | "dtd"
├── reason           "left knee", "personal", "load management"
├── projected_return DATE | NULL ("week-to-week" can be NULL with notes)
├── notes            free text
├── source           "rotowire" | "yahoo" | "espn" — provenance
├── source_url       link to the original news item
├── updated_at       when our sync wrote this row
└── confidence       "official" | "reported" | "rumor"
```

- **Daily sync job** in `app/jobs/sync_injuries.py` (APScheduler, ~6am ET).
  Provider candidates: RotoWire, FantasyData, Sportradar. Pricing TBD.
- **New agent tool** `get_injury_status(player_ids)` — returns status +
  projected_return + reason for each requested player.
- **Prompt update**: stronger preference for `get_injury_status` over
  `search_recent_news`. News becomes a fallback for stale/unknown rows or
  when user explicitly asks for news.
- **Mark stale data**: rows with `updated_at` > 36h ago surface as
  "potentially stale" so the agent knows when to fall back to news.

**Cost win:** if a typical FA chat triggers 3 news searches today, and we
replace them with table queries, we save ~$0.30 per FA chat. At any scale of
real usage, that's real money.

**Eval cases to add once this lands:**

- "who are the best free agents" → `must_call_tools=[top_projected_free_agents, get_injury_status]`, `must_not_call_tools=[search_recent_news]`, and a vocab check that the agent surfaces at least one **healthy** option in the recommendation
- "is X playing tonight" → `must_call_tools=[get_injury_status]`
- "any news on X's injury" → `must_call_tools=[search_recent_news]` (the explicit news-wanted case)
- Vocab: response should mention healthy/injured/availability/return language

**Estimated effort:** 1 session for sync job + table + tool; ½ session for
prompt + cases. Pick + price the provider beforehand.

---

<!-- Add new items above this line. Move completed items to a "Done" section
or delete them once the corresponding work is committed. -->
