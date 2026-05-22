# Tab plan — chat-mentions

> Wire clickable player/team chips into agent chat replies.
> Master plan §4 item 1. Branch: `feature/chat-mentions`.

## Context

Today the chat tab renders agent replies as markdown text. The data
foundation now provides headshots (in `frontend/public/headshots/`) and
team logos (in `frontend/public/nba-logos/`), plus the
`<PlayerChip/>`, `<PlayerAvatar/>`, `<TeamLogo/>` primitives in
`frontend/src/components/shared/`. The post-processor
`renderWithMentions(text, ctx)` already exists in
`frontend/src/lib/render-with-mentions.tsx`.

Goal: replace the raw-text rendering in `<Message>` with
`renderWithMentions` for assistant messages.

## Data-foundation prerequisites

- ✅ `espn_player_id` + `headshot_path` on `players`
- ⏳ Headshots downloaded (`backend/scripts/download_headshots.py` must
  have run; otherwise PlayerAvatar falls back to initials — acceptable).
- ⏳ NBA team logos in `frontend/public/nba-logos/<ABBR>.svg` — without
  these, TeamLogo falls back to colored monograms (acceptable).
- ✅ `PlayerChip`, `PlayerAvatar`, `TeamLogo`, `renderWithMentions` built

## Shared primitives used

`PlayerChip`, `PlayerAvatar`, `TeamLogo`, `renderWithMentions`,
`useActiveLeague` (to know which league's players are "known").

## Net new code

**Backend:**
- New endpoint `GET /api/players/mention-context?league_id=N` that
  returns the lean known-players list (player_id, full_name, last_name,
  position, nba_team_abbr, headshot_path) — used to feed `renderWithMentions`
  context. Avoid serializing the full Players table on every chat render.
- Optional (Risk #4 mitigation): extend the agent's chat response shape
  to include a `mentions[]` sidecar so the post-processor doesn't have
  to fuzzy-match for ambiguous names.

**Frontend:**
- `frontend/src/components/chat/message.tsx` — swap the raw markdown
  render for `renderWithMentions(text, ctx)` on assistant messages only
  (user-typed messages stay plain — they don't need chips).
- Wire `onPlayerClick={(id) => open player drawer}` — drawer comes
  from the Players tab session; until then, route to `/players?id=<id>`.

## Phases

| # | Phase | Deliverable | Smoke check |
|---|---|---|---|
| 1 | Backend mention-context endpoint | New endpoint returns leaderboard-style list | `curl /api/players/mention-context?league_id=…` returns valid JSON |
| 2 | Frontend hook + cache | `useMentionContext(leagueId)` (TanStack Query) | Network tab shows one request per league, cached |
| 3 | Wire renderWithMentions into Message | Assistant replies show clickable chips | Send a message naming Embiid; chip renders w/ headshot |
| 4 | Click chip → drawer | Drawer opens player detail | Playwright: click chip; drawer visible |

## Verification

Replay mode (`AS_OF_DATE=2026-03-15`), backend running, headshots downloaded:

1. Open `/chat`
2. Ask: "Who scored the most points yesterday in my league?"
3. Expected: reply contains clickable player chips (avatar + name); team
   names render with mini logos
4. Click a chip → player drawer opens

## Out of scope

- Hover preview cards (defer to Players tab session)
- Stat-line inline highlighting ("30 pts" → highlight)
- Editing chips inside user-typed messages

## Risks

- Name collisions ("McDaniels"): mitigated by the post-processor's
  unique-only last-name strategy; ambiguous tokens stay plain text.
- Performance: mention-context fetched once per league; cached.
