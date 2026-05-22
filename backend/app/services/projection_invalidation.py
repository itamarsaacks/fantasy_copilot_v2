"""Mark projections stale when their inputs change.

Per master plan §2.7. Wired into `sync_game_logs` so a new game log
flips `projection_cache.stale = True` for the affected player across
every league. A background worker (TBD; v1 is on-demand recompute when
the next read sees `stale=True`) drains the queue.

Eventual consistency: a player's projection may lag the latest game log
by up to ~10 min. The plan acknowledges this trade-off.

We intentionally do NOT trigger team-cascade here. CLAUDE.md states the
rule "a player's injury/trade/return invalidates every teammate's
projection" — that's an upstream invalidation (news ingestion) and
lives elsewhere. This module only handles the data-update side: I have
new actual stats, mark this player's projections stale.
"""

from __future__ import annotations

import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectionCache

log = logging.getLogger(__name__)


async def invalidate_for_player(db: AsyncSession, player_id: int) -> int:
    """Mark every projection_cache row for this player stale.

    Returns the row count flipped. Idempotent — already-stale rows stay
    stale. Caller must commit.
    """
    result = await db.execute(
        update(ProjectionCache)
        .where(ProjectionCache.player_id == player_id)
        .where(ProjectionCache.stale.is_(False))
        .values(stale=True)
    )
    n = result.rowcount or 0
    if n:
        log.debug("invalidated %d projection_cache rows for player %s", n, player_id)
    return n


async def invalidate_for_players(
    db: AsyncSession, player_ids: list[int]
) -> int:
    """Bulk invalidate. Same semantics."""
    if not player_ids:
        return 0
    result = await db.execute(
        update(ProjectionCache)
        .where(ProjectionCache.player_id.in_(player_ids))
        .where(ProjectionCache.stale.is_(False))
        .values(stale=True)
    )
    n = result.rowcount or 0
    if n:
        log.debug("invalidated %d projection_cache rows for %d players", n, len(player_ids))
    return n
