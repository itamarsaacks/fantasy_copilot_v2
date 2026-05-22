# Tab plan — trades-waiver

> Merge Trades + Waiver into one tab with sub-tabs. New Waiver Planner uses calendar picker.
> Master plan §4 item 6. Branch: `feature/trades-waiver-tab`.

## Context

Current state: Trades and Waivers are separate top-level tabs. New
layout collapses both under "Trades + Waivers" with NestedTabs:

- **Sub-tab 1 — Trades:** existing trade builder (mostly unchanged)
- **Sub-tab 2 — Waiver Planner:** brand new. User picks specific
  calendar dates via `CalendarMultiPicker`. Backend returns FAs whose
  teams play on those exact dates, ranked by projected FPS sum across
  those dates. Blank state if no team plays selected dates.

## Data-foundation prerequisites

- ✅ `/api/waiver-planner/candidates?league_id=N&dates=…` endpoint
- ✅ `CalendarMultiPicker` shared component
- ⏳ `nba_schedule` populated for the date range users will browse
- ⏳ Projection cache fresh

## Shared primitives used

`NestedTabs`, `CalendarMultiPicker`, `PlayerChip`, `PlayerAvatar`,
shared `player-drawer`.

## Net new code

**Frontend:**
- Top-level route consolidation: drop `/waivers`, redirect to
  `/trades?tab=waiver-planner` or move both under `/trades-waiver/{sub}`
- `frontend/src/components/waivers/planner-view.tsx` — new view
  using `CalendarMultiPicker` + candidates list
- Keep existing `/waivers` (the windowed-pickups view) accessible as
  a third sub-tab? Decide in Phase 1.

## Phases

| # | Phase | Deliverable | Smoke check |
|---|---|---|---|
| 1 | Sub-tab structure | Trades + Waiver Planner load under one route | Click sub-tab, content swaps |
| 2 | Calendar picker + candidates list | Pick 3 dates → see ranked FAs | Pick Mon/Wed/Fri → list populated |
| 3 | Blank state | Pick a day no NBA team plays → message | All-star break date → empty msg |
| 4 | Sidebar nav update | Remove standalone Waivers entry | Nav reflects new structure |

## Verification

Replay date 2026-03-15:
- Pick 3/17 + 3/19 + 3/22 → candidates ranked by projected FPS window
- Pick 2/16 (All-Star Saturday, no games) → blank-state message
- Click an FA → player drawer

## Out of scope

- One-click waiver claim (Yahoo write API — non-goal)
- FAAB bid suggestions
- Optimal-pick-up solver across N FAs simultaneously
