# Backlog

> Things we want but haven't built yet. Captured here so they survive across
> sessions instead of living in chat scrollback.
>
> **Convention:** every tab gets its own section. Add new items at the top
> of the relevant section. When you ship something, leave the section in
> place (so we can find "what's missing on Players" in one spot) but cross
> the item out or move to a "Done" sub-list.

_Last updated: 2026-05-17_

---

## Global / cross-cutting

### Yahoo write OAuth scope (`fspt-w`)
Today everything is read-only (`fspt-r`). Blocks:
- Team tab: real slot swap (currently local what-if)
- Players / Waivers: add a free agent, drop a player, claim a waivers player
- Trades: propose / accept / reject trades

One-shot re-auth event for every existing user. Worth doing as a batch
when 2-3 of these are queued.

### Background nightly game-log backfill
Biggest remaining perf win for the Players drawer. Cold per-date Yahoo
fetches still cost ~1.7s for new ranges. A nightly job pre-warming
`nba_game_logs` for every rostered + FA player would make every range
pure DB (~50ms).

Sketch:
- New `sync_player_history.py` job
- Iterates all FA + rostered players, fans out ~7 days at a time
- Caps total round-trips per night (Yahoo doesn't love huge bursts)
- Idempotent via existing `nba_game_logs` unique constraint

### Feedback buttons on agent responses (post-launch)
👍 / 👎 on each chat message → `chat_feedback` table → admin dashboard
pulls recent 👎 with trace link + comment. Most useful when there are
real users.

### Improvement-loop case-tightening (now unblocked)
Build-everything-first gate is lifted. Two known borderline misses
from 5/12 (both at 3/4):
- `injury_screen_fa_list` — agent skips `get_injury_status` when status
  flags are inline in `top_projected_free_agents`
- `start_sit_tonight` — same root cause

### Incremental transactions sync
Current sync paginates 1391+ transactions every time it runs from
scratch. The endpoint trigger only re-syncs if no events exist for the
league. Eventually want:
- "newest event in DB → only fetch newer pages"
- Cron daily so new trades land without waiting on a user click

### Public-launch email-based admin gate
Currently `ADMIN_USER_IDS=1,2,...` (User.id). Yahoo doesn't give us
email cleanly. Switch to email-based gate when we add email collection
for public launch.

### Eval infra E8 — Cron + weekly digest
Auto-trigger full-suite runs on a schedule, post a digest to a Slack
channel or email when verdicts shift.

---

## Team tab

Shipped: per-date roster + projection / actual fps + slot what-if swap
(`8eface1`, `68f2d1f`).

### Per-date projection — Stage 2 inputs
Today: `season_per_game × home(±3%) × b2b(0.93)/rest(1.05) × availability`.
Missing real opponent context.
- Compute team defensive ratings (fpts allowed per game) from `nba_game_logs`
- Plug into projection as opponent factor
- Stretch: minutes trend (last 10 games), pace, position-vs-DvP

### Real slot swap (write scope)
See Global → Yahoo write scope.

### Other tweaks the user flagged but didn't enumerate
- More status detail inline (PROBABLE, GTD detail, expected return)
- Total team fps for the selected day — opt-in for past-date post-mortems
- Lineup save / load named scenarios
- "Optimal lineup" highlight ("you left 12 fps on the bench")

---

## Players tab

Shipped v1 + v2 + the 5-pass polish (`d50a614` → `07a4e5d`).

### Per-segment stats card on timeline click
User asked for "click a period → clean look of average stats" — currently
clicking sets the Stats tab range but doesn't surface a compact summary
near the timeline itself. Small inline stats card under each chip would
be nicer.

### Season-overall vs period toggle
A toggle on the Stats tab to switch between "stats for this period" and
"season overall." Easy with the existing data.

### Projection breakdown card
Click the projected fps number → reveal the component breakdown
(`per_game × home_factor × b2b_factor × availability_factor`). The data's
already in the response, just no UI.

### News indicator per row (Players list, not drawer)
Small dot/icon when player has recent `NewsItem`. Click expands.

### More filters
- NBA team chip (only LAL, etc.)
- Status (Healthy / Questionable / Out)
- Min GP
- "Playing tonight" toggle

### More stat columns
- TO (hidden currently)
- FG%, FT%, 3PM, GP, MPG, %started — important for 9-cat leagues

### Action buttons on the drawer (write scope)
Add / Drop / Claim / Watch — needs `fspt-w`.

### "Add to trade builder"
Route from drawer to Trades tab with player pre-loaded.

---

## Waivers tab

Shipped v1 (`0bc950c` + `3a6892f`).

### Slot-eligibility check on paired swaps
Currently any pickup can be paired with any drop. Add the same
`canFillSlot` check the Team tab uses so suggestions stay legal.

### Recently-dropped timeline
Show players just dropped (last 24-72h) as pickup candidates. Needs
the `player_ownership_events` table we just added — query for
recent `drop` events.

### FAAB context
User's league is waiver-priority so this is deferred. When we onboard
a FAAB user, surface balance + pending bids + bid history.

### Real claim/drop actions
See Global → Yahoo write scope.

---

## League tab

Shipped v1 (`6dddd27`).

### Manager roster click-through
Click a row → drawer/page showing that team's full roster, mirroring
the Team tab layout.

### Weekly matchup view
Will need it when the next season starts. Yahoo's `scoreboard` endpoint
+ projections gives "projected winner per matchup."

### Playoff bracket
Once playoffs run, show the bracket + per-round matchups.

---

## Trades tab

Shipped v1 (`32b7cfa`).

### Trade history
No ingest yet. Could derive from `player_ownership_events` (where
event_type='trade'), grouping by `transaction_key`.

### Submit proposal to Yahoo
See Global → Yahoo write scope.

### Position-eligibility / lineup-viability check after swap
"You'd have 0 PGs left."

### Auto-suggest trade partners
Find candidates for my roster gaps. Some "stat profile fit" logic:
categories I'm weak in × teams with surplus.

### "Chat about this trade" button
Open a new chat thread with the trade context pre-loaded.

---

## Chat tab

Shipped Phase 6/7. Improvements:

- Per-message feedback buttons — see Global → Feedback buttons
- Conversation list / search across past threads
- Suggested follow-up chips after each agent reply
- "Snapshot" share: export an answer as a shareable card
- Replay/regenerate a message with one click

---

## Eval dashboard

Shipped (E5/E6/E7) (`13a5606`).

### Per-run charts
Currently the dashboard is a table-heavy view. A small sparkline of
pass-rate across the last 10 runs on the landing page would help.

### Vocab health view
Aggregate vocab-cluster pass rate across all cases — surface which
intent vocabulary is consistently missed.

### Bulk trace download
"Download all FAIL traces from run #N as a zip" — useful for offline
triage.

### Cron + digest (E8)
See Global → Eval infra E8.

---

## Dashboard (open question)

v1 had a dashboard. v2 doesn't yet. Open question whether we want one
in v2 or if Chat + the per-tab views are enough.

---

<!-- Add new items above this line. Each tab keeps its own section. -->
