"""Waivers tab — pickup recommendations, drop candidates, paired swaps.

GET /api/waivers/{league_id}?days_ahead=N returns three sections:

  pickups          top free agents ranked by their expected
                   fantasy points over the next N days
                   (per_game × games_in_window × availability)
  drops            user's roster, sorted ascending by the same score
                   so the worst-projected players bubble to the top
  suggested_swaps  top combinations of (pickup, drop) sorted by net
                   window-fps delta

Scope is intentionally small for v1. Defer to BACKLOG.md → Waivers tab:
  - FAAB context (user's league is waiver-priority anyway)
  - Slot-eligibility check on paired swaps
  - Recently-dropped timeline (needs a Yahoo transactions sync we don't
    have yet)
  - Real "claim" / "drop" actions (need write OAuth scope)
"""

from __future__ import annotations

from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    FreeAgent,
    League,
    NbaSchedule,
    Player,
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/waivers", tags=["waivers"])

# Same availability buckets as Team tab — keep in sync if we change.
_AVAIL_OUT = {"OUT", "O", "IL", "IL-LT", "NA", "SUSP"}
_AVAIL_QUESTIONABLE = {"INJ", "GTD", "DTD", "Q"}

# Roster slots that mean "this player isn't a real start-sit option" —
# IR/IL slots are excluded from drop candidates.
_IR_SLOTS = {"IR", "IR+", "IL", "IL+", "NA"}

_MAX_WINDOW_DAYS = 14
_DEFAULT_WINDOW_DAYS = 7
_DEFAULT_LIMIT = 10


def _availability_factor(status: str | None) -> float:
    s = (status or "").upper()
    if s in _AVAIL_OUT:
        return 0.0
    if s in _AVAIL_QUESTIONABLE:
        return 0.7
    return 1.0


class WaiverCandidate(BaseModel):
    player_id: int
    name: str
    nba_team: str | None
    eligible_positions: list[str]
    status: str | None
    status_full: str | None
    injury_note: str | None
    projected_fps_per_game: float | None
    games_in_window: int
    back_to_back_count: int
    availability_factor: float
    window_fps: float | None  # the headline ranking number
    waiver_status: str | None = None  # populated on pickups (A / FA / W)
    selected_position: str | None = None  # populated on drops


class SuggestedSwap(BaseModel):
    pickup: WaiverCandidate
    drop: WaiverCandidate
    delta_window_fps: float
    delta_per_game: float


class WaiversResponse(BaseModel):
    league_id: int
    window_days: int
    window_start: str
    window_end: str
    pickups: list[WaiverCandidate]
    drops: list[WaiverCandidate]
    suggested_swaps: list[SuggestedSwap]


def _build_candidate(
    *,
    player: Player,
    proj_per_game: float | None,
    team_games: list[NbaSchedule],
    waiver_status: str | None = None,
    selected_position: str | None = None,
) -> WaiverCandidate:
    avail = _availability_factor(player.status)
    games_in_window = len(team_games)
    # B2B count: number of games whose prev-day also had a game for this team
    b2b = 0
    prev_date: date_type | None = None
    for g in team_games:
        if prev_date is not None and (g.game_date - prev_date).days == 1:
            b2b += 1
        prev_date = g.game_date

    window_fps: float | None
    if proj_per_game is None:
        window_fps = None
    else:
        window_fps = round(proj_per_game * games_in_window * avail, 2)

    return WaiverCandidate(
        player_id=player.id,
        name=player.full_name,
        nba_team=player.nba_team_abbr,
        eligible_positions=player.eligible_positions or [],
        status=player.status,
        status_full=player.status_full,
        injury_note=player.injury_note,
        projected_fps_per_game=(
            round(proj_per_game, 2) if proj_per_game is not None else None
        ),
        games_in_window=games_in_window,
        back_to_back_count=b2b,
        availability_factor=avail,
        window_fps=window_fps,
        waiver_status=waiver_status,
        selected_position=selected_position,
    )


@router.get("/{league_id}", response_model=WaiversResponse)
async def get_waivers(
    league_id: int,
    days_ahead: int = Query(default=_DEFAULT_WINDOW_DAYS, ge=1, le=_MAX_WINDOW_DAYS),
    limit_pickups: int = Query(default=_DEFAULT_LIMIT, ge=1, le=50),
    limit_drops: int = Query(default=_DEFAULT_LIMIT, ge=1, le=50),
    limit_swaps: int = Query(default=5, ge=1, le=20),
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

    my_team = (
        await db.execute(
            select(Team).where(Team.league_id == league_id, Team.is_user_team.is_(True))
        )
    ).scalar_one_or_none()
    if my_team is None:
        raise HTTPException(404, "user's team not found in league")

    today = datetime.now(timezone.utc).date()
    window_end = today + timedelta(days=days_ahead)

    # ------------------------------------------------------------------
    # Collect candidate pools
    # ------------------------------------------------------------------
    # Free agents — by definition not on any team in this league.
    fa_rows = (
        await db.execute(
            select(FreeAgent, Player)
            .join(Player, Player.id == FreeAgent.player_id)
            .where(FreeAgent.league_id == league_id)
        )
    ).all()

    # User's roster — full set (we filter out IR slots for drop ranking).
    roster_rows = (
        await db.execute(
            select(RosterPlayer, Player)
            .join(Player, Player.id == RosterPlayer.player_id)
            .where(RosterPlayer.team_id == my_team.id)
        )
    ).all()

    fa_player_ids = [p.id for _, p in fa_rows]
    roster_player_ids = [p.id for _, p in roster_rows]
    all_player_ids = list({*fa_player_ids, *roster_player_ids})
    if not all_player_ids:
        return WaiversResponse(
            league_id=league_id,
            window_days=days_ahead,
            window_start=today.isoformat(),
            window_end=window_end.isoformat(),
            pickups=[],
            drops=[],
            suggested_swaps=[],
        )

    # Projections (per-game horizon)
    proj_rows = (
        await db.execute(
            select(ProjectionCache).where(
                ProjectionCache.league_id == league_id,
                ProjectionCache.horizon == "per_game",
                ProjectionCache.player_id.in_(all_player_ids),
            )
        )
    ).scalars().all()
    proj_by_player = {
        p.player_id: float(p.projected_value) if p.projected_value is not None else None
        for p in proj_rows
    }

    # Schedule for the window
    teams_in_pool = {
        p.nba_team_abbr
        for _, p in (*fa_rows, *roster_rows)
        if p.nba_team_abbr
    }
    games_by_team: dict[str, list[NbaSchedule]] = {}
    if teams_in_pool:
        sched = (
            await db.execute(
                select(NbaSchedule).where(
                    NbaSchedule.game_date >= today,
                    NbaSchedule.game_date < window_end,
                    or_(
                        NbaSchedule.home_team_abbr.in_(teams_in_pool),
                        NbaSchedule.away_team_abbr.in_(teams_in_pool),
                    ),
                )
            )
        ).scalars().all()
        for g in sorted(sched, key=lambda x: x.game_date):
            games_by_team.setdefault(g.home_team_abbr, []).append(g)
            games_by_team.setdefault(g.away_team_abbr, []).append(g)

    def _games(player: Player) -> list[NbaSchedule]:
        return games_by_team.get(player.nba_team_abbr or "", [])

    # ------------------------------------------------------------------
    # Build pickup candidates
    # ------------------------------------------------------------------
    pickups: list[WaiverCandidate] = []
    for fa, p in fa_rows:
        pickups.append(
            _build_candidate(
                player=p,
                proj_per_game=proj_by_player.get(p.id),
                team_games=_games(p),
                waiver_status=fa.waiver_status,
            )
        )
    # Sort by window_fps desc, nulls last
    pickups.sort(
        key=lambda c: (c.window_fps is None, -(c.window_fps or 0.0), c.name)
    )
    pickups = pickups[:limit_pickups]

    # ------------------------------------------------------------------
    # Build drop candidates (user's roster, exclude IR slots)
    # ------------------------------------------------------------------
    drops: list[WaiverCandidate] = []
    for rp, p in roster_rows:
        slot = (rp.selected_position or "").upper()
        if slot in _IR_SLOTS:
            continue
        drops.append(
            _build_candidate(
                player=p,
                proj_per_game=proj_by_player.get(p.id),
                team_games=_games(p),
                selected_position=rp.selected_position,
            )
        )
    # Sort ascending — worst window_fps first (good drop targets)
    drops.sort(key=lambda c: (c.window_fps is None, c.window_fps or 0.0, c.name))
    drops = drops[:limit_drops]

    # ------------------------------------------------------------------
    # Suggested swaps — top combos by net delta
    # ------------------------------------------------------------------
    swaps: list[SuggestedSwap] = []
    for pick in pickups:
        for drop in drops:
            if pick.window_fps is None or drop.window_fps is None:
                continue
            delta = pick.window_fps - drop.window_fps
            if delta <= 0:
                # Not interesting — pickup isn't better than the drop.
                continue
            per_game_delta = round(
                (pick.projected_fps_per_game or 0)
                - (drop.projected_fps_per_game or 0),
                2,
            )
            swaps.append(
                SuggestedSwap(
                    pickup=pick,
                    drop=drop,
                    delta_window_fps=round(delta, 2),
                    delta_per_game=per_game_delta,
                )
            )
    swaps.sort(key=lambda s: -s.delta_window_fps)
    swaps = swaps[:limit_swaps]

    return WaiversResponse(
        league_id=league_id,
        window_days=days_ahead,
        window_start=today.isoformat(),
        window_end=window_end.isoformat(),
        pickups=pickups,
        drops=drops,
        suggested_swaps=swaps,
    )
