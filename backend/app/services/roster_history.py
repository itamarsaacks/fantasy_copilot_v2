"""Point-in-time roster reconstruction.

Per master plan §2.5: roster state on date X is *replayed* from draft
results + ownership events, NOT stored as snapshots.

Public API:
    roster_at(db, team_id, on_date) -> list[RosterSlot]
    roster_at_for_league(db, league_id, on_date) -> dict[int, list[RosterSlot]]
        (one entry per team in the league — used by standings_at)

Known trade-off (documented in plan §2.5): slot positions (PG/BN/IL/etc.)
are not reconstructed historically. Yahoo doesn't expose historical
slot assignments cleanly. The returned RosterSlot exposes the player_id
+ team_id + whether-owned-on-that-date; the UI labels these "owned" not
"started" for past dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    PlayerOwnershipEvent,
    RosterPlayer,
    Team,
)
from app.services.clock import resolve_today


@dataclass(frozen=True)
class RosterSlot:
    """One owned player as of a specific date.

    We don't reconstruct positional slot (BN/PG/etc.) — see module docstring.
    """

    player_id: int
    team_id: int


def _end_of_day(d: date_type) -> datetime:
    """Treat `on_date` as inclusive — events at any time on that date count."""
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


async def roster_at(
    db: AsyncSession,
    team_id: int,
    on_date: date_type,
) -> list[RosterSlot]:
    """Players owned by `team_id` at end-of-day `on_date`.

    Algorithm:
      Pass 1: start with empty set (we don't have a draft_results table
        as a first-class entity; draft additions are logged as
        PlayerOwnershipEvent rows with event_type='add' and a
        transaction_key like 'draft-<league_key>-pickN').
      Pass 2: walk every event for this team ordered by occurred_at:
        - to_team_id == team_id  -> add player
        - from_team_id == team_id  -> remove player
    Stop at events with occurred_at > end_of_day(on_date).

    If the date is today or later AND no events have moved a player
    since the last roster_players snapshot, we fall back to
    `RosterPlayer` rows so we don't return an empty roster for a
    league we haven't fully event-sourced yet.
    """
    cutoff = _end_of_day(on_date)

    # Get team to confirm it exists and find its league_id
    team = (
        await db.execute(select(Team).where(Team.id == team_id))
    ).scalar_one_or_none()
    if team is None:
        return []

    # Pass: events touching this team, in order
    q = (
        select(PlayerOwnershipEvent)
        .where(PlayerOwnershipEvent.league_id == team.league_id)
        .where(
            (PlayerOwnershipEvent.to_team_id == team_id)
            | (PlayerOwnershipEvent.from_team_id == team_id)
        )
        .where(PlayerOwnershipEvent.occurred_at <= cutoff)
        .order_by(PlayerOwnershipEvent.occurred_at)
    )
    events = (await db.execute(q)).scalars().all()

    owned: set[int] = set()
    for ev in events:
        if ev.to_team_id == team_id:
            owned.add(ev.player_id)
        elif ev.from_team_id == team_id:
            owned.discard(ev.player_id)

    if owned:
        return sorted(
            (RosterSlot(player_id=pid, team_id=team_id) for pid in owned),
            key=lambda s: s.player_id,
        )

    # Fallback for leagues where transactions aren't fully synced yet:
    # if the requested date is today (or later) and we'd otherwise return
    # an empty roster, use the live RosterPlayer rows so the UI has data.
    today_or_later = on_date >= resolve_today()
    if not events and today_or_later:
        rp_q = select(RosterPlayer.player_id).where(
            RosterPlayer.team_id == team_id
        )
        return [
            RosterSlot(player_id=pid, team_id=team_id)
            for (pid,) in (await db.execute(rp_q)).all()
        ]

    return []


async def roster_at_for_league(
    db: AsyncSession,
    league_id: int,
    on_date: date_type,
) -> dict[int, list[RosterSlot]]:
    """All teams in a league → their roster on `on_date`.

    Used by standings_at and the League-tab opponent-drawer endpoint.
    Avoids N round-trips by issuing one query per team but reusing a
    cached "events for this league before cutoff" set.
    """
    cutoff = _end_of_day(on_date)
    teams = (
        await db.execute(select(Team).where(Team.league_id == league_id))
    ).scalars().all()

    events = (
        (
            await db.execute(
                select(PlayerOwnershipEvent)
                .where(PlayerOwnershipEvent.league_id == league_id)
                .where(PlayerOwnershipEvent.occurred_at <= cutoff)
                .order_by(PlayerOwnershipEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    owned_per_team: dict[int, set[int]] = {t.id: set() for t in teams}
    for ev in events:
        if ev.to_team_id is not None and ev.to_team_id in owned_per_team:
            owned_per_team[ev.to_team_id].add(ev.player_id)
        if ev.from_team_id is not None and ev.from_team_id in owned_per_team:
            owned_per_team[ev.from_team_id].discard(ev.player_id)

    # Fallback to live roster for any team that has no events
    today_or_later = on_date >= resolve_today()
    result: dict[int, list[RosterSlot]] = {}
    for team in teams:
        owned = owned_per_team.get(team.id, set())
        if not owned and today_or_later:
            rp_q = select(RosterPlayer.player_id).where(
                RosterPlayer.team_id == team.id
            )
            owned = {pid for (pid,) in (await db.execute(rp_q)).all()}
        result[team.id] = [
            RosterSlot(player_id=pid, team_id=team.id) for pid in sorted(owned)
        ]
    return result
