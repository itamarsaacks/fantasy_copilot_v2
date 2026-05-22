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

## Data-foundation prerequisites (ALL CLEARED 2026-05-22)

- ✅ `espn_player_id` + `headshot_path` on `players`
- ✅ Headshots downloaded — 522 players in `frontend/public/headshots/`
- ✅ NBA team logo placeholder SVGs — 30 monograms in `frontend/public/nba-logos/`
- ✅ `PlayerChip`, `PlayerAvatar`, `TeamLogo`, `renderWithMentions` built
- ✅ `GET /api/players/{league_id}/mention-context` endpoint built
- ✅ `<DrawerProvider/>` mounted at app shell — `useDrawer().openPlayer(id)`
  works anywhere
- ✅ Chat agent's system prompt knows replay-mode current date

## Shared primitives used

`PlayerChip`, `PlayerAvatar`, `TeamLogo`, `renderWithMentions`,
`useActiveLeague` (to know which league's players are "known").

## Net new code

**Backend:**
- ✅ Endpoint already built — `GET /api/players/{league_id}/mention-context`
  returns `{ league_id, players: [...], teams: [...] }`.
- Optional (Risk #4 mitigation): extend the agent's chat response shape
  to include a `mentions[]` sidecar so the post-processor doesn't have
  to fuzzy-match for ambiguous names. Deferred — not needed for v1.

**Frontend:**
- `frontend/src/components/chat/message.tsx` — swap the raw markdown
  render for `renderWithMentions(text, ctx)` on assistant messages only
  (user-typed messages stay plain — they don't need chips).
- Wire `onPlayerClick={(id) => useDrawer().openPlayer(id)}` — uses the
  shared `DrawerProvider` already mounted in the app shell.
- New hook `useMentionContext(leagueId)` — TanStack Query against the
  new endpoint with `staleTime: Infinity` (data changes daily at most).

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
