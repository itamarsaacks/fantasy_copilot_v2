"""The platform-agnostic connector contract.

A `Connector` is a read-only adapter from one fantasy platform (Yahoo,
ESPN, Sleeper, ...) into our canonical internal data model. Once a
connector exists for a platform, every tab and every agent tool works
for users on that platform automatically — no platform-specific code
in the app/api or app/agent layers.

The contract is intentionally narrow (seven methods). It captures
exactly what we need to project our internal model and answer every
question the agent gets asked. Anything else a platform offers
(writing trades, social features, mobile push, etc.) is OUT OF SCOPE
for v1 — see docs/plans/league-formats.md §3.

Method-by-method:

  fetch_league_meta        league_key, name, season, scoring_type,
                           num_teams, current_week
  fetch_scoring_rules      stat_modifiers (points) or stat_categories
                           (cat), in normalized form
  fetch_roster_slots       slot composition (PG/SG/UTIL/BN/IL/...)
  fetch_settings_extras    trade deadline, waiver type, max games,
                           keeper flags
  fetch_teams              team_id, name, manager, current standings
  fetch_current_rosters    {team_id: [player_keys]} as of now
  fetch_transactions       draft + add/drop/trade events for ownership
                           replay (the load-bearing call for
                           `roster_at`)

Implementations live next to this file:
  - yahoo.py  (existing — adapt to this protocol without rewriting)
  - espn.py   (TODO — added during the ESPN connector session)
  - sleeper.py (TODO — bonus, NBA support is thin)

A connector is constructed with whatever credentials its platform
needs (OAuth token for Yahoo, espn_s2 + SWID cookies for ESPN private
leagues, just a league_id for Sleeper). Construction is platform-
specific; the resulting object satisfies this Protocol.

Why a Protocol and not an ABC: connectors don't share implementation
state — each platform's wire format is wildly different. The Protocol
gives us a typed seam at the call sites without forcing inheritance
gymnastics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol


# ---------------------------------------------------------------------------
# Normalized return types — what every connector MUST produce, regardless of
# what wire format the upstream uses.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeagueMeta:
    """Top-level league identity + scoring type.

    `scoring_type` MUST be one of the canonical Yahoo strings so it
    routes through the same valuators regardless of platform:
        point | seasonpoint | headpoint | head | headone | roto

    ESPN/Sleeper connectors translate their native scoring identifiers
    into one of these — see app/connectors/<platform>.py for the map.
    """

    league_key: str  # platform-prefixed unique key, e.g. "yahoo:466.l.162434"
    name: str
    season: str
    scoring_type: Literal[
        "point", "seasonpoint", "headpoint", "head", "headone", "roto"
    ]
    num_teams: int
    current_week: int | None


@dataclass(frozen=True)
class ScoringRule:
    """One row in the league's scoring table.

    For POINTS leagues: `modifier` is the per-occurrence point value
    (PTS=1, REB=1.2, TO=-1, ...).
    For CATEGORY leagues: `modifier` is None — the stat counts as a
    category but has no point weight.
    """

    stat_id: str
    abbr: str  # PTS, REB, AST, ...
    display_name: str
    modifier: float | None


@dataclass(frozen=True)
class RosterSlotDef:
    """One slot in the lineup. `count` slots of `position`.

    Example: RosterSlotDef("PG", 1), RosterSlotDef("BN", 3),
             RosterSlotDef("IL", 3).
    """

    position: str
    count: int


@dataclass(frozen=True)
class LeagueSettingsExtras:
    """Universal per-league knobs that aren't scoring/roster.

    Surfaced in the UI as status pills (trade deadline countdown,
    FAAB vs priority, max games progress) and fed into agent context
    for format-aware strategy advice.
    """

    waiver_type: str | None        # "continual" | "FAAB" | "lock" ...
    uses_faab: bool
    waiver_days: str | None        # e.g. "2", "0"
    trade_end_date: date | None    # past date => trading closed
    max_games_played: int | None   # cap per player per season (cat leagues)
    max_weekly_adds: int | None    # acquisition cap
    is_keeper: bool                # true => keeper or dynasty
    keeper_count: int | None       # how many keepers per team
    uses_playoff: bool
    playoff_start_week: int | None
    num_playoff_teams: int | None


@dataclass(frozen=True)
class TeamInfo:
    """One fantasy team within a league.

    The string keys (`team_key`, `manager_id`) are platform-scoped;
    the integer `team_id_in_league` is the human-friendly slot number
    (1..num_teams) which is stable across platforms.
    """

    team_key: str
    team_id_in_league: int
    name: str
    manager_name: str | None
    manager_id: str | None
    is_user_team: bool
    logo_url: str | None
    # Current standings — h2h uses W/L/T; points leagues use points_for/against.
    wins: int | None
    losses: int | None
    ties: int | None
    rank: int | None
    points_for: float | None
    points_against: float | None
    faab_balance: int | None
    waiver_priority: int | None


@dataclass(frozen=True)
class OwnershipEvent:
    """One add / drop / trade in a league's history.

    Walking these in `occurred_at` order reconstructs every team's
    roster at any past date — the foundation of `roster_at` and the
    historical My Team / League tabs.

    `from_team_id_in_league=None` ⇒ player was a free agent.
    `to_team_id_in_league=None` ⇒ player became a free agent (drop).
    """

    occurred_at: datetime
    event_type: Literal["add", "drop", "trade", "draft"]
    player_key: str
    from_team_id_in_league: int | None
    to_team_id_in_league: int | None
    transaction_key: str  # platform-stable dedup key


# ---------------------------------------------------------------------------
# The Connector Protocol
# ---------------------------------------------------------------------------


class Connector(Protocol):
    """Read-only adapter from one fantasy platform into our internal model.

    Every method is async because every implementation hits the network.
    The shape of `league_id` is platform-scoped (Yahoo: numeric league
    key suffix; ESPN: leagueId; Sleeper: league_id string) — the
    connector instance is constructed knowing what to do with it.
    """

    platform: str  # "yahoo" | "espn" | "sleeper"

    async def fetch_league_meta(self) -> LeagueMeta: ...

    async def fetch_scoring_rules(self) -> list[ScoringRule]: ...

    async def fetch_roster_slots(self) -> list[RosterSlotDef]: ...

    async def fetch_settings_extras(self) -> LeagueSettingsExtras: ...

    async def fetch_teams(self) -> list[TeamInfo]: ...

    async def fetch_current_rosters(
        self,
    ) -> dict[int, list[str]]:  # team_id_in_league -> [player_key]
        ...

    async def fetch_transactions(
        self,
        since: date | None = None,
    ) -> list[OwnershipEvent]:
        """Full transaction history (draft + every add/drop/trade).

        `since` is a hint — implementations MAY pull only events on/
        after this date if their API supports it, but a correct
        implementation that ignores `since` is still allowed (the
        downstream upserter is idempotent via `transaction_key`).
        """
        ...
