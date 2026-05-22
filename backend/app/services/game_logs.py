"""Read-only game-log accessor — Postgres only, never Yahoo at request time.

Per master plan §2.3: every request-path endpoint reads from
`nba_game_logs` only. Yahoo lives in background jobs (sync_game_logs.py)
and one-shot backfill scripts.

If a row is missing for a date ≤ yesterday, the player did not play on
that date (the sync job writes a placeholder did_not_play=True row when
Yahoo confirms "no game line"). Future dates return nothing — projections
handle those.

Callers should NOT import `app.services.player_history.fetch_and_cache_logs`
from inside request handlers. The CI guard in `scripts/check_forbidden_sources.sh`
will (after this lands) escalate the players.py / team.py warnings into
failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NbaGameLog


@dataclass(frozen=True)
class GameLogRow:
    """Normalized game-log row returned to endpoints + agent tools."""

    player_id: int
    game_id: str
    game_date: date_type
    opponent_abbr: str | None
    is_home: bool | None
    minutes: float | None
    box: dict[str, Any]
    did_not_play: bool

    def fps_for(self, valuator) -> float | None:  # noqa: ANN001
        """Compute FPS using a league-scoring valuator (passed in by caller)."""
        if self.did_not_play or not self.box:
            return None
        return float(valuator.value_of(self.box))


async def get_logs_for_player(
    db: AsyncSession,
    player_id: int,
    start: date_type,
    end: date_type,
) -> list[GameLogRow]:
    """Return rows for [start, end] inclusive, ordered ascending by date."""
    if start > end:
        return []
    rows = (
        (
            await db.execute(
                select(NbaGameLog)
                .where(
                    and_(
                        NbaGameLog.player_id == player_id,
                        NbaGameLog.game_date >= start,
                        NbaGameLog.game_date <= end,
                    )
                )
                .order_by(NbaGameLog.game_date)
            )
        )
        .scalars()
        .all()
    )
    return [
        GameLogRow(
            player_id=r.player_id,
            game_id=r.game_id,
            game_date=r.game_date,
            opponent_abbr=r.opponent_abbr,
            is_home=r.is_home,
            minutes=float(r.minutes) if r.minutes is not None else None,
            box=r.box or {},
            did_not_play=bool(r.did_not_play),
        )
        for r in rows
    ]


async def get_logs_for_players_on_date(
    db: AsyncSession,
    player_ids: list[int],
    on_date: date_type,
) -> dict[int, GameLogRow]:
    """Bulk: many players, one date. Used by standings_at + Games-tab box scores."""
    if not player_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(NbaGameLog).where(
                    NbaGameLog.player_id.in_(player_ids),
                    NbaGameLog.game_date == on_date,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        r.player_id: GameLogRow(
            player_id=r.player_id,
            game_id=r.game_id,
            game_date=r.game_date,
            opponent_abbr=r.opponent_abbr,
            is_home=r.is_home,
            minutes=float(r.minutes) if r.minutes is not None else None,
            box=r.box or {},
            did_not_play=bool(r.did_not_play),
        )
        for r in rows
    }
