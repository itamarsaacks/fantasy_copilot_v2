"""Test data factories — synthetic users / leagues / teams / players.

The factories let any DB-integration test set up a realistic league
state in one or two lines, eliminating ~80 lines of boilerplate per
test file. They produce ORM objects (via `db.add()` + `db.flush()`)
that are valid against every constraint our models declare.

Format coverage is first-class: `make_league(db, user, scoring_type=...)`
populates `settings_json` with the exact shape each scoring family
requires. The cat-league UX work, ESPN connector tests, and any
format-conditional eval cases can all spin up an arbitrary format
without joining a real Yahoo league.

Usage:

    async def test_something(db_session):
        user = await make_user(db_session)
        league = await make_league(db_session, user, scoring_type="head")
        team = await make_team(db_session, league, is_user_team=True)
        ...

All factories take **kwargs to override defaults — anything not
overridden uses a sensible default. Names use `f"Player {i}"` style
so duplicate factories in one test don't collide on unique constraints.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    League,
    Player,
    PlayerOwnershipEvent,
    PlayerStats,
    RosterPlayer,
    Team,
    User,
)

# Monotonic counter so factories don't collide on unique columns when
# multiple objects are created in one test.
_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


# ---------------------------------------------------------------------------
# Settings_json shapes — one per Yahoo scoring family
# ---------------------------------------------------------------------------

ScoringType = Literal[
    "point", "seasonpoint", "headpoint", "head", "headone", "roto"
]


_POINTS_MODIFIERS: dict[str, float] = {
    "12": 1.0,  # PTS
    "15": 1.2,  # REB
    "16": 1.5,  # AST
    "17": 3.0,  # ST
    "18": 3.0,  # BLK
    "19": -1.0,  # TO
}

_NINE_CAT_IDS: list[str] = ["12", "15", "16", "17", "18", "19", "10", "5", "8"]


def _settings_json_for(scoring_type: ScoringType) -> dict[str, Any]:
    """Realistic-shape Yahoo `settings_json` for the given scoring family.

    The shape mirrors what the projection valuator extractors expect
    (see app/engine/projection.py::_extract_stat_modifiers and
    _extract_scored_stat_ids). Connector contract tests can use these
    directly; UI tests can render the full SettingsCard.
    """
    common_extras = {
        "max_teams": 12,
        "waiver_type": "continual",
        "waiver_days": "2",
        "uses_faab": False,
        "uses_playoff": True,
        "trade_end_date": "2026-03-15",
        "max_games_played": 82,
        "is_highscore": False,
    }

    if scoring_type in {"point", "seasonpoint", "headpoint"}:
        return {
            **common_extras,
            "stat_modifiers": {
                "stats": [
                    {"stat": {"stat_id": int(sid), "value": str(v)}}
                    for sid, v in _POINTS_MODIFIERS.items()
                ]
            },
            "stat_categories": {
                "stats": [{"stat": {"stat_id": int(sid)}} for sid in _POINTS_MODIFIERS]
            },
        }

    # Category families: head / headone / roto
    return {
        **common_extras,
        "stat_modifiers": None,
        "stat_categories": {
            "stats": [
                *({"stat": {"stat_id": int(sid)}} for sid in _NINE_CAT_IDS),
                {"stat": {"stat_id": 9, "is_only_display_stat": "1"}},  # MIN
            ]
        },
    }


# ---------------------------------------------------------------------------
# Object factories
# ---------------------------------------------------------------------------


async def make_user(db: AsyncSession, **overrides: Any) -> User:
    """Synthetic User with valid OAuth state — token_expires_at in the future."""
    n = _next()
    defaults: dict[str, Any] = {
        "yahoo_guid": f"guid-{n}",
        "display_name": f"User {n}",
        "access_token": f"access-{n}",
        "refresh_token": f"refresh-{n}",
        "token_expires_at": datetime(2030, 1, 1, tzinfo=timezone.utc),
    }
    user = User(**{**defaults, **overrides})
    db.add(user)
    await db.flush()
    return user


async def make_league(
    db: AsyncSession,
    user: User,
    *,
    scoring_type: ScoringType = "point",
    **overrides: Any,
) -> League:
    """Synthetic League with realistic settings_json for the given scoring type."""
    n = _next()
    defaults: dict[str, Any] = {
        "user_id": user.id,
        "league_key": f"466.l.{n:06d}",
        "name": f"Test League {n}",
        "scoring_type": scoring_type,
        "num_teams": 12,
        "current_week": 20,
        "season": "2025",
        "settings_json": _settings_json_for(scoring_type),
    }
    league = League(**{**defaults, **overrides})
    db.add(league)
    await db.flush()
    return league


async def make_team(
    db: AsyncSession,
    league: League,
    *,
    is_user_team: bool = False,
    **overrides: Any,
) -> Team:
    """Synthetic Team. Pair with `make_league` first."""
    n = _next()
    defaults: dict[str, Any] = {
        "league_id": league.id,
        "team_key": f"{league.league_key}.t.{n}",
        "team_id_in_league": n,
        "name": f"Team {n}",
        "manager_name": f"Manager {n}",
        "is_user_team": is_user_team,
        "rank": 1 if is_user_team else 2,
        "wins": 10,
        "losses": 5,
    }
    team = Team(**{**defaults, **overrides})
    db.add(team)
    await db.flush()
    return team


async def make_player(
    db: AsyncSession,
    *,
    with_season_stats: bool = False,
    **overrides: Any,
) -> Player:
    """Synthetic Player; optionally seed season-scope stats."""
    n = _next()
    defaults: dict[str, Any] = {
        "yahoo_player_key": f"nba.p.{1000 + n}",
        "yahoo_player_id": 1000 + n,
        "full_name": f"Player {n}",
        "first_name": "Player",
        "last_name": str(n),
        "eligible_positions": ["PG"],
        "primary_position": "PG",
        "nba_team_abbr": "LAL",
    }
    player = Player(**{**defaults, **overrides})
    db.add(player)
    await db.flush()

    if with_season_stats:
        # A representative star line — enough that the projection
        # valuator returns a non-trivial score in any format.
        #
        # `league_key` is required by the model but the projection engine
        # ignores it (stats are league-independent raw NBA values now);
        # use a sentinel so the NOT NULL constraint is satisfied.
        sample = {
            "0": 70,  # GP
            "12": 1800,  # PTS
            "15": 560,  # REB
            "16": 580,  # AST
            "17": 90,  # ST
            "18": 50,  # BLK
            "19": 280,  # TO
            "10": 200,  # 3PTM
        }
        for stat_id, value in sample.items():
            db.add(
                PlayerStats(
                    player_id=player.id,
                    league_key="nba.global",
                    stat_id=stat_id,
                    value=value,
                    scope="season",
                    as_of_date=datetime(2026, 3, 15, tzinfo=timezone.utc).date(),
                )
            )
        await db.flush()
    return player


async def make_roster_entry(
    db: AsyncSession,
    team: Team,
    player: Player,
    *,
    selected_position: str | None = "PG",
) -> RosterPlayer:
    """Add `player` to `team`'s current roster (snapshot row)."""
    rp = RosterPlayer(
        team_id=team.id,
        player_id=player.id,
        selected_position=selected_position,
    )
    db.add(rp)
    await db.flush()
    return rp


async def make_ownership_event(
    db: AsyncSession,
    league: League,
    player: Player,
    *,
    occurred_at: datetime,
    event_type: Literal["add", "drop", "trade", "draft"] = "add",
    from_team: Team | None = None,
    to_team: Team | None = None,
    transaction_key: str | None = None,
) -> PlayerOwnershipEvent:
    """One add/drop/trade/draft event — the input to `roster_at` replay."""
    n = _next()
    ev = PlayerOwnershipEvent(
        league_id=league.id,
        player_id=player.id,
        occurred_at=occurred_at,
        event_type=event_type,
        from_team_id=from_team.id if from_team else None,
        to_team_id=to_team.id if to_team else None,
        transaction_key=transaction_key or f"tx-{n}",
    )
    db.add(ev)
    await db.flush()
    return ev


# ---------------------------------------------------------------------------
# Convenience composers
# ---------------------------------------------------------------------------


async def make_full_league(
    db: AsyncSession,
    *,
    scoring_type: ScoringType = "point",
    num_teams: int = 4,
    players_per_team: int = 3,
) -> tuple[League, list[Team], list[Player]]:
    """One-call setup: user + league + N teams + M players each.

    Useful for connector contract tests, agent eval-lite cases, and
    anywhere you need a populated league without 30 lines of factory
    calls. Returns the league, the teams list, and the flat players list.
    """
    user = await make_user(db)
    league = await make_league(db, user, scoring_type=scoring_type, num_teams=num_teams)
    teams = [
        await make_team(db, league, is_user_team=(i == 0))
        for i in range(num_teams)
    ]
    players: list[Player] = []
    for team in teams:
        for _ in range(players_per_team):
            p = await make_player(db, with_season_stats=True)
            await make_roster_entry(db, team, p)
            players.append(p)
    return league, teams, players
