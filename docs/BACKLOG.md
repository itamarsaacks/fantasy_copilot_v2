# Backlog

> Things we want but haven't built yet. Captured here so they survive across
> sessions instead of living in chat scrollback.
>
> **Convention:** every tab and every cross-cutting concern gets its own
> section below. When we ship a tab, we leave its section in place and add
> items as they surface. Empty sections are placeholders for tabs not yet
> built. Add new items at the top of the relevant section.

---

## Global / cross-cutting

### Yahoo write OAuth scope (Stage 2 lift)
Today everything is read-only (`fspt-r`). Several "real" actions are blocked
on getting the write scope (`fspt-w`):

- Team tab: real slot swap (currently local what-if only)
- Players / Waivers: add a free agent, drop a player, claim a waivers player
- Trades: propose / accept / reject trades

This is a one-shot re-auth event — every existing user has to reconnect Yahoo
after we add the scope. Worth doing as one batch when 2-3 of these are queued.

### Feedback buttons on agent responses (post-launch)
👍 / 👎 on each chat message → `chat_feedback` table → admin dashboard pulls
recent 👎 with trace link + comment. Most useful when there are real users.
Until then, in-person feedback is higher signal.

### Eval infra (Phase E5/E6/E7)
- E5: admin gate via `ADMIN_EMAILS` env + `require_admin` dep
- E6: `/api/admin/evals/*` routes (runs, cases, results, traces)
- E7: `/eval` frontend route with 6 views (case library, recent run, regressions, vocab health, run trends, case detail)
- E8 (deferred): cron + weekly digest

### Improvement-loop case-tightening (deferred per build-order rule)
Both at 3/4 borderline misses today; will tighten once features land:
- `injury_screen_fa_list` — agent skips `get_injury_status` when status flags are inline in `top_projected_free_agents`
- `start_sit_tonight` — same root cause; agent thinks schedule + roster is enough

---

## Team tab

Shipped in commit `8eface1` (Stage 1) + `68f2d1f` (past actuals).
Browseable per-date roster with projection / actual fps, status badges,
slot what-if swap.

### Per-date projection — Stage 2 inputs
Today: `season_per_game × home(±3%) × b2b(0.93)/rest(1.05) × availability`.
Missing real opponent context.
- Compute team defensive ratings (fpts allowed per game) from `nba_game_logs`
- Plug into projection as opponent factor
- Stretch: minutes trend (last 10 games), pace, position-vs-DvP

### Real slot swap (write scope)
Today the slot pill is a local what-if. Push to Yahoo via `fspt-w` scope.
See Global → Yahoo write OAuth scope.

### Other tweaks the user flagged on 2026-05-12 (not yet enumerated)
User said "there are other things i want to fix" — list to be captured next
session. Possibly:
- More status info inline (PROBABLE, GTD detail, expected return)
- Total team fps for the selected day (we removed totals; might want it
  back as an opt-in for past-date post-mortems)
- Lineup save / load named scenarios
- Highlight optimal lineup ("you left 12 fps on the bench")

---

## Players tab

Shipped in commit `d50a614`. Search/filter/sort over the league universe.

### Click → player detail panel
Modal or side sheet with: full season stats, recent form (last 7/14/30),
game log, schedule preview, news headlines, projection breakdown,
percent_started, draft analysis.

### News indicator per row
Small dot/icon when the player has a recent `NewsItem`. Click to expand
the headline list.

### Inline schedule preview
Yahoo-style "M T W Th F Sa Su" with games marked, B2B highlighted.

### Action buttons (write scope)
Add / Drop / Claim / Watch — needs `fspt-w` (see Global).

### More filters
- NBA team chip (only Lakers, only DEN, etc.)
- Status (Healthy / Questionable / Out)
- Min GP (hide skewed small-sample lines)
- "Playing tonight" toggle

### More stat columns
- TO (we hide it currently)
- FG%, FT%, 3PM, GP, MPG, %started — important for 9-cat leagues

### Recent-form view
Toggle between season / L7 / L14 / L30. The `PlayerStats.scope` field
already supports this; today we only query `scope='season'`.

### Per-date stats view
Same "look up actuals on this date" mode we built for Team tab.

### Compare flow
Multi-select 2–3 players → side-by-side. Surfaces the existing
`compare_players` agent tool as UI.

### "Add to trade builder"
Route to Trades tab with a player pre-selected.

---

## Waivers tab

Not yet built. See current planning in this session — may or may not stay as
a separate tab. Possible scope:

- Currently on waivers (with clear time)
- Recently dropped (timeline)
- Pickup recommendations (paired add/drop)
- FAAB balance + pending bids + bid history
- "Add X, drop Y" preview with projection delta

---

## League tab

Not yet built. Possible scope:

- Full standings table (W/L, fps for/against, streak)
- Weekly matchups + projected winner
- Playoff bracket
- League rules / scoring detail
- FAAB / waiver settings
- Manager rosters (cross-team browse)

---

## Trades tab

Not yet built. Phase 9. Possible scope:

- Trade analyzer (paste a proposal, get an opinion)
- Trade suggester (find candidates for my needs)
- Active / proposed trades visible
- Trade history
- "Stat profile fit" — categories I'm weak in × who has surplus

---

## Chat tab

Already shipped (Phase 6/7). Possible improvements:

- Per-message feedback buttons — see Global → Feedback buttons
- Conversation list / search across past threads
- Suggested follow-up chips after each agent reply
- "Snapshot" share: export a chat answer as a shareable card
- Replay/regenerate a message with one click

---

## Dashboard (not built — open question)

v1 had a dashboard. v2 doesn't yet. Open question whether we want one in v2
or if Chat + the per-tab views are enough.

---

<!-- Add new items above this line. Each tab keeps its own section so we can
     find "what's missing on the Players page" in one place. -->
