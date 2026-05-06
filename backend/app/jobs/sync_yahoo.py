"""Yahoo roster + free-agent + teams sync, scoped to one (user, league).

Each concern is committed in its own transaction so a Yahoo error or slow
response can't wipe a previously-synced roster:

  1. Teams + standings
  2. Per-team rosters (one transaction per team)
  3. League-wide free agents (single transaction at the end)

Idempotent: re-running upserts existing rows by their unique keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import yahoo
from app.db.engine import SessionLocal
from app.db.models import FreeAgent, League, Player, RosterPlayer, Team, User
from app.services.yahoo_auth import YahooAuthBroken, get_fresh_access_token

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    league_key: str
    teams_synced: int = 0
    rosters_synced: int = 0
    roster_players_total: int = 0
    free_agents_synced: int = 0
    errors: list[str] = field(default_factory=list)


async def sync_league(user_id: int, league_id: int) -> SyncResult:
    """Run a full sync for one (user, league). Designed for both manual and scheduled use."""
    async with SessionLocal() as session:
        user, league = await _load_user_and_league(session, user_id, league_id)
        if not user or not league:
            return SyncResult(
                league_key="unknown",
                errors=[f"user_id={user_id} league_id={league_id} not found"],
            )
        result = SyncResult(league_key=league.league_key)

        try:
            access_token = await get_fresh_access_token(session, user)
        except YahooAuthBroken as exc:
            result.errors.append(f"auth broken: {exc}")
            return result

        # --- 1. Teams (own transaction) ---------------------------------
        try:
            await _sync_teams(session, league, access_token)
            await session.commit()
            # After commit, query teams again for use in later steps.
            teams_q = await session.execute(select(Team).where(Team.league_id == league.id))
            team_rows = list(teams_q.scalars().all())
            result.teams_synced = len(team_rows)
        except Exception as exc:
            log.exception("team sync failed for %s", league.league_key)
            result.errors.append(f"teams: {exc}")
            await session.rollback()
            team_rows = []

        # --- 2. Per-team rosters (own transaction per team) -------------
        for team in team_rows:
            try:
                roster_count = await _sync_team_roster(session, team, access_token)
                await session.commit()
                result.rosters_synced += 1
                result.roster_players_total += roster_count
            except Exception as exc:
                log.exception("roster sync failed for team %s", team.team_key)
                result.errors.append(f"roster {team.team_key}: {exc}")
                await session.rollback()

        # --- 3. Free agents (own transaction) ---------------------------
        try:
            count = await _sync_free_agents(session, league, access_token)
            await session.commit()
            result.free_agents_synced = count
        except Exception as exc:
            log.exception("FA sync failed for %s", league.league_key)
            result.errors.append(f"free_agents: {exc}")
            await session.rollback()

        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_user_and_league(
    session: AsyncSession, user_id: int, league_id: int
) -> tuple[User | None, League | None]:
    user = await session.get(User, user_id)
    league = await session.get(League, league_id)
    if league and league.user_id != user_id:
        return user, None
    return user, league


async def _sync_teams(session: AsyncSession, league: League, access_token: str) -> None:
    teams_data = await yahoo.fetch_teams(access_token, league.league_key)
    for td in teams_data:
        existing_q = await session.execute(
            select(Team).where(
                Team.league_id == league.id,
                Team.team_key == td["team_key"],
            )
        )
        team = existing_q.scalar_one_or_none()
        if team is None:
            team = Team(league_id=league.id, team_key=td["team_key"])
            session.add(team)
        team.team_id_in_league = td["team_id_in_league"]
        team.name = td["name"]
        team.manager_name = td["manager_name"]
        team.is_user_team = td["is_user_team"]
        team.wins = td["wins"]
        team.losses = td["losses"]
        team.ties = td["ties"]
        team.rank = td["rank"]
    await session.flush()


async def _sync_team_roster(session: AsyncSession, team: Team, access_token: str) -> int:
    players = await yahoo.fetch_team_roster(access_token, team.team_key)
    if not players:
        return 0

    # Upsert player identity rows
    keys = [p["yahoo_player_key"] for p in players]
    existing_q = await session.execute(
        select(Player).where(Player.yahoo_player_key.in_(keys))
    )
    existing_by_key = {p.yahoo_player_key: p for p in existing_q.scalars().all()}

    for pdata in players:
        player = existing_by_key.get(pdata["yahoo_player_key"])
        if player is None:
            player = Player(yahoo_player_key=pdata["yahoo_player_key"])
            session.add(player)
            existing_by_key[pdata["yahoo_player_key"]] = player
        _apply_player_fields(player, pdata)
    await session.flush()

    # Replace the team's current roster snapshot.
    # Strategy: delete old entries for this team, then insert fresh ones.
    # Simpler and correct as long as we're inside one transaction.
    await session.execute(
        RosterPlayer.__table__.delete().where(RosterPlayer.team_id == team.id)
    )
    for pdata in players:
        player = existing_by_key[pdata["yahoo_player_key"]]
        session.add(
            RosterPlayer(
                team_id=team.id,
                player_id=player.id,
                selected_position=pdata.get("selected_position"),
            )
        )
    await session.flush()
    return len(players)


async def _sync_free_agents(session: AsyncSession, league: League, access_token: str) -> int:
    fas = await yahoo.fetch_league_free_agents(access_token, league.league_key)
    if not fas:
        # Wipe in case the league's FA list went to zero (all owned).
        await session.execute(
            FreeAgent.__table__.delete().where(FreeAgent.league_id == league.id)
        )
        return 0

    keys = [p["yahoo_player_key"] for p in fas]
    existing_q = await session.execute(
        select(Player).where(Player.yahoo_player_key.in_(keys))
    )
    existing_by_key = {p.yahoo_player_key: p for p in existing_q.scalars().all()}

    for pdata in fas:
        player = existing_by_key.get(pdata["yahoo_player_key"])
        if player is None:
            player = Player(yahoo_player_key=pdata["yahoo_player_key"])
            session.add(player)
            existing_by_key[pdata["yahoo_player_key"]] = player
        _apply_player_fields(player, pdata)
    await session.flush()

    # Replace the FA snapshot for this league.
    await session.execute(
        FreeAgent.__table__.delete().where(FreeAgent.league_id == league.id)
    )
    for pdata in fas:
        player = existing_by_key[pdata["yahoo_player_key"]]
        session.add(
            FreeAgent(
                league_id=league.id,
                player_id=player.id,
                waiver_status=pdata.get("waiver_status"),
                percent_owned=pdata.get("percent_owned"),
            )
        )
    await session.flush()
    return len(fas)


def _apply_player_fields(player: Player, pdata: dict) -> None:
    """Update a Player ORM row from a parsed connector dict (idempotent)."""
    player.yahoo_player_id = pdata.get("yahoo_player_id") or 0
    player.full_name = pdata.get("full_name") or "Unknown"
    player.first_name = pdata.get("first_name")
    player.last_name = pdata.get("last_name")
    player.eligible_positions = pdata.get("eligible_positions") or []
    player.primary_position = pdata.get("primary_position")
    player.nba_team_abbr = pdata.get("nba_team_abbr")
    player.status = pdata.get("status")
    player.image_url = pdata.get("image_url")
