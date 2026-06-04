"""Integration tests for point-in-time roster reconstruction.

`roster_at(team_id, date)` replays draft + ownership events to compute
which players a team owned at end-of-day on a given date. This is the
single most-load-bearing service we have outside the projection engine
— every "what did my team look like on March 8" question routes through
it, including the My Team historical view, the League opponent drawer,
the agent's `get_team_roster_on_date` tool, and standings_at.

These are DB-integration tests and require a running Postgres. Mark:
    pytest.mark.db

Run locally with:
    docker compose up -d
    cd backend && pytest -m db -v

CI's pure-unit pass excludes these via `-m "not db"`. A future CI job
will spin up a Postgres service container and run them.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.db.models import (
    League,
    Player,
    PlayerOwnershipEvent,
    RosterPlayer,
    Team,
    User,
)
from app.services.roster_history import roster_at, roster_at_for_league

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Helpers — build a tiny synthetic league
# ---------------------------------------------------------------------------


async def _seed_minimal_league(db, *, num_teams: int = 2, num_players: int = 8):
    """Create one user, one league, N teams, M players. Returns the ORM objects.

    No events, no rosters — those get added per-test.
    """
    user = User(
        yahoo_guid="test-user-guid",
        access_token="dev",
        refresh_token="dev",
        token_expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    db.add(user)
    await db.flush()

    league = League(
        user_id=user.id,
        league_key="466.l.test",
        name="Test League",
        scoring_type="point",
        num_teams=num_teams,
        season="2025",
        settings_json={},
    )
    db.add(league)
    await db.flush()

    teams: list[Team] = []
    for i in range(num_teams):
        t = Team(
            league_id=league.id,
            team_key=f"466.l.test.t.{i + 1}",
            team_id_in_league=i + 1,
            name=f"Team {i + 1}",
            is_user_team=(i == 0),
        )
        db.add(t)
        teams.append(t)
    await db.flush()

    players: list[Player] = []
    for i in range(num_players):
        p = Player(
            yahoo_player_key=f"nba.p.{1000 + i}",
            yahoo_player_id=1000 + i,
            full_name=f"Player {i + 1}",
            eligible_positions=["PG"],
        )
        db.add(p)
        players.append(p)
    await db.flush()

    return league, teams, players


def _ts(d: date, hour: int = 12) -> datetime:
    """Build a UTC timestamp on a calendar date (default mid-day)."""
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRosterAt:
    async def test_empty_team_returns_empty_list(self, db_session) -> None:
        _, teams, _ = await _seed_minimal_league(db_session)
        result = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        # No events and the requested date is in the past (no fallback) →
        # empty roster, not an error.
        assert result == []

    async def test_unknown_team_returns_empty(self, db_session) -> None:
        # Don't seed anything — pass a team_id that doesn't exist.
        result = await roster_at(db_session, 9999, date(2026, 3, 15))
        assert result == []

    async def test_single_add_event_owns_player(self, db_session) -> None:
        league, teams, players = await _seed_minimal_league(db_session)
        db_session.add(
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[0].id,
                occurred_at=_ts(date(2026, 3, 1)),
                event_type="add",
                from_team_id=None,
                to_team_id=teams[0].id,
                transaction_key="add-1",
            )
        )
        await db_session.flush()

        result = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        assert [s.player_id for s in result] == [players[0].id]

    async def test_event_after_cutoff_is_ignored(self, db_session) -> None:
        """Events after the requested date must not count toward that date's roster."""
        league, teams, players = await _seed_minimal_league(db_session)
        db_session.add(
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[0].id,
                occurred_at=_ts(date(2026, 3, 20)),  # AFTER our query date
                event_type="add",
                from_team_id=None,
                to_team_id=teams[0].id,
                transaction_key="add-future",
            )
        )
        await db_session.flush()

        result = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        assert result == []

    async def test_add_then_drop_owns_nothing(self, db_session) -> None:
        league, teams, players = await _seed_minimal_league(db_session)
        db_session.add_all(
            [
                PlayerOwnershipEvent(
                    league_id=league.id,
                    player_id=players[0].id,
                    occurred_at=_ts(date(2026, 3, 1)),
                    event_type="add",
                    to_team_id=teams[0].id,
                    transaction_key="add-1",
                ),
                PlayerOwnershipEvent(
                    league_id=league.id,
                    player_id=players[0].id,
                    occurred_at=_ts(date(2026, 3, 10)),
                    event_type="drop",
                    from_team_id=teams[0].id,
                    transaction_key="drop-1",
                ),
            ]
        )
        await db_session.flush()

        result = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        assert result == []

    async def test_trade_moves_player_between_teams(self, db_session) -> None:
        """The exact bug the user surfaced: 'players on past dates were the
        players currently on my team, not the players who were on my team
        on that date.' This test guards against that regression.
        """
        league, teams, players = await _seed_minimal_league(db_session)
        # T1 owns the player from March 1
        db_session.add(
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[0].id,
                occurred_at=_ts(date(2026, 3, 1)),
                event_type="add",
                to_team_id=teams[0].id,
                transaction_key="add-1",
            )
        )
        # T1 trades the player to T2 on March 10
        db_session.add(
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[0].id,
                occurred_at=_ts(date(2026, 3, 10)),
                event_type="trade",
                from_team_id=teams[0].id,
                to_team_id=teams[1].id,
                transaction_key="trade-1",
            )
        )
        await db_session.flush()

        # On March 5: T1 owns, T2 does not
        t1_mar5 = await roster_at(db_session, teams[0].id, date(2026, 3, 5))
        t2_mar5 = await roster_at(db_session, teams[1].id, date(2026, 3, 5))
        assert [s.player_id for s in t1_mar5] == [players[0].id]
        assert t2_mar5 == []

        # On March 15: T2 owns, T1 does not
        t1_mar15 = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        t2_mar15 = await roster_at(db_session, teams[1].id, date(2026, 3, 15))
        assert t1_mar15 == []
        assert [s.player_id for s in t2_mar15] == [players[0].id]

    async def test_multiple_players_returns_all_currently_owned(
        self, db_session
    ) -> None:
        league, teams, players = await _seed_minimal_league(
            db_session, num_players=5
        )
        # T1 adds players 0, 1, 2 — drops player 1
        events = [
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[0].id,
                occurred_at=_ts(date(2026, 3, 1)),
                event_type="add",
                to_team_id=teams[0].id,
                transaction_key="a-0",
            ),
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[1].id,
                occurred_at=_ts(date(2026, 3, 2)),
                event_type="add",
                to_team_id=teams[0].id,
                transaction_key="a-1",
            ),
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[2].id,
                occurred_at=_ts(date(2026, 3, 3)),
                event_type="add",
                to_team_id=teams[0].id,
                transaction_key="a-2",
            ),
            PlayerOwnershipEvent(
                league_id=league.id,
                player_id=players[1].id,
                occurred_at=_ts(date(2026, 3, 8)),
                event_type="drop",
                from_team_id=teams[0].id,
                transaction_key="d-1",
            ),
        ]
        db_session.add_all(events)
        await db_session.flush()

        result = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        assert {s.player_id for s in result} == {players[0].id, players[2].id}

    async def test_today_fallback_to_roster_players_when_no_events(
        self, db_session, monkeypatch
    ) -> None:
        """Leagues that haven't been event-sourced yet should still show
        the current roster when the requested date is today.
        """
        from app.services import roster_history as rh

        league, teams, players = await _seed_minimal_league(db_session)
        # Seed a current roster row but NO events
        db_session.add(
            RosterPlayer(team_id=teams[0].id, player_id=players[0].id)
        )
        await db_session.flush()

        # Force resolve_today() to return our query date so the "today or
        # later" branch fires.
        monkeypatch.setattr(rh, "resolve_today", lambda: date(2026, 3, 15))

        result = await roster_at(db_session, teams[0].id, date(2026, 3, 15))
        assert [s.player_id for s in result] == [players[0].id]


class TestRosterAtForLeague:
    async def test_returns_one_entry_per_team(self, db_session) -> None:
        league, teams, _ = await _seed_minimal_league(
            db_session, num_teams=4
        )
        result = await roster_at_for_league(
            db_session, league.id, date(2026, 3, 15)
        )
        assert set(result.keys()) == {t.id for t in teams}
        assert all(r == [] for r in result.values())

    async def test_trade_reflected_in_both_team_rows(self, db_session) -> None:
        league, teams, players = await _seed_minimal_league(
            db_session, num_teams=2, num_players=3
        )
        db_session.add_all(
            [
                PlayerOwnershipEvent(
                    league_id=league.id,
                    player_id=players[0].id,
                    occurred_at=_ts(date(2026, 3, 1)),
                    event_type="add",
                    to_team_id=teams[0].id,
                    transaction_key="a-0",
                ),
                PlayerOwnershipEvent(
                    league_id=league.id,
                    player_id=players[0].id,
                    occurred_at=_ts(date(2026, 3, 10)),
                    event_type="trade",
                    from_team_id=teams[0].id,
                    to_team_id=teams[1].id,
                    transaction_key="t-0",
                ),
            ]
        )
        await db_session.flush()

        before = await roster_at_for_league(
            db_session, league.id, date(2026, 3, 5)
        )
        after = await roster_at_for_league(
            db_session, league.id, date(2026, 3, 15)
        )
        assert [s.player_id for s in before[teams[0].id]] == [players[0].id]
        assert after[teams[0].id] == []
        assert [s.player_id for s in after[teams[1].id]] == [players[0].id]
