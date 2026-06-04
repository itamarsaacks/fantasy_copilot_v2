"""Trivial smoke-tests to prove the pytest scaffold loads.

These exist so CI has a real test command to run from day one. Real
service-level tests land in subsequent files; this one just verifies the
test environment + imports + scoring-type constants haven't drifted.

Add more tests next to this file — pytest discovers `test_*.py` under
`backend/tests/` per pyproject.toml [tool.pytest.ini_options].
"""

from __future__ import annotations


def test_pytest_runs() -> None:
    """The most basic possible test — proves the runner works."""
    assert 1 + 1 == 2


def test_app_imports() -> None:
    """All critical modules import without side-effect errors."""
    from app.agent import prompts as _prompts  # noqa: F401
    from app.engine import projection as _projection  # noqa: F401
    from app.services import clock as _clock  # noqa: F401


def test_scoring_type_sets_cover_all_yahoo_formats() -> None:
    """All 5 Yahoo NBA league formats route through projection valuators.

    Locks in the league-formats reformation: when a new Yahoo format is
    added, this test fails until it is consciously assigned to points or
    categories. Prevents silent fallthrough.
    """
    from app.engine.projection import (
        CATEGORY_LEAGUE_TYPES,
        POINTS_LEAGUE_TYPES,
    )

    yahoo_formats = {"point", "seasonpoint", "headpoint", "head", "headone", "roto"}
    covered = POINTS_LEAGUE_TYPES | CATEGORY_LEAGUE_TYPES
    missing = yahoo_formats - covered
    assert not missing, f"Yahoo formats not routed to a valuator: {missing}"


def test_scoring_type_sets_are_disjoint() -> None:
    """A scoring type cannot be both points and category — that would be
    ambiguous routing and is almost certainly a copy-paste bug.
    """
    from app.engine.projection import (
        CATEGORY_LEAGUE_TYPES,
        POINTS_LEAGUE_TYPES,
    )

    overlap = POINTS_LEAGUE_TYPES & CATEGORY_LEAGUE_TYPES
    assert not overlap, f"scoring_type in both sets: {overlap}"


def test_scoring_type_notes_cover_all_formats() -> None:
    """Agent system-prompt notes must exist for every routed format.

    Without a note, the agent falls back to generic 'treat as H2H points'
    advice — incorrect for cat/roto/one-win/season-points users.
    """
    from app.agent.prompts import SCORING_TYPE_NOTES
    from app.engine.projection import CATEGORY_LEAGUE_TYPES, POINTS_LEAGUE_TYPES

    all_formats = POINTS_LEAGUE_TYPES | CATEGORY_LEAGUE_TYPES
    missing = all_formats - set(SCORING_TYPE_NOTES.keys())
    assert not missing, f"SCORING_TYPE_NOTES missing entries: {missing}"
