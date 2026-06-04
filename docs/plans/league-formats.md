# League Formats — full Yahoo-format support + per-league UX

> Tab session: `feature/league-formats`. Goal: app behaves correctly and
> *feels right* for every Yahoo Fantasy Basketball league type (5 scoring
> formats × per-league setting variations), not just the default
> "Season Points" league Itamar plays.

---

## 1. Yahoo formats — full matrix

| Yahoo `scoring_type` | Friendly name      | Math                              | Standings unit         | Status in app |
|----------------------|--------------------|-----------------------------------|------------------------|---------------|
| `point`              | Season Points      | Σ per-stat × modifier             | Total FPS              | ✅ supported  |
| `seasonpoint`        | Season Points (private) | same as `point`              | Total FPS              | ✅ now aliased to points (this session) |
| `headpoint`          | H2H Points         | Σ FPS per matchup week            | W / L                  | ✅ supported  |
| `head`               | H2H Categories     | 9 cats W/L per matchup            | Cat-wins record        | ⚠️ engine ok, **UX missing** |
| `headone`            | H2H One Win        | majority of 9 cats → 1 W          | Single W / L           | ✅ now aliased to categories (this session) |
| `roto`               | Rotisserie         | rank-sum across 9 cats, season    | Sum of cat ranks       | ⚠️ engine ok, **UX missing** |

Shipped this session (quick wins):

- `backend/app/engine/projection.py` — `POINTS_LEAGUE_TYPES` now includes
  `seasonpoint`; `CATEGORY_LEAGUE_TYPES` now includes `headone`; unknown
  types auto-detect (stat_categories → cat valuator; stat_modifiers →
  points valuator) instead of erroring.
- `backend/app/agent/prompts.py` — added `SCORING_TYPE_NOTES` entries for
  `headone` (one-win majority strategy) and `seasonpoint` (same as point).
- `frontend/src/components/league/league-view.tsx` — `scoringTypeLabel()`
  covers all 6 keys; new `isCategoryLeague()` helper; MetaCard now shows
  FAAB-vs-priority pill, trade-deadline pill (red/closed, amber/<7d, ok),
  and max-games-per-player pill.

---

## 2. Settings that vary per league (any format)

Already persisted in `LeagueSettings` (see `frontend/src/lib/api-types.ts`):

- `max_teams`, `uses_faab`, `waiver_type`, `waiver_days`, `waiver_rule`,
  `waiver_time`, `uses_playoff`, `trade_end_date`, `max_games_played`,
  `is_highscore`.

**Stored in `League.settings_json` (JSONB) but not yet typed/surfaced:**

- `roster_positions` — slot composition (PG/SG/G/SF/PF/F/C/UTIL/BN/IL counts)
- `playoff_start_week`, `num_playoff_teams`, `num_playoff_consolation_teams`,
  `playoff_seeding_type`, `uses_playoff_reseeding`
- `max_weekly_adds` (acquisition cap)
- `uses_keeper` + keeper count + keeper deadlines
- `ir_count` (separate from bench)
- `trade_review_type` (`commish` / `votes` / `yahoo` / `none`)
- `trade_reject_time`, `trade_ratify_type`

These should be added as typed fields on the `LeagueSettings` API model and
read off `settings_json` during league sync. Migration-free; sync-script
change only.

---

## 3. UX changes per league type

### 3.1 Category leagues (`head`, `headone`, `roto`) — the big gap

The app currently shows ONE projected number per player (a "composite category
score"). For real category-league users this is almost useless — they need to
see *which* categories a player wins.

**League tab — Standings:**
- For `head` / `headone`: add per-category W/L columns (PTS / REB / AST / ST /
  BLK / 3PTM / TO / FG% / FT%). The matchup view (week summary) shows the
  team's wins per cat.
- For `roto`: standings table shows rank in each category + total roto
  points (e.g. "PTS rank 3, REB rank 7, … total 78").
- Standings sort defaults to record / roto points, not FPS.

**My Team tab — Roster bucket:**
- Per-player row shows per-cat per-game projections instead of FPS
  (small sparkline-style table or a horizontal cat-strength bar).
- Below the roster, a "Team category strengths" panel: bar per cat
  showing where this team is in the league (which is the only metric
  that matters in roto/cat).
- Simulator returns per-cat delta, not just FPS delta.

**Players tab:**
- Sort/filter by individual category (z-score per cat).
- Compare view: cat-by-cat radar / side-by-side, not just FPS.
- Leaders: per-cat leaderboards.

**Waiver Planner / Pickups:**
- Ranking is "biggest improvement to YOUR team's weakest cats", not
  just window FPS. Needs the agent's strength-analysis logic on the
  team's current cat profile.
- Pickup row shows the cats this player would *move* on your team
  (e.g. "+0.3 in BLK, +0.1 in FT%, -0.2 in TO").

**Trades:**
- Trade delta is per-cat, not single FPS number. Show "cats you'd win"
  vs "cats you'd lose" after the swap.
- For `headone`: emphasize 5+ majority. For `head`: balance. For
  `roto`: closeness to next/prior team in each cat.

**Backend prerequisites:**
- Real per-cat z-scores in `_CategoryValuator` (currently MVP composite,
  noted at `projection.py:21`). Replace composite with per-cat
  contribution: `(player_value - cat_mean) / cat_stdev` summed
  (with TO sign-flipped — already in `INVERSE_STATS`).
- API responses include per-cat components everywhere (already done in
  `get_player_projection`'s `components`, but team/waiver-planner/trade
  endpoints need to surface them too).

### 3.2 Points leagues (`point`, `seasonpoint`, `headpoint`) — already mostly right

- Keep FPS-only standings & projections.
- `headpoint` weekly view: emphasize **games this week** + per-game FPS
  (already in `get_player_schedule`).
- `seasonpoint` / `point`: show cumulative FPS vs league pace.
- `is_highscore` setting: emphasize that THE HIGHEST single-week
  score also matters (some private points leagues award a bonus).

### 3.3 Universal per-league knobs (every format)

These already exist in data but aren't fully surfaced:

1. **Trade deadline** — ✅ pill in MetaCard this session. Next: disable
   "Propose Trade" UI in `trades-view.tsx` when past deadline, with a
   tooltip explaining why.
2. **Max games played / season** — show progress bar per player on the
   My Team tab ("48 / 82 games used") so the user can plan IR / streaming.
   Critical for category leagues where over-streaming wastes the cap.
3. **Max weekly adds** — surface remaining count somewhere on Trades+Waivers.
4. **Waiver day / time** — surface "next process: Wed 7am ET" on Pickups.
5. **FAAB balance** — show remaining $ next to each user; trade builder
   can include FAAB in the offer (Yahoo allows this).
6. **Playoff context** — when `current_week >= playoff_start_week - 2`,
   add a "Playoff push" banner. When inside playoffs, the simulator and
   waiver planner should default to the current matchup's date range.
7. **Roster slot composition** — render the actual slots (e.g. some
   leagues have 2 UTIL, some have G+F instead of separate PG/SG); the
   My Team grouping is hard-coded today.
8. **Keeper leagues** — entirely unsupported. Future tab session.

---

## 4. Order of operations (next session)

1. Type the missing `LeagueSettings` fields (`roster_positions`,
   `playoff_start_week`, `max_weekly_adds`, `ir_count`, `trade_review_type`,
   keeper fields). Sync change only — no migration.
2. Backend: per-cat z-score valuator in `projection.py`. Add a
   `category_components: dict[cat, float]` to projection_cache rows used
   by category leagues. Recompute via `/admin/compute-projections`.
3. Backend: propagate `category_components` through team / players /
   waiver-planner / trade endpoints.
4. Frontend: `isCategoryLeague(scoring_type)` switches:
   - League tab: per-cat columns in standings.
   - My Team tab: cat-strength panel + per-row cat bars.
   - Players tab: per-cat sort + radar compare.
   - Waiver Planner: rank by team-cat-need delta.
   - Trades: per-cat delta panel.
5. Universal pills already shipped (trade deadline, FAAB/priority, max
   games). Add: max weekly adds, playoff-push banner, dynamic roster
   slot composition.
6. Eval cases: add 6 new ones — one per scoring type — to prove the agent
   gives format-correct advice.

---

## 5. Acceptance — how we know it worked

- Set up a synthetic test league of each type (or use replay-mode private
  category league if available) and verify:
  - Standings render the right columns.
  - "Should I trade A for B?" gives a category-aware answer in cat
    leagues, a FPS answer in points leagues, and a one-win-majority
    answer in `headone`.
  - Trades-disabled banner appears past `trade_end_date`.
  - Max-games progress bar matches games actually used in `nba_game_logs`.
- Existing point-league behavior unchanged (Itamar's league = `point`,
  scoring still shows total FPS — regression check).
