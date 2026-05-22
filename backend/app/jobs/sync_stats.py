"""Sync per-player raw NBA stats for all players in a league (rosters + FAs).

Stats are fetched from Yahoo's GLOBAL /players endpoint (not league-scoped),
which returns ALL stats including GP. Stored as raw NBA stats — the
projection engine applies per-league scoring rules at compute time.

We still tag rows with league_key for provenance + cleanup, but the values
are league-independent. Different leagues sharing players will write
duplicate rows; that's intentional + cheap, keeps the table simple.

Writes into `player_stats` (append-only time-series). Idempotent for the
same as_of_date via ON CONFLICT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import yahoo
from app.db.engine import SessionLocal
from app.db.models import FreeAgent, League, Player, PlayerStats, RosterPlayer, Team, User
from app.services.clock import resolve_today
from app.services.yahoo_auth import YahooAuthBroken, get_fresh_access_token

log = logging.getLogger(__name__)

BATCH_SIZE = 25  # Yahoo's max
COVERAGE_TO_SCOPE = {
    "season": "season",
    "lastweek": "last_7",
    "lastmonth": "last_30",
}


@dataclass
class StatsSyncResult:
    league_key: str
    coverage: str
    players_attempted: int = 0
    players_with_stats: int = 0
    stat_rows_written: int = 0
    errors: list[str] = field(default_factory=list)


async def sync_league_stats(
    user_id: int, league_id: int, coverage: str = "season"
) -> StatsSyncResult:
    """Fetch per-player stats for all rostered + FA players in a league.

    Writes one PlayerStats row per (player, stat_id) at today's as_of_date.
    Idempotent for the same as_of_date (uses ON CONFLICT DO UPDATE).
    """
    if coverage not in COVERAGE_TO_SCOPE:
        return StatsSyncResult(
            league_key="?",
            coverage=coverage,
            errors=[f"unsupported coverage: {coverage}"],
        )

    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        league = await session.get(League, league_id)
        if not user or not league or league.user_id != user_id:
            return StatsSyncResult(
                league_key="?",
                coverage=coverage,
                errors=["user/league not found"],
            )

        result = StatsSyncResult(league_key=league.league_key, coverage=coverage)

        try:
            access_token = await get_fresh_access_token(session, user)
        except YahooAuthBroken as exc:
            result.errors.append(f"auth broken: {exc}")
            return result

        # Collect every player_key in the league (rostered + FA)
        rostered_q = await session.execute(
            select(Player.yahoo_player_key, Player.id)
            .join(RosterPlayer, RosterPlayer.player_id == Player.id)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(Team.league_id == league.id)
        )
        rostered = {row[0]: row[1] for row in rostered_q.all()}

        fa_q = await session.execute(
            select(Player.yahoo_player_key, Player.id)
            .join(FreeAgent, FreeAgent.player_id == Player.id)
            .where(FreeAgent.league_id == league.id)
        )
        fas = {row[0]: row[1] for row in fa_q.all()}

        all_players = {**rostered, **fas}
        result.players_attempted = len(all_players)
        if not all_players:
            return result

        scope = COVERAGE_TO_SCOPE[coverage]
        as_of = resolve_today()
        keys = list(all_players.keys())

        # Batch in chunks of 25
        for i in range(0, len(keys), BATCH_SIZE):
            batch = keys[i : i + BATCH_SIZE]
            try:
                stats_by_key = await yahoo.fetch_player_stats(
                    access_token, batch, coverage=coverage
                )
            except Exception as exc:
                log.exception("stats batch failed")
                result.errors.append(
                    f"batch {i}-{i+len(batch)}: {exc.__class__.__name__}: {exc}"
                )
                continue

            written_this_batch = 0
            for player_key, stats in stats_by_key.items():
                player_id = all_players.get(player_key)
                if not player_id or not stats:
                    continue
                rows_for_upsert = [
                    {
                        "player_id": player_id,
                        "league_key": league.league_key,
                        "scope": scope,
                        "stat_id": s["stat_id"],
                        "value": _coerce_float(s.get("value")),
                        "as_of_date": as_of,
                    }
                    for s in stats
                    if _coerce_float(s.get("value")) is not None
                ]
                if not rows_for_upsert:
                    continue
                stmt = (
                    pg_insert(PlayerStats)
                    .values(rows_for_upsert)
                    .on_conflict_do_update(
                        index_elements=[
                            "player_id",
                            "league_key",
                            "scope",
                            "stat_id",
                            "as_of_date",
                        ],
                        set_={"value": pg_insert(PlayerStats).excluded.value},
                    )
                )
                await session.execute(stmt)
                written_this_batch += len(rows_for_upsert)
                result.players_with_stats += 1

            result.stat_rows_written += written_this_batch
            await session.commit()  # commit per-batch (split-transaction principle)

        return result


def _coerce_float(value) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
