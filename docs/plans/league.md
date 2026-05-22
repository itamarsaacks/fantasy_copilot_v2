# Tab plan — league

> Existing tab + opponent roster drawer + standings on date + rules footer.
> Master plan §4 item 5. Branch: `feature/league-tab`.

## Context

Current League tab shows standings + scoring + settings. Add:
- Click opponent team row → drawer with that team's roster on the
  selected date, with averages and that-day FPS per player ("-" if
  didn't play).
- Date toggle on standings — show each manager's FPS that day.
- League rules + scoring at the bottom (move from current location).

## Data-foundation prerequisites (ALL CLEARED 2026-05-22)

- ✅ `roster_at(team_id, date)` and `roster_at_for_league(league_id, date)`
- ✅ `/api/standings?league_id=N&date=…` endpoint
- ✅ `/api/teams/{team_id}/roster?date=…` endpoint
- ✅ `nba_game_logs` backfilled for 2026-03-01 → 2026-03-15 (verified —
  `Barakooda 146.9 FPS` on 3/8 via the agent's `get_standings_on_date`)
- ✅ `standings_daily_cache` populated lazily on first read; sweeper
  invalidates after game-log updates (runs every 5 min in both modes)
- ✅ `<DrawerProvider/>` mounted for opponent roster drill-in
- ✅ `<DateToggle/>` primitive

## Shared primitives used

`DateToggle`, `PlayerAvatar`, `PlayerChip`, `player-drawer` (shared).

## Net new code

**Frontend:**
- `frontend/src/components/league/opponent-roster-drawer.tsx`
- Wire DateToggle into existing `league-view.tsx`
- Add per-row click handler → opens opponent drawer
- Move rules + scoring tables into a collapsible footer section

## Phases

| # | Phase | Deliverable | Smoke check |
|---|---|---|---|
| 1 | Date toggle + that-day FPS column | Each row shows FPS for the toggled date | Switch date, values change |
| 2 | Opponent drawer | Click row → drawer w/ that team's roster | Click row → drawer visible |
| 3 | That-day FPS per player in drawer | Each player row shows FPS or "-" | Drawer rows show fps values |
| 4 | Rules + scoring footer | Bottom section toggleable | Footer renders |

## Verification

Replay date 2026-03-15:
- Each standings row shows manager FPS for 3/15
- Toggle to 3/14, values change (different game-day)
- Click opponent → drawer shows their 13 players + their 3/15 FPS
- DNP players show "-"

## Out of scope

- Per-week (matchup-period) standings — defer
- Trade-finder shortcuts from opponent drawer — that's the Trades tab
