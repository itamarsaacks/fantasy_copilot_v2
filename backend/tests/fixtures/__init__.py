"""Fixture loader.

Tiny helper so tests don't repeat path/JSON boilerplate. Provides a
clear error if a fixture file is missing (so a renamed/dropped fixture
shows up as "fixture not found at <path>" instead of a generic
FileNotFoundError mid-test).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_ROOT = Path(__file__).resolve().parent


def fixture_path(platform: str, kind: str, name: str) -> Path:
    """Resolve `<platform>/<kind>/<name>` under the fixtures root."""
    return FIXTURES_ROOT / platform / kind / name


def load_fixture(platform: str, kind: str, name: str) -> Any:
    """Load and JSON-parse a fixture file.

    Args:
        platform: "yahoo" | "espn" | "sleeper"
        kind:     fixture category, e.g. "league_settings", "rosters"
        name:     filename including .json extension

    Raises FileNotFoundError with the resolved path if missing.
    """
    p = fixture_path(platform, kind, name)
    if not p.exists():
        raise FileNotFoundError(f"fixture not found at {p}")
    with p.open() as f:
        return json.load(f)
