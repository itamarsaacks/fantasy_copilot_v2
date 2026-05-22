# Tab plan — players

> Existing Players tab + leaders + compare + timeline + EOS projection.
> Master plan §4 item 2. Branch: `feature/players-tab`.

## Context

Current Players tab has search/filter/sort + drawer (stats / schedule /
history / news) + multi-player compare. Polish + new views:
- **Leaders view** — top-N by stat, by per-game, by per-window.
- **Compare view** — already exists in `/players/compare`, integrate into main tab.
- **Timeline view** — per-player game-by-game trend across last N games.
- **EOS projection card** — projected rest-of-season totals + per-game.

## Data-foundation prerequisites (ALL CLEARED 2026-05-22 except wider backfill)

- ✅ `nba_game_logs` schema + sync — 15 days backfilled (3/1–3/15, 10,785 rows).
  Wider backfill (3+ months) recommended before this session but not blocking.
- ✅ Game-logs accessor (`get_logs_for_player`)
- ✅ Drawer migrated to `@/components/shared/player-drawer` + mobile bottom sheet
- ✅ `<DrawerProvider/>` mounted — programmatic open from anywhere via `useDrawer()`
- ✅ Headshots downloaded (PlayerAvatar shows real images for 522 players)
- ⏳ Projection refresh — game-log backfill marked projections stale, but
  worker hasn't recomputed yet. Run manually or trigger via the
  freshness scheduler in live mode.

## Shared primitives used

`PlayerAvatar`, `PlayerChip`, `NestedTabs` (analytics / compare / leaders / timeline / EOS), `DateToggle` (timeline date pivot).

## Net new code

**Backend:**
- `/api/players/leaders?stat=PTS&window=last_7&league_id=N` (compose
  existing get_top_by_stat helpers; add per-window)
- Extend `/api/players/{league_id}/{player_id}` response with
  `eos_projection: { games_left, projected_total, projected_per_game }`

**Frontend:**
- Move drawer → `components/shared/player-drawer.tsx`
- Make drawer responsive: side panel on desktop, full-screen sheet on mobile
- New sub-tab routes inside `/players` via NestedTabs
- Timeline chart component (line/bar)

## Phases

| # | Phase | Deliverable | Smoke check |
|---|---|---|---|
| 1 | Drawer move + mobile sheet | Drawer reusable everywhere | Open at 375px width → full sheet |
| 2 | Leaders view | Sortable top-N table | Top scorers list populated |
| 3 | Timeline view | Per-player game trend chart | Player → 30-game line chart |
| 4 | EOS card | RoS projection visible in drawer | Card renders |
| 5 | Compare integration | Compare lives in same tab now | NestedTabs has Compare entry |

## Verification

Replay date 2026-03-15, ~165 backfilled game-log days:
- Leaders: top-10 PTS for last_7 days returns real data
- Timeline: open Embiid → last 30 game-log bars render
- EOS card: numeric projection
- Mobile: drawer behaves as bottom sheet

## Out of scope

- Player news feed (news_items already in drawer)
- Trade-finder integration here (lives in Trades tab)
- Advanced shot charts (defer)
