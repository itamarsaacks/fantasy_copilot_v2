"""Tests for the feature flag system.

Locks two invariants:
  1. Every Feature enum member maps to a real Settings field.
     If they drift, `is_enabled()` silently returns False — bug class
     where a flag-flip in env doesn't actually enable anything.
  2. Flag defaults are OFF. Forgetting to default-disable a new flag
     would ship incomplete code at the next release without a flip.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app import features
from app.config import Settings
from app.features import Feature, is_enabled


def test_every_feature_enum_has_matching_settings_field() -> None:
    """Each Feature.X must correspond to Settings.feature_x (lowercase).

    Without this guard, `is_enabled(Feature.NEW_THING)` reads a
    non-existent attribute and returns False forever.
    """
    settings = Settings()
    for f in Feature:
        attr = f"feature_{f.value}"
        assert hasattr(settings, attr), (
            f"Feature.{f.name} has no matching Settings.{attr} field. "
            f"Add `{attr}: bool = False` to Settings in app/config.py."
        )


def test_all_feature_defaults_are_false() -> None:
    """A feature flag added without explicit default would ship enabled.

    Catches the bug-class: developer adds `feature_x: bool` (no default,
    pydantic-settings makes it required) OR `feature_x: bool = True`
    (a footgun for shipping unfinished work).
    """
    settings = Settings()
    for f in Feature:
        attr = f"feature_{f.value}"
        assert getattr(settings, attr) is False, (
            f"Feature.{f.name} defaults to True. New flags must default "
            f"OFF — set `{attr}: bool = False` in app/config.py."
        )


# ---------------------------------------------------------------------------
# is_enabled — toggles via monkeypatched settings
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettings:
    feature_espn_connector: bool = False
    feature_sleeper_connector: bool = False
    feature_category_league_ux: bool = False
    feature_billing: bool = False


@pytest.fixture
def patched_features(monkeypatch: pytest.MonkeyPatch):
    """Replace features.get_settings with a fake we can mutate per-test."""
    fake = _FakeSettings()
    monkeypatch.setattr(features, "get_settings", lambda: fake)
    return fake


class TestIsEnabled:
    def test_default_is_off(self, patched_features: _FakeSettings) -> None:
        for f in Feature:
            assert is_enabled(f) is False

    def test_flipping_one_flag_doesnt_affect_others(
        self, patched_features: _FakeSettings
    ) -> None:
        patched_features.feature_espn_connector = True
        assert is_enabled(Feature.ESPN_CONNECTOR) is True
        assert is_enabled(Feature.SLEEPER_CONNECTOR) is False
        assert is_enabled(Feature.CATEGORY_LEAGUE_UX) is False
        assert is_enabled(Feature.BILLING) is False

    def test_enabled_features_returns_only_on_flags(
        self, patched_features: _FakeSettings
    ) -> None:
        patched_features.feature_espn_connector = True
        patched_features.feature_billing = True
        assert features.enabled_features() == {Feature.ESPN_CONNECTOR, Feature.BILLING}
