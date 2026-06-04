"""Fixture-driven parser tests.

Demonstrates the pattern every future parser test should follow:
hand-curated (or capture-script-generated) JSON fixture in
`tests/fixtures/<platform>/<kind>/<scenario>.json`, loaded by
`tests.fixtures.load_fixture`, fed to the extractor/parser under test.

The current fixtures are MINIMAL — they capture the subset of Yahoo's
response shape our extractors actually read. When `scripts/capture_fixture.py`
lands (the upcoming capture tool), these get replaced with full-shape
anonymized real responses.

For each fixture, we assert:
  1. The extractor produces non-empty output (no silent zeroing on
     a real-shape input — the canary scenario)
  2. Key values are exactly what the fixture declares (catches
     extractor drift)

Adding a new fixture is the cheapest way to add coverage — a single
JSON file + a single test function.
"""

from __future__ import annotations

import pytest

from app.engine.projection import (
    _extract_scored_stat_ids,
    _extract_stat_modifiers,
)
from tests.fixtures import load_fixture


# ---------------------------------------------------------------------------
# Yahoo league_settings fixtures
# ---------------------------------------------------------------------------


class TestYahooLeagueSettingsParsing:
    def test_points_league_modifiers_extracted(self) -> None:
        payload = load_fixture(
            "yahoo", "league_settings", "points_league_minimal.json"
        )
        modifiers = _extract_stat_modifiers(payload)
        # All 6 modifiers in the fixture should round-trip
        assert modifiers == {
            "12": 1.0,
            "15": 1.2,
            "16": 1.5,
            "17": 3.0,
            "18": 3.0,
            "19": -1.0,
        }

    def test_category_league_categories_extracted(self) -> None:
        payload = load_fixture(
            "yahoo", "league_settings", "category_league_minimal.json"
        )
        scored = _extract_scored_stat_ids(payload)
        # 9 real cats + 1 display-only that must be filtered out
        assert scored == {"12", "15", "16", "17", "18", "19", "10", "5", "8"}
        assert "9" not in scored, "display-only MIN must be filtered"

    def test_category_league_has_no_point_modifiers(self) -> None:
        """A category league shouldn't accidentally produce points
        modifiers — that would silently route through the wrong valuator.
        """
        payload = load_fixture(
            "yahoo", "league_settings", "category_league_minimal.json"
        )
        modifiers = _extract_stat_modifiers(payload)
        assert modifiers == {}


# ---------------------------------------------------------------------------
# Fixture-loader sanity
# ---------------------------------------------------------------------------


class TestFixtureLoader:
    def test_missing_fixture_raises_clear_error(self) -> None:
        with pytest.raises(FileNotFoundError, match="fixture not found"):
            load_fixture("yahoo", "league_settings", "does_not_exist.json")
