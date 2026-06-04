"""Connector contract tests.

These tests target the Connector Protocol (`app/connectors/base.py`)
itself — invariants every implementation must respect. They run today
without any concrete connector being live, because they check the
shape and constraint surface, not behavior against a real platform.

When ESPN and Sleeper connectors land, each will get its own
`tests/test_connectors/test_<platform>.py` file with fixture-driven
behavioral tests. This file remains the shared contract.

What's locked in here:
  - Allowed scoring_type values match the projection engine's
    POINTS_LEAGUE_TYPES ∪ CATEGORY_LEAGUE_TYPES exactly
  - The Protocol exposes exactly the 7 fetch methods we depend on
  - Normalized dataclasses are frozen (we treat them as values)
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields

import pytest

from app.connectors import base


# ---------------------------------------------------------------------------
# scoring_type allow-list — must match the projection engine exactly
# ---------------------------------------------------------------------------


def test_league_meta_scoring_type_matches_projection_engine() -> None:
    """The Literal in LeagueMeta.scoring_type and the (POINTS ∪ CATEGORY)
    sets in projection.py must agree. If they drift, a connector could
    populate a scoring_type that the engine refuses to route — silently
    breaking projections for that league.
    """
    from typing import get_args

    from app.engine.projection import CATEGORY_LEAGUE_TYPES, POINTS_LEAGUE_TYPES

    # Pull the Literal values out of the LeagueMeta annotation
    league_meta_annotation = base.LeagueMeta.__dataclass_fields__["scoring_type"].type
    # In Python 3.12+ field.type is a string when from __future__ import
    # annotations is used; we resolve it via get_type_hints
    from typing import get_type_hints

    hints = get_type_hints(base.LeagueMeta)
    allowed = set(get_args(hints["scoring_type"]))
    engine_allowed = POINTS_LEAGUE_TYPES | CATEGORY_LEAGUE_TYPES
    assert allowed == engine_allowed, (
        f"LeagueMeta.scoring_type Literal ({allowed}) drifted from "
        f"projection engine routing ({engine_allowed}). "
        f"Diff: only in Literal={allowed - engine_allowed}, "
        f"only in engine={engine_allowed - allowed}"
    )


# ---------------------------------------------------------------------------
# Protocol surface — exactly seven fetch methods, all async
# ---------------------------------------------------------------------------


REQUIRED_METHODS = {
    "fetch_league_meta",
    "fetch_scoring_rules",
    "fetch_roster_slots",
    "fetch_settings_extras",
    "fetch_teams",
    "fetch_current_rosters",
    "fetch_transactions",
}


def test_connector_protocol_has_exactly_required_methods() -> None:
    """Adding methods to the Connector Protocol is a design decision —
    each one increases the surface every adapter must implement. This
    test fails when methods are added without updating REQUIRED_METHODS
    here, forcing a conscious review.
    """
    public_methods = {
        name
        for name, value in inspect.getmembers(base.Connector)
        if callable(value) and not name.startswith("_")
    }
    assert public_methods == REQUIRED_METHODS, (
        f"Connector Protocol surface changed. "
        f"New methods: {public_methods - REQUIRED_METHODS}. "
        f"Removed: {REQUIRED_METHODS - public_methods}."
    )


def test_all_protocol_methods_are_async() -> None:
    """A non-async method on the Connector Protocol is almost certainly
    a bug — every implementation will hit network.
    """
    for name in REQUIRED_METHODS:
        method = getattr(base.Connector, name)
        assert inspect.iscoroutinefunction(method), (
            f"Connector.{name} must be async (def + await network call)"
        )


# ---------------------------------------------------------------------------
# Normalized dataclasses — frozen, hashable where applicable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [
        base.LeagueMeta,
        base.ScoringRule,
        base.RosterSlotDef,
        base.LeagueSettingsExtras,
        base.TeamInfo,
        base.OwnershipEvent,
    ],
)
def test_normalized_dataclasses_are_frozen(cls: type) -> None:
    """Frozen dataclasses prevent accidental mutation of values we
    pass through the system. A mutated normalized struct would be hard
    to track because it could happen anywhere downstream.
    """
    # Build a dummy instance with default-ish values
    kwargs = {}
    for f in fields(cls):
        type_ = f.type if isinstance(f.type, type) else None
        if type_ is str:
            kwargs[f.name] = "x"
        elif type_ is int:
            kwargs[f.name] = 0
        elif type_ is bool:
            kwargs[f.name] = False
        else:
            kwargs[f.name] = None  # Optional / unioned types
    # The dataclasses use future-annotations so the simple type check
    # above misses Literal/Optional fields. Just try the constructor;
    # if it fails, supply None for everything as a fallback.
    try:
        inst = cls(**kwargs)
    except TypeError:
        inst = cls(**{f.name: None for f in fields(cls)})
    # Pick the first field and try to mutate; frozen=True must raise
    first_field = fields(cls)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(inst, first_field, "mutated")
