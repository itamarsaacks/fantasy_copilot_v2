# Tab plan — games

> NEW tab. NBA scores + per-game box scores + NBA standings sub-tab.
> Master plan §4 item 3. Branch: `feature/games-tab`.

## Context

Doesn't exist today. Tab 2 in the new layout. Shows the day's NBA games
with team logos + scores. Click a game → box score. Click a player →
shared player drawer. Date toggle (prev/next + last-7 picker).
Sub-tab: NBA standings (conference tables).

## Data-foundation prerequisites

- ✅ `nba_schedule` populated (already synced from ESPN)
- ⏳ `nba_game_logs` populated for the relevant date — `sync_game_logs.py`
  must have run or `python -m app.jobs.sync_game_logs backfill --from … --to …`
- ✅ `/api/games?date=…` endpoint (in `backend/app/api/routes/games.py`)
- ✅ `/api/games/{id}/box?league_id=N` endpoint
- ⏳ NBA standings endpoint — `/api/nba/standings` — NOT YET BUILT.
  Plan to add: query `nba_schedule` for the current season, aggregate
  win/loss per team, compute conference standings. No external source.

## Shared primitives used

`DateToggle`, `TeamLogo` (everywhere), `PlayerAvatar` (box-score rows),
`NestedTabs` (scores / standings).

## Net new code

**Backend:**
- `/api/nba/standings` endpoint (aggregate from `nba_schedule`)

**Frontend:**
- `frontend/src/app/(app)/games/page.tsx` — top-level route + DateToggle + NestedTabs
- `frontend/src/components/games/games-list.tsx` — scoreboard grid
- `frontend/src/components/games/game-box-modal.tsx` — drill-in
- `frontend/src/components/games/nba-standings.tsx` — conference tables
- Sidebar nav update — add Games entry, reorder per master plan layout

## Phases

| # | Phase | Deliverable | Smoke check |
|---|---|---|---|
| 1 | Skeleton route + DateToggle | Empty grid renders, date toggle works | `/games` doesn't 404 |
| 2 | Scoreboard | Games for the date show w/ logos + score | Replay mode date shows ~10 games |
| 3 | Click-game → box | Drill-in shows per-player lines | Click a final game → box visible |
| 4 | NBA standings sub-tab | Conference tables render | E/W tables populate |
| 5 | Click-player → drawer | Shared player drawer opens | Click a player → drawer visible |

## Verification

Replay date 2026-03-15:
- `/games` shows scores + logos for ~10 games on that date
- Click LAL game → home/away box scores visible, players have headshots
- Sub-tab "Standings" → conference tables populated
- Backend logs show zero ESPN / zero Yahoo calls during this flow

## Out of scope

- Live play-by-play (out per master plan §7)
- Per-game advanced stats (efficiency, pace, defensive ratings)
- Future: clickable team logo → team page
