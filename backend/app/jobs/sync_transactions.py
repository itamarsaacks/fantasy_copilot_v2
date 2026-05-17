"""Pull every Yahoo transaction for a league and write
PlayerOwnershipEvent rows for each player movement.

Idempotent — the unique constraint (league_id, player_id, transaction_key)
makes re-runs a no-op for known transactions.

Triggered on-demand from the player-detail endpoint (so the first time
a user opens a player's drawer, we backfill ownership history for that
league). A daily cron could call this too; we don't need one until
multi-user usage scales.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import yahoo as yahoo_client
from app.db.models import League, Player, PlayerOwnershipEvent, Team, User
from app.services.yahoo_auth import get_fresh_access_token

log = logging.getLogger(__name__)


async def _sync_draft(
    db: AsyncSession, *, access_token: str, league: League
) -> int:
    """Pull the league's draft results and write an "add" PlayerOwnershipEvent
    per pick at the league's draft_time.

    Without this, drafted players who were never traded have no history
    at all — the transactions endpoint only covers post-draft moves.
    Idempotent via the transaction_key unique constraint (we use a
    synthetic key 'draft-<league_key>-pick<N>').
    """
    picks = await yahoo_client.fetch_league_draft_results(
        access_token, league.league_key
    )
    if not picks:
        return 0

    draft_ts = (league.settings_json or {}).get("draft_time")
    try:
        draft_at = datetime.fromtimestamp(int(draft_ts), tz=timezone.utc)
    except (TypeError, ValueError):
        # Fallback to a synthetic "early in season" date so the events
        # still anchor before any post-draft trade.
        draft_at = datetime(2025, 10, 1, tzinfo=timezone.utc)

    player_keys = {p["player_key"] for p in picks if p.get("player_key")}
    team_keys = {p["team_key"] for p in picks if p.get("team_key")}
    players = (
        {
            p.yahoo_player_key: p.id
            for p in (
                await db.execute(
                    select(Player).where(Player.yahoo_player_key.in_(player_keys))
                )
            ).scalars().all()
        }
        if player_keys
        else {}
    )
    teams = (
        {
            t.team_key: t.id
            for t in (
                await db.execute(
                    select(Team).where(
                        Team.league_id == league.id, Team.team_key.in_(team_keys)
                    )
                )
            ).scalars().all()
        }
        if team_keys
        else {}
    )

    rows: list[dict[str, Any]] = []
    for pick in picks:
        player_id = players.get(pick.get("player_key") or "")
        team_id = teams.get(pick.get("team_key") or "")
        if not player_id or not team_id:
            continue
        rows.append(
            {
                "league_id": league.id,
                "player_id": player_id,
                "occurred_at": draft_at,
                "event_type": "add",
                "from_team_id": None,
                "to_team_id": team_id,
                "transaction_key": f"draft-{league.league_key}-pick{pick.get('pick')}",
                "raw": {
                    "tx_type": "draft",
                    "round": pick.get("round"),
                    "pick": pick.get("pick"),
                    "cost": pick.get("cost"),
                },
            }
        )
    if not rows:
        return 0
    stmt = (
        pg_insert(PlayerOwnershipEvent)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["league_id", "player_id", "transaction_key"]
        )
    )
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount if res.rowcount is not None else 0


async def sync_league_transactions(
    db: AsyncSession, *, user: User, league: League
) -> dict[str, int]:
    """Pull draft results AND all transactions for this league, upserting
    ownership events for both.

    Returns counts for observability:
      {fetched: N, players_seen: N, events_written: N, draft_events: N}
    """
    access_token = await get_fresh_access_token(db, user)

    # 1. Draft (initial team assignments)
    draft_events = await _sync_draft(db, access_token=access_token, league=league)

    # 2. Post-draft transactions (adds / drops / trades)
    raw_txns = await yahoo_client.fetch_league_transactions(
        access_token, league.league_key
    )

    if not raw_txns:
        return {
            "fetched": 0,
            "players_seen": 0,
            "events_written": 0,
            "draft_events": draft_events,
        }

    # Build lookup maps: player_key → player_id, team_key → team_id
    player_keys = {
        p["player_key"]
        for tx in raw_txns
        for p in tx["players"]
        if p.get("player_key")
    }
    team_keys = set()
    for tx in raw_txns:
        for p in tx["players"]:
            if p.get("source_team_key"):
                team_keys.add(p["source_team_key"])
            if p.get("destination_team_key"):
                team_keys.add(p["destination_team_key"])

    players = {
        p.yahoo_player_key: p.id
        for p in (
            await db.execute(
                select(Player).where(Player.yahoo_player_key.in_(player_keys))
            )
        ).scalars().all()
    } if player_keys else {}
    teams = {
        t.team_key: t.id
        for t in (
            await db.execute(
                select(Team).where(
                    Team.league_id == league.id, Team.team_key.in_(team_keys)
                )
            )
        ).scalars().all()
    } if team_keys else {}

    rows_to_write: list[dict[str, Any]] = []
    players_seen: set[int] = set()
    for tx in raw_txns:
        tx_key = tx["transaction_key"]
        if tx.get("status") and tx["status"] not in {"successful", "accepted"}:
            # Pending / vetoed / rejected — skip. We only track completed.
            continue
        occurred_at = datetime.fromtimestamp(tx["timestamp"] or 0, tz=timezone.utc)
        for pmove in tx["players"]:
            pkey = pmove.get("player_key")
            player_id = players.get(pkey) if pkey else None
            if player_id is None:
                # Player not in our DB (rare — could be a player from
                # a different season that didn't make it into our
                # current player table). Skip silently.
                continue
            movement = pmove.get("movement_type")
            # Yahoo movement_types we care about: add, drop, trade.
            # Trades carry both source_team_key and destination_team_key.
            # Adds usually have source_type=waivers|freeagents and dest=team.
            # Drops are the reverse.
            if movement not in {"add", "drop", "trade"}:
                continue
            from_team_id = teams.get(pmove.get("source_team_key") or "")
            to_team_id = teams.get(pmove.get("destination_team_key") or "")

            # Classify the event:
            #   movement=trade  team X → team Y
            #   movement=add    waivers/FA → team
            #   movement=drop   team → waivers/FA
            if movement == "trade" or tx["type"] == "trade":
                event_type = "trade"
            elif movement == "add":
                event_type = "add"
            else:
                event_type = "drop"
            players_seen.add(player_id)
            rows_to_write.append(
                {
                    "league_id": league.id,
                    "player_id": player_id,
                    "occurred_at": occurred_at,
                    "event_type": event_type,
                    "from_team_id": from_team_id,
                    "to_team_id": to_team_id,
                    "transaction_key": tx_key,
                    "raw": {
                        "source_type": pmove.get("source_type"),
                        "destination_type": pmove.get("destination_type"),
                        "tx_type": tx["type"],
                        "status": tx.get("status"),
                    },
                }
            )

    events_written = 0
    if rows_to_write:
        stmt = (
            pg_insert(PlayerOwnershipEvent)
            .values(rows_to_write)
            .on_conflict_do_nothing(
                index_elements=["league_id", "player_id", "transaction_key"]
            )
        )
        res = await db.execute(stmt)
        await db.commit()
        # rowcount is the number of *inserted* rows (excluded by conflict).
        events_written = res.rowcount if res.rowcount is not None else 0

    return {
        "fetched": len(raw_txns),
        "players_seen": len(players_seen),
        "events_written": events_written,
        "draft_events": draft_events,
    }
