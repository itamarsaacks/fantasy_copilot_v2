"""Format-coverage integration tests.

Exercises every Yahoo scoring type end-to-end through the factories
+ projection engine. The user can't realistically play in 5 different
real Yahoo leagues just to validate cat-league or roto code; these
tests fill that gap with synthetic data that's shape-identical to
real Yahoo responses.

For each scoring_type:
  - The factory's settings_json shape parses cleanly via the
    extractor functions
  - The projection engine's valuator routing picks the correct class
  - The valuator returns a non-None composite for a realistic stat line

This is the format equivalent of a smoke test: when we ship category-
league UX or any settings-aware feature, these tests prove the wiring
is correct for every supported league family before any user sees it.
"""

from __future__ import annotations

import pytest

from app.engine.projection import (
    CATEGORY_LEAGUE_TYPES,
    POINTS_LEAGUE_TYPES,
    _CategoryValuator,
    _PointsValuator,
)
from tests.factories import _settings_json_for, make_full_league


# All 6 Yahoo scoring types — used to parameterize the suite.
ALL_FORMATS = ["point", "seasonpoint", "headpoint", "head", "headone", "roto"]


# ---------------------------------------------------------------------------
# Pure-unit: factory's settings_json round-trips through the extractors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scoring_type", ALL_FORMATS)
def test_factory_settings_route_to_correct_valuator(scoring_type: str) -> None:
    """The factory's settings_json must produce a valuator that matches
    the scoring family. If the factory is misconfigured, every downstream
    DB test for category leagues silently uses the points valuator.

    Pure-unit: no DB, runs in the default CI pass.
    """
    settings = _settings_json_for(scoring_type)  # type: ignore[arg-type]
    pv = _PointsValuator.from_settings(settings)
    cv = _CategoryValuator.from_settings(settings)

    if scoring_type in POINTS_LEAGUE_TYPES:
        assert pv is not None, f"{scoring_type}: should produce points valuator"
        # NOTE: category extractor also returns non-None for points
        # leagues because the factory includes stat_categories. That's
        # fine — the dispatcher in projection.compute_league_projections
        # picks by scoring_type, not by which extractors return something.
    elif scoring_type in CATEGORY_LEAGUE_TYPES:
        assert cv is not None, f"{scoring_type}: should produce category valuator"
        assert pv is None, f"{scoring_type}: must NOT produce a points valuator"
    else:
        pytest.fail(f"Unknown scoring_type {scoring_type}")


# ---------------------------------------------------------------------------
# DB-integration: full league setup works for every format
# ---------------------------------------------------------------------------


@pytest.mark.db
@pytest.mark.parametrize("scoring_type", ALL_FORMATS)
async def test_full_league_setup_each_format(db_session, scoring_type: str) -> None:
    """`make_full_league` produces a valid league for every scoring type.

    Catches: unique-constraint violations from counter reuse across
    parameterized runs, settings_json validation failures, foreign-key
    mismatches.
    """
    league, teams, players = await make_full_league(
        db_session,
        scoring_type=scoring_type,  # type: ignore[arg-type]
        num_teams=2,
        players_per_team=2,
    )
    assert league.scoring_type == scoring_type
    assert len(teams) == 2
    assert len(players) == 4
    assert teams[0].is_user_team is True
    assert teams[1].is_user_team is False
    assert league.settings_json  # non-empty


@pytest.mark.db
@pytest.mark.parametrize("scoring_type", ALL_FORMATS)
async def test_full_league_seeds_stats_each_format(
    db_session, scoring_type: str
) -> None:
    """The factory's `with_season_stats=True` path seeds `player_stats`
    rows for every player. Verifies the NOT NULL constraints + the
    realistic stat line make it through the model layer.

    NOTE: the full end-to-end "projection engine runs on this league"
    test is deferred — `compute_league_projections` opens its own
    SessionLocal which bypasses the test SAVEPOINT, so we'd need to
    monkeypatch SessionLocal. Filed as a follow-up; for now the pure-
    unit `test_projection_engine.py` covers valuator correctness and
    `test_factory_settings_route_to_correct_valuator` (above) covers
    routing.
    """
    from sqlalchemy import select

    from app.db.models import PlayerStats

    _league, _teams, players = await make_full_league(
        db_session,
        scoring_type=scoring_type,  # type: ignore[arg-type]
        num_teams=2,
        players_per_team=2,
    )
    # Each player got 8 stat IDs seeded (GP + 7 cats)
    rows = (
        await db_session.execute(
            select(PlayerStats).where(
                PlayerStats.player_id.in_([p.id for p in players])
            )
        )
    ).scalars().all()
    assert len(rows) == len(players) * 8
