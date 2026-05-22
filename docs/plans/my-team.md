# Tab plan — my-team

> Existing Team tab + clickable cards + date toggle (future = projection) + what-if simulator.
> Master plan §4 item 4. Branch: `feature/my-team-tab`.

## Context

Current Team tab already has per-date projection/actuals and a basic
slot what-if swap. Add:
- Clickable player cards opening the shared drawer (full analytics:
  averages, totals, timeline) — replaces the inline stat strip.
- Date toggle (prev/next + last-7 picker) — already partially present
  via `?date=` query param, needs standard DateToggle component.
- Future-date projections: when toggled to a date > today, FPS column
  shows projection (or "-" if player not playing that date).
- Waiver-planner-style what-if: swap roster slots with FAs or other
  owned players, see projected FPS delta over a date window.

## Data-foundation prerequisites

- ✅ `project_fps_on_date(player_id, league_id, on_date)`
- ✅ `project_fps_for_window(player_id, league_id, dates)`
- ✅ `POST /api/team/simulate` endpoint
- ✅ Shared `player-drawer` (when migrated from `components/players/`)
- ⏳ `nba_game_logs` for the date(s) being viewed
- ⏳ Projection cache fresh for current rostered players

## Shared primitives used

`DateToggle`, `PlayerAvatar`, `PlayerChip`, `player-drawer`.

## Net new code

**Frontend:**
- Migrate scattered date helpers in `team-view.tsx` → use `lib/date-utils`
- Wire shared `DateToggle` (delete the local date controls)
- Replace inline player rows with `PlayerChip` + drawer-open onClick
- New what-if panel: select N swaps + N dates → calls `/api/team/simulate`,
  shows baseline vs simulated FPS

## Phases

| # | Phase | Deliverable | Smoke check |
|---|---|---|---|
| 1 | Swap to shared date-utils + DateToggle | No regression in date behavior | Switch date, roster updates |
| 2 | Clickable player rows → shared drawer | Click → drawer | Player drawer opens |
| 3 | Future-date projections | Toggle to next Wed; shows projected FPS | Future date → numeric FPS, not "-" |
| 4 | What-if simulator panel | Pick swaps + dates → see delta | Add swap → delta updates |

## Verification

Replay date 2026-03-15:
- Roster shows my team's lineup for 3/15
- Toggle to 3/16 → FPS column shows projections (not actuals)
- Click a player → drawer
- Open simulator → drop player X, add FA Y, dates [3/16, 3/17, 3/19]
  → delta visible

## Out of scope

- Multi-team what-if (compare my team's two hypothetical futures)
- Optimal-lineup solver — deferred
- Setting starting lineup from this tab (Yahoo write API — non-goal)
