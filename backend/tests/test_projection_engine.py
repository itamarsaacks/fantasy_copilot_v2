"""Tests for the projection engine valuators.

The valuators (_PointsValuator, _CategoryValuator) are the load-bearing
math that drives every quantitative claim the app makes — chat answers,
trade verdicts, waiver rankings, leaderboards. A regression here is
silent because nothing crashes; numbers just get subtly wrong.

These tests LOCK IN current behavior. When we later replace the MVP
composite category score with real z-scores (see
backend/app/engine/projection.py docstring + docs/plans/league-formats.md),
the category-composite assertions in this file will fail loudly and
intentionally — at that point we'll update them with the new expected
values.

The settings-extractor tests pin the exact Yahoo JSON shape we parse,
because Yahoo occasionally adjusts the wrapper structure and a silent
breakage there zeroes out every projection in the league.

All tests here are pure-Python (no DB, no network) — they're in the
default pytest run and gate every PR.
"""

from __future__ import annotations

import pytest

from app.engine.projection import (
    CATEGORY_LEAGUE_TYPES,
    INVERSE_STATS,
    POINTS_LEAGUE_TYPES,
    _CategoryValuator,
    _extract_scored_stat_ids,
    _extract_stat_modifiers,
    _PointsValuator,
)


# ---------------------------------------------------------------------------
# Fixture data — minimal but realistic Yahoo NBA settings shape
# ---------------------------------------------------------------------------

# Yahoo NBA stat IDs (the ones we care about for these tests):
#   "0"  = Games Played
#   "12" = Points
#   "15" = Rebounds
#   "16" = Assists
#   "17" = Steals
#   "18" = Blocks
#   "19" = Turnovers   (inverse-scored in category leagues)

POINTS_SETTINGS = {
    "stat_modifiers": {
        "stats": [
            {"stat": {"stat_id": 12, "value": "1"}},      # PTS = 1.0
            {"stat": {"stat_id": 15, "value": "1.2"}},    # REB = 1.2
            {"stat": {"stat_id": 16, "value": "1.5"}},    # AST = 1.5
            {"stat": {"stat_id": 17, "value": "3"}},      # ST  = 3.0
            {"stat": {"stat_id": 18, "value": "3"}},      # BLK = 3.0
            {"stat": {"stat_id": 19, "value": "-1"}},     # TO  = -1.0
        ]
    }
}

# Category league settings — 6-cat for compactness (real Yahoo is 9-cat)
CATEGORY_SETTINGS = {
    "stat_categories": {
        "stats": [
            {"stat": {"stat_id": 12, "name": "PTS"}},
            {"stat": {"stat_id": 15, "name": "REB"}},
            {"stat": {"stat_id": 16, "name": "AST"}},
            {"stat": {"stat_id": 17, "name": "ST"}},
            {"stat": {"stat_id": 18, "name": "BLK"}},
            {"stat": {"stat_id": 19, "name": "TO"}},
            # Display-only stats are filtered out (e.g. minutes)
            {"stat": {"stat_id": 9, "name": "MIN", "is_only_display_stat": "1"}},
        ]
    }
}

# A representative star player's raw season totals
LEBRON_STATS = {
    "0": 70.0,    # GP
    "12": 1800.0, # PTS
    "15": 560.0,  # REB
    "16": 580.0,  # AST
    "17": 90.0,   # ST
    "18": 50.0,   # BLK
    "19": 280.0,  # TO
}


# ---------------------------------------------------------------------------
# Scoring-type set integrity
# ---------------------------------------------------------------------------


def test_inverse_stats_contains_turnovers() -> None:
    """TO is stat_id '19' in Yahoo. If this drifts we silently treat TO
    as a counting-good stat in category leagues — every cat-league ranking
    would invert.
    """
    assert "19" in INVERSE_STATS


def test_scoring_type_sets_are_disjoint() -> None:
    assert not (POINTS_LEAGUE_TYPES & CATEGORY_LEAGUE_TYPES)


# ---------------------------------------------------------------------------
# Settings extractors — the seam against Yahoo's JSON shape
# ---------------------------------------------------------------------------


class TestExtractStatModifiers:
    def test_parses_real_yahoo_shape(self) -> None:
        m = _extract_stat_modifiers(POINTS_SETTINGS)
        assert m == {"12": 1.0, "15": 1.2, "16": 1.5, "17": 3.0, "18": 3.0, "19": -1.0}

    def test_empty_settings_returns_empty(self) -> None:
        assert _extract_stat_modifiers({}) == {}

    def test_none_returns_empty(self) -> None:
        # Some legacy League rows might have settings_json = None or non-dict
        assert _extract_stat_modifiers(None) == {}  # type: ignore[arg-type]
        assert _extract_stat_modifiers("not a dict") == {}  # type: ignore[arg-type]

    def test_missing_stat_modifiers_key_returns_empty(self) -> None:
        assert _extract_stat_modifiers({"unrelated": 123}) == {}

    def test_skips_invalid_value_strings(self) -> None:
        # Yahoo has historically sent "Infinity" or "" for some modifiers
        bad = {
            "stat_modifiers": {
                "stats": [
                    {"stat": {"stat_id": 12, "value": "Infinity"}},
                    {"stat": {"stat_id": 15, "value": ""}},
                    {"stat": {"stat_id": 16, "value": "1.5"}},
                ]
            }
        }
        m = _extract_stat_modifiers(bad)
        # "Infinity" parses as float('inf') — currently kept. "" skipped.
        # Documenting current behavior: 15 is skipped (empty), 16 is kept.
        # If 12=inf becomes a problem we add explicit filtering.
        assert "15" not in m  # empty string skipped
        assert m.get("16") == 1.5


class TestExtractScoredStatIds:
    def test_parses_real_yahoo_shape(self) -> None:
        ids = _extract_scored_stat_ids(CATEGORY_SETTINGS)
        # Display-only stat_id 9 must be filtered out
        assert ids == {"12", "15", "16", "17", "18", "19"}

    def test_filters_is_only_display_stat(self) -> None:
        s = {
            "stat_categories": {
                "stats": [
                    {"stat": {"stat_id": 12}},
                    {"stat": {"stat_id": 9, "is_only_display_stat": "1"}},
                ]
            }
        }
        assert _extract_scored_stat_ids(s) == {"12"}

    def test_empty_and_invalid_settings(self) -> None:
        assert _extract_scored_stat_ids({}) == set()
        assert _extract_scored_stat_ids(None) == set()  # type: ignore[arg-type]
        assert _extract_scored_stat_ids({"stat_categories": []}) == set()


# ---------------------------------------------------------------------------
# Points valuator
# ---------------------------------------------------------------------------


class TestPointsValuator:
    @pytest.fixture
    def valuator(self) -> _PointsValuator:
        v = _PointsValuator.from_settings(POINTS_SETTINGS)
        assert v is not None, "fixture settings should parse cleanly"
        return v

    def test_from_settings_returns_none_when_no_modifiers(self) -> None:
        assert _PointsValuator.from_settings({}) is None

    def test_season_total_lebron(self, valuator: _PointsValuator) -> None:
        # Hand-computed expected:
        #   1800*1 + 560*1.2 + 580*1.5 + 90*3 + 50*3 + 280*(-1)
        # = 1800 + 672 + 870 + 270 + 150 - 280
        # = 3482.0
        total, components = valuator.season_total(LEBRON_STATS)
        assert total == pytest.approx(3482.0)
        # Components round to 2 decimals per engine code (line 219)
        assert components["12"] == pytest.approx(1800.0)
        assert components["19"] == pytest.approx(-280.0)
        # GP is not in modifiers, so not in components
        assert "0" not in components

    def test_per_game_lebron(self, valuator: _PointsValuator) -> None:
        # per_game = season_total / GP, with rounding at component level
        # 3482.0 / 70 ≈ 49.74285...
        pg, components = valuator.per_game(LEBRON_STATS, gp=70.0)
        assert pg == pytest.approx(3482.0 / 70.0, rel=1e-3)
        # PTS per game ≈ 25.714
        assert components["12"] == pytest.approx(25.714, abs=0.01)
        # TO per-game contribution is negative
        assert components["19"] < 0

    def test_season_total_returns_none_when_no_overlap(
        self, valuator: _PointsValuator
    ) -> None:
        # Stats dict has only stat_ids that aren't in modifiers
        stats = {"99": 100.0, "98": 50.0}
        total, components = valuator.season_total(stats)
        assert total is None
        assert components == {}

    def test_per_game_returns_none_when_gp_below_one(
        self, valuator: _PointsValuator
    ) -> None:
        pg, components = valuator.per_game(LEBRON_STATS, gp=0.0)
        assert pg is None
        assert components == {}

    def test_skips_stats_with_none_value(self, valuator: _PointsValuator) -> None:
        stats = {"12": None, "15": 100.0}  # type: ignore[dict-item]
        total, components = valuator.season_total(stats)
        # Should ignore the None and use only REB
        assert total == pytest.approx(120.0)
        assert "12" not in components


# ---------------------------------------------------------------------------
# Category valuator  (MVP composite — will be replaced by z-scores)
# ---------------------------------------------------------------------------


class TestCategoryValuator:
    """Locks in current MVP composite behavior. When we ship z-scores,
    these assertions will fail in known places — rewrite then.
    """

    @pytest.fixture
    def valuator(self) -> _CategoryValuator:
        v = _CategoryValuator.from_settings(CATEGORY_SETTINGS)
        assert v is not None, "fixture settings should parse cleanly"
        return v

    def test_from_settings_returns_none_when_no_categories(self) -> None:
        assert _CategoryValuator.from_settings({}) is None

    def test_season_total_to_sign_flipped(self, valuator: _CategoryValuator) -> None:
        # Current MVP: sum of (sign * stat_value), TO sign-flipped.
        # 1800 + 560 + 580 + 90 + 50 + (-280) = 2800.0
        total, components = valuator.season_total(LEBRON_STATS)
        assert total == pytest.approx(2800.0)
        # Components hold raw per-cat values, NOT sign-flipped
        assert components["12"] == pytest.approx(1800.0)
        assert components["19"] == pytest.approx(280.0)  # raw value, no flip
        # GP not in scored set
        assert "0" not in components

    def test_per_game_to_sign_flipped(self, valuator: _CategoryValuator) -> None:
        # Per-game composite:
        #   (1800+560+580+90+50)/70 - 280/70
        # = 3080/70 - 4.0 = 44.0 - 4.0 = 40.0
        pg, components = valuator.per_game(LEBRON_STATS, gp=70.0)
        assert pg == pytest.approx(40.0, abs=0.01)
        # Component for TO is raw per-game (positive), not the sign-flipped value
        assert components["19"] == pytest.approx(4.0, abs=0.01)

    def test_display_only_stats_excluded(self, valuator: _CategoryValuator) -> None:
        # If LeBron's stats dict had a value for stat_id "9" (minutes),
        # the valuator should ignore it because we marked it display-only.
        stats_with_minutes = {**LEBRON_STATS, "9": 2500.0}
        total, components = valuator.season_total(stats_with_minutes)
        assert "9" not in components
        # Total should equal the no-minutes case
        baseline, _ = valuator.season_total(LEBRON_STATS)
        assert total == pytest.approx(baseline)

    def test_season_total_returns_none_when_no_overlap(
        self, valuator: _CategoryValuator
    ) -> None:
        total, components = valuator.season_total({"99": 100.0})
        assert total is None
        assert components == {}

    def test_per_game_returns_none_when_gp_below_one(
        self, valuator: _CategoryValuator
    ) -> None:
        pg, _ = valuator.per_game(LEBRON_STATS, gp=0.0)
        assert pg is None


# ---------------------------------------------------------------------------
# Cross-type integrity
# ---------------------------------------------------------------------------


def test_points_and_category_valuators_disagree_for_same_player() -> None:
    """Same raw stats should produce different composite scores in a
    points league vs a category league. If they're identical, something
    is broken in the routing or one valuator is silently no-op'd.
    """
    pv = _PointsValuator.from_settings(POINTS_SETTINGS)
    cv = _CategoryValuator.from_settings(CATEGORY_SETTINGS)
    assert pv is not None and cv is not None
    p_total, _ = pv.season_total(LEBRON_STATS)
    c_total, _ = cv.season_total(LEBRON_STATS)
    assert p_total != c_total
