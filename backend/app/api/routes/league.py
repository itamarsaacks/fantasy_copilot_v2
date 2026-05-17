"""League tab — standings, scoring rules, league-level settings.

GET /api/league/{league_id} returns:
  meta        league name, season, scoring type, num teams, current week
  teams       all teams in this league with W/L/points/rank/moves/trades
              and a flag marking the user's own team
  scoring     per-stat modifier table for points leagues, or the enabled
              category list for h2h/roto leagues — with abbr + display_name
              parsed out of settings_json.stat_categories
  settings    pruned view of common league knobs (max_teams, waiver_type,
              waiver_days, faab toggle, playoff settings, trade deadline)

Read-only — pulls from already-synced tables. No live Yahoo calls.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import League, Team, User
from app.security import get_current_user

router = APIRouter(prefix="/api/league", tags=["league"])


class LeagueMeta(BaseModel):
    league_id: int
    league_key: str
    name: str
    season: str
    scoring_type: str
    num_teams: int
    current_week: int | None


class TeamStanding(BaseModel):
    team_id: int
    team_key: str
    name: str
    manager_name: str | None
    logo_url: str | None
    is_user_team: bool
    rank: int | None
    wins: int | None
    losses: int | None
    ties: int | None
    points_for: float | None
    points_against: float | None
    number_of_moves: int | None
    number_of_trades: int | None
    faab_balance: int | None
    waiver_priority: int | None
    clinched_playoffs: bool | None
    division_id: str | None


class ScoringRule(BaseModel):
    stat_id: str
    abbr: str
    display_name: str
    modifier: float | None  # set for points leagues; null for categories


class LeagueSettings(BaseModel):
    max_teams: int | None
    waiver_type: str | None
    waiver_days: str | None
    waiver_rule: str | None
    waiver_time: str | None
    uses_faab: bool
    uses_playoff: bool
    trade_end_date: str | None
    max_games_played: int | None
    is_highscore: bool


class LeagueResponse(BaseModel):
    meta: LeagueMeta
    teams: list[TeamStanding]
    scoring: list[ScoringRule]
    settings: LeagueSettings


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _truthy(v: Any) -> bool:
    """Yahoo settings use '0' / '1' strings interchangeably with bools."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes"}
    return False


def _extract_scoring(settings_json: dict[str, Any], scoring_type: str) -> list[ScoringRule]:
    """Build the per-stat rule list for the UI.

    Points leagues use `stat_modifiers` for the per-stat weight.
    Category leagues just have `stat_categories` with no weight.
    Either way the abbr / display_name come from `stat_categories`.
    """
    categories: dict[str, dict[str, Any]] = {}
    sc = settings_json.get("stat_categories") if isinstance(settings_json, dict) else None
    sc_stats = sc.get("stats") if isinstance(sc, dict) else None
    if isinstance(sc_stats, list):
        for wrapper in sc_stats:
            stat = wrapper.get("stat") if isinstance(wrapper, dict) else None
            if not isinstance(stat, dict):
                continue
            sid = stat.get("stat_id")
            if sid is None:
                continue
            categories[str(sid)] = stat

    modifiers: dict[str, float] = {}
    if scoring_type in {"point", "headpoint"}:
        sm = settings_json.get("stat_modifiers") if isinstance(settings_json, dict) else None
        sm_stats = sm.get("stats") if isinstance(sm, dict) else None
        if isinstance(sm_stats, list):
            for wrapper in sm_stats:
                stat = wrapper.get("stat") if isinstance(wrapper, dict) else None
                if not isinstance(stat, dict):
                    continue
                sid = stat.get("stat_id")
                try:
                    val = float(stat.get("value"))
                except (TypeError, ValueError):
                    continue
                if sid is not None:
                    modifiers[str(sid)] = val

    rules: list[ScoringRule] = []
    seen_ids: set[str] = set()

    # Order: any stat that appears in stat_modifiers (the actually-scored ones
    # for points leagues), then anything else in categories.
    ordered_ids = list(modifiers.keys()) + [
        sid for sid in categories if sid not in modifiers
    ]
    for sid in ordered_ids:
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        cat = categories.get(sid, {})
        # Skip stat_categories entries that aren't enabled.
        if cat and str(cat.get("enabled", "1")) not in {"1", "true", "True"}:
            continue
        rules.append(
            ScoringRule(
                stat_id=sid,
                abbr=str(cat.get("abbr") or cat.get("display_name") or sid),
                display_name=str(cat.get("display_name") or cat.get("name") or sid),
                modifier=modifiers.get(sid),
            )
        )
    return rules


_WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _flatten_yahoo_list(value: Any, key: str) -> str | None:
    """Yahoo returns some settings as lists of {key: value} dicts (e.g.
    waiver_days = [{day: 0}, {day: 3}]). Flatten to a friendly string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and key in item:
                v = item[key]
                if key == "day":
                    try:
                        parts.append(_WEEKDAY_LABELS[int(v)])
                        continue
                    except (TypeError, ValueError, IndexError):
                        pass
                parts.append(str(v))
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else None
    return str(value)


def _extract_settings(settings_json: dict[str, Any]) -> LeagueSettings:
    sj = settings_json if isinstance(settings_json, dict) else {}
    return LeagueSettings(
        max_teams=_as_int(sj.get("max_teams")),
        waiver_type=_flatten_yahoo_list(sj.get("waiver_type"), "type"),
        waiver_days=_flatten_yahoo_list(sj.get("waiver_days"), "day"),
        waiver_rule=_flatten_yahoo_list(sj.get("waiver_rule"), "rule"),
        waiver_time=_flatten_yahoo_list(sj.get("waiver_time"), "time"),
        uses_faab=_truthy(sj.get("uses_faab")),
        uses_playoff=_truthy(sj.get("uses_playoff")),
        trade_end_date=_flatten_yahoo_list(sj.get("trade_end_date"), "date"),
        max_games_played=_as_int(sj.get("max_games_played")),
        is_highscore=_truthy(sj.get("is_highscore")),
    )


@router.get("/{league_id}", response_model=LeagueResponse)
async def get_league(
    league_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    league = (
        await db.execute(
            select(League).where(League.id == league_id, League.user_id == user.id)
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")

    team_rows = (
        await db.execute(
            select(Team)
            .where(Team.league_id == league_id)
            .order_by(
                # Some leagues populate rank, others only have points_for —
                # NULLS LAST + secondary points sort keeps the order sensible.
                Team.rank.asc().nullslast(),
                Team.points_for.desc().nullslast(),
                Team.name.asc(),
            )
        )
    ).scalars().all()

    teams = [
        TeamStanding(
            team_id=t.id,
            team_key=t.team_key,
            name=t.name,
            manager_name=t.manager_name,
            logo_url=t.logo_url,
            is_user_team=t.is_user_team,
            rank=t.rank,
            wins=t.wins,
            losses=t.losses,
            ties=t.ties,
            points_for=float(t.points_for) if t.points_for is not None else None,
            points_against=float(t.points_against) if t.points_against is not None else None,
            number_of_moves=t.number_of_moves,
            number_of_trades=t.number_of_trades,
            faab_balance=t.faab_balance,
            waiver_priority=t.waiver_priority,
            clinched_playoffs=t.clinched_playoffs,
            division_id=t.division_id,
        )
        for t in team_rows
    ]

    return LeagueResponse(
        meta=LeagueMeta(
            league_id=league.id,
            league_key=league.league_key,
            name=league.name,
            season=league.season,
            scoring_type=league.scoring_type,
            num_teams=league.num_teams,
            current_week=league.current_week,
        ),
        teams=teams,
        scoring=_extract_scoring(league.settings_json or {}, league.scoring_type),
        settings=_extract_settings(league.settings_json or {}),
    )
