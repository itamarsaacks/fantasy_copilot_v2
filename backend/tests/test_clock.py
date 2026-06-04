"""Tests for the resolve_today() chokepoint.

Every place in the app that asks "what day is it" calls resolve_today().
A regression here is catastrophic for off-season replay testing — the
whole app would silently fall back to real-world today (June 4, 2026 at
time of writing — an off-season day with no fantasy games), making
nothing testable until the season starts.

These tests do NOT touch the real `app.config.get_settings()` lru_cache.
Instead they monkeypatch `app.services.clock.get_settings` to return a
fake settings object with the attributes we want. This is faster and
more isolated than env-var juggling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest

from app.services import clock


@dataclass
class _FakeSettings:
    """Minimal stand-in for app.config.Settings — only the fields clock reads."""

    app_mode: str = "live"
    as_of_date: date | None = None


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: _FakeSettings) -> None:
    """Replace clock.get_settings with a lambda returning our fake settings."""
    monkeypatch.setattr(clock, "get_settings", lambda: settings)


# ---------------------------------------------------------------------------
# resolve_today
# ---------------------------------------------------------------------------


class TestResolveToday:
    def test_live_mode_returns_real_utc_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, _FakeSettings(app_mode="live"))
        result = clock.resolve_today()
        # We can't pin the exact date (it changes daily), so we sanity-check
        # against the real UTC date computed inline. Window of 1 day to
        # tolerate a UTC midnight crossing during the test.
        real_today = datetime.now(timezone.utc).date()
        delta_days = abs((result - real_today).days)
        assert delta_days <= 1, (
            f"live-mode resolve_today() returned {result}, expected ~{real_today}"
        )

    def test_replay_mode_returns_as_of_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = date(2026, 3, 15)
        _patch_settings(
            monkeypatch, _FakeSettings(app_mode="replay", as_of_date=seeded)
        )
        assert clock.resolve_today() == seeded

    def test_replay_mode_without_as_of_date_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Misconfiguration must fail loudly, not silently fall back to today."""
        _patch_settings(
            monkeypatch, _FakeSettings(app_mode="replay", as_of_date=None)
        )
        with pytest.raises(RuntimeError, match="AS_OF_DATE"):
            clock.resolve_today()

    def test_replay_mode_returns_seeded_date_not_real_today(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole POINT of replay mode is that resolve_today() != today.
        If they're ever equal in a test we'd silently get false confidence.
        """
        seeded = date(2024, 1, 1)  # picked far from any real-world today
        _patch_settings(
            monkeypatch, _FakeSettings(app_mode="replay", as_of_date=seeded)
        )
        real_today = datetime.now(timezone.utc).date()
        assert clock.resolve_today() != real_today


# ---------------------------------------------------------------------------
# is_replay_mode
# ---------------------------------------------------------------------------


class TestIsReplayMode:
    def test_live(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, _FakeSettings(app_mode="live"))
        assert clock.is_replay_mode() is False

    def test_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(
            monkeypatch,
            _FakeSettings(app_mode="replay", as_of_date=date(2026, 3, 15)),
        )
        assert clock.is_replay_mode() is True
