"""League-wide analyst tools — leaderboards, comparisons, team strengths.

These work entirely off data we already sync (Phase 6.5 stats + projections).
Date-range / per-game-log queries land in Phase 9 once we sync NBA game logs.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import desc, func, select

from app.agent.tools._helpers import fold_ascii, get_context, player_view
from app.db.engine import SessionLocal
from app.db.models import (
    FreeAgent,
    League,
    Player,
    PlayerStats,
    ProjectionCache,
    RosterPlayer,
    Team,
)

# Yahoo NBA stat_id lookup. Stable across leagues. Display names are what the
# user / LLM uses; the raw stat_id is what's in player_stats.
STAT_ID_BY_ALIAS: dict[str, tuple[str, str]] = {
    # alias -> (stat_id, pretty name)
    "gp": ("0", "Games Played"),
    "games_played": ("0", "Games Played"),
    "gs": ("1", "Games Started"),
    "min": ("9004003", "Minutes"),
    "minutes": ("9004003", "Minutes"),
    "fgm": ("3", "FG Made"),
    "fga": ("4", "FG Attempted"),
    "fg%": ("5", "FG%"),
    "fg_pct": ("5", "FG%"),
    "ftm": ("7", "FT Made"),
    "fta": ("8", "FT Attempted"),
    "ft%": ("9", "FT%"),
    "ft_pct": ("9", "FT%"),
    "3pm": ("10", "3PT Made"),
    "3p": ("10", "3PT Made"),
    "threes": ("10", "3PT Made"),
    "pts": ("12", "Points"),
    "points": ("12", "Points"),
    "oreb": ("13", "Off Rebounds"),
    "dreb": ("14", "Def Rebounds"),
    "reb": ("15", "Rebounds"),
    "rebounds": ("15", "Rebounds"),
    "ast": ("16", "Assists"),
    "assists": ("16", "Assists"),
    "stl": ("17", "Steals"),
    "steals": ("17", "Steals"),
    "blk": ("18", "Blocks"),
    "blocks": ("18", "Blocks"),
    "to": ("19", "Turnovers"),
    "turnovers": ("19", "Turnovers"),
    "tov": ("19", "Turnovers"),
}


def _resolve_stat(name: str) -> tuple[str | None, str | None]:
    key = name.strip().lower().replace(" ", "_")
    if key in STAT_ID_BY_ALIAS:
        return STAT_ID_BY_ALIAS[key]
    # Allow raw stat_id input
    raw = name.strip()
    for sid, pretty in STAT_ID_BY_ALIAS.values():
        if sid == raw:
            return sid, pretty
    return None, None


@tool
async def get_top_players_overall(
    config: RunnableConfig,
    horizon: str = "per_game",
    position: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return the highest-projected players in this league across ALL ownership
    states (rostered + free agent). Use this for any "best players in the
    league", "top scorers", "league leaders by projection" question.

    Args:
      horizon: "per_game" (default) or "season_total".
      position: optional filter (PG, SG, SF, PF, C, G, F, FC).
      limit: 1-50 (default 10).

    Output: {count, players: [{name, nba_team, primary_position, status,
                               percent_owned, projected_value, ownership: {...}}]}.

    `ownership.kind` is "rostered" (with team_name + manager + is_user_team)
    or "free_agent" — so the agent can always tell the user where the
    player sits in this league.
    """
    user_id, league_id = get_context(config)
    limit = max(1, min(int(limit), 50))
    pos_filter = position.upper().strip() if position else None

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        rows = (
            await db.execute(
                select(Player, ProjectionCache)
                .join(
                    ProjectionCache,
                    (ProjectionCache.player_id == Player.id)
                    & (ProjectionCache.league_id == league_id)
                    & (ProjectionCache.horizon == horizon),
                )
                .order_by(desc(ProjectionCache.projected_value).nullslast())
            )
        ).all()

        # Pull ownership in one shot for all candidate players.
        cand_ids = [p.id for p, _ in rows[: limit * 4]]  # buffer for position filter
        roster_q = await db.execute(
            select(RosterPlayer.player_id, Team.name, Team.manager_name, Team.is_user_team)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(Team.league_id == league_id, RosterPlayer.player_id.in_(cand_ids))
        )
        owner_by_player: dict[int, dict[str, Any]] = {
            pid: {
                "kind": "rostered",
                "team_name": tname,
                "manager": mname,
                "is_user_team": bool(is_user),
            }
            for pid, tname, mname, is_user in roster_q.all()
        }
        fa_q = await db.execute(
            select(FreeAgent.player_id).where(
                FreeAgent.league_id == league_id, FreeAgent.player_id.in_(cand_ids)
            )
        )
        for (pid,) in fa_q.all():
            owner_by_player.setdefault(pid, {"kind": "free_agent"})

        out: list[dict[str, Any]] = []
        for player, proj in rows:
            if pos_filter:
                eligible = [pos.upper() for pos in (player.eligible_positions or [])]
                if pos_filter not in eligible:
                    continue
            view = player_view(player)
            view["projected_value"] = (
                float(proj.projected_value) if proj.projected_value is not None else None
            )
            view["ownership"] = owner_by_player.get(player.id, {"kind": "unknown"})
            out.append(view)
            if len(out) >= limit:
                break

        return {"count": len(out), "horizon": horizon, "players": out}


@tool
async def get_top_by_stat(
    stat: str,
    config: RunnableConfig,
    limit: int = 10,
    position: str | None = None,
) -> dict[str, Any]:
    """Return the league leaders in a single raw NBA stat for this season.

    Use for: "who has the most points", "league rebound leaders", "who shot
    the best from three", "top assist players in my league". Reads
    season-totals from the player_stats table (synced from Yahoo).

    Args:
      stat: stat name. Accepts: PTS / Points, REB / Rebounds, AST / Assists,
            STL / Steals, BLK / Blocks, TO / Turnovers, FG% / FT%, 3PM, FGM,
            FTM, FGA, FTA, GP, MIN, OREB, DREB. Case-insensitive.
      limit: 1-50 (default 10).
      position: optional eligibility filter.

    Output: {stat_name, count, players: [{name, nba_team, primary_position,
             status, percent_owned, value, ownership: {...}}]}.

    For percentage stats (FG%, FT%) the value is a 0–1 ratio; for counting
    stats it's a season total.
    """
    user_id, league_id = get_context(config)
    stat_id, pretty = _resolve_stat(stat)
    if not stat_id:
        return {"error": f"unknown stat '{stat}'"}
    limit = max(1, min(int(limit), 50))
    pos_filter = position.upper().strip() if position else None

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        # Latest as_of_date per player for season-scope rows. Subquery picks
        # the max as_of_date per player; we then join back for that stat_id.
        latest_dates_subq = (
            select(
                PlayerStats.player_id,
                func.max(PlayerStats.as_of_date).label("max_date"),
            )
            .where(PlayerStats.scope == "season", PlayerStats.stat_id == stat_id)
            .group_by(PlayerStats.player_id)
            .subquery()
        )

        rows = (
            await db.execute(
                select(Player, PlayerStats.value)
                .join(PlayerStats, PlayerStats.player_id == Player.id)
                .join(
                    latest_dates_subq,
                    (latest_dates_subq.c.player_id == PlayerStats.player_id)
                    & (latest_dates_subq.c.max_date == PlayerStats.as_of_date),
                )
                .where(
                    PlayerStats.scope == "season",
                    PlayerStats.stat_id == stat_id,
                )
                .order_by(desc(PlayerStats.value))
                .limit(limit * 4)  # buffer for position filter
            )
        ).all()

        # Restrict to this league: must be either rostered here or a FA here.
        cand_ids = [p.id for p, _ in rows]
        in_league_q = await db.execute(
            select(RosterPlayer.player_id)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(Team.league_id == league_id, RosterPlayer.player_id.in_(cand_ids))
        )
        rostered_ids = {pid for (pid,) in in_league_q.all()}
        fa_q = await db.execute(
            select(FreeAgent.player_id).where(
                FreeAgent.league_id == league_id, FreeAgent.player_id.in_(cand_ids)
            )
        )
        fa_ids = {pid for (pid,) in fa_q.all()}
        in_league = rostered_ids | fa_ids

        # Ownership lookup (single pass)
        roster_q = await db.execute(
            select(RosterPlayer.player_id, Team.name, Team.manager_name, Team.is_user_team)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(Team.league_id == league_id, RosterPlayer.player_id.in_(rostered_ids))
        )
        owner_by_player: dict[int, dict[str, Any]] = {
            pid: {
                "kind": "rostered",
                "team_name": tname,
                "manager": mname,
                "is_user_team": bool(is_user),
            }
            for pid, tname, mname, is_user in roster_q.all()
        }
        for pid in fa_ids - rostered_ids:
            owner_by_player[pid] = {"kind": "free_agent"}

        out: list[dict[str, Any]] = []
        for player, value in rows:
            if player.id not in in_league:
                continue
            if pos_filter:
                eligible = [pos.upper() for pos in (player.eligible_positions or [])]
                if pos_filter not in eligible:
                    continue
            view = player_view(player)
            view["value"] = float(value) if value is not None else None
            view["ownership"] = owner_by_player.get(player.id, {"kind": "unknown"})
            out.append(view)
            if len(out) >= limit:
                break

        return {"stat_name": pretty, "count": len(out), "players": out}


@tool
async def compare_players(
    names: list[str],
    config: RunnableConfig,
    horizon: str = "per_game",
) -> dict[str, Any]:
    """Compare 2-4 players side by side: identity, season totals, projection,
    ownership in this league.

    Use for "X vs Y", "should I trade A for B", "who's the better waiver pick".

    Args:
      names: 2-4 player name fragments (case + diacritic insensitive).
      horizon: "per_game" or "season_total" for projected_value.

    Output: {players: [{name, nba_team, primary_position, status, percent_owned,
             projected_value, components, season_stats (dict {stat_name: value}),
             ownership: {kind, ...}}]}.

    If a name doesn't uniquely match, returns {ambiguous: [...]} for that name.
    """
    user_id, league_id = get_context(config)
    if not names or len(names) < 2 or len(names) > 4:
        return {"error": "compare requires 2-4 player names"}

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        all_players = (await db.execute(select(Player))).scalars().all()
        out_players: list[dict[str, Any]] = []
        for name in names:
            needle = fold_ascii(name)
            matches = [p for p in all_players if needle and needle in fold_ascii(p.full_name)]
            if not matches:
                return {"error": f"no player matched '{name}'"}
            if len(matches) > 1:
                return {
                    "ambiguous_for": name,
                    "candidates": [
                        {"name": p.full_name, "nba_team": p.nba_team_abbr}
                        for p in matches[:8]
                    ],
                }
            player = matches[0]

            # Projection
            proj = (
                await db.execute(
                    select(ProjectionCache).where(
                        ProjectionCache.player_id == player.id,
                        ProjectionCache.league_id == league_id,
                        ProjectionCache.horizon == horizon,
                    )
                )
            ).scalar_one_or_none()

            # Season-total stats — latest snapshot
            stat_rows = (
                await db.execute(
                    select(PlayerStats.stat_id, PlayerStats.value, PlayerStats.as_of_date)
                    .where(
                        PlayerStats.player_id == player.id,
                        PlayerStats.scope == "season",
                    )
                    .order_by(desc(PlayerStats.as_of_date))
                )
            ).all()
            season_stats: dict[str, float] = {}
            seen_stat_ids: set[str] = set()
            latest_date = None
            for sid, value, asof in stat_rows:
                if latest_date is None:
                    latest_date = asof
                if asof != latest_date:
                    continue
                if sid in seen_stat_ids:
                    continue
                pretty = next(
                    (n for k, (i, n) in STAT_ID_BY_ALIAS.items() if i == sid),
                    f"stat_{sid}",
                )
                season_stats[pretty] = float(value) if value is not None else None  # type: ignore[assignment]
                seen_stat_ids.add(sid)

            # Ownership
            roster_row = (
                await db.execute(
                    select(RosterPlayer, Team)
                    .join(Team, Team.id == RosterPlayer.team_id)
                    .where(
                        RosterPlayer.player_id == player.id,
                        Team.league_id == league_id,
                    )
                )
            ).first()
            if roster_row:
                _rp, team = roster_row
                ownership = {
                    "kind": "rostered",
                    "team_name": team.name,
                    "manager": team.manager_name,
                    "is_user_team": team.is_user_team,
                }
            else:
                fa = (
                    await db.execute(
                        select(FreeAgent).where(
                            FreeAgent.player_id == player.id,
                            FreeAgent.league_id == league_id,
                        )
                    )
                ).scalar_one_or_none()
                ownership = {"kind": "free_agent" if fa else "unknown"}

            view = player_view(player, include_draft=True)
            view["projected_value"] = (
                float(proj.projected_value) if proj and proj.projected_value is not None else None
            )
            view["projection_horizon"] = horizon
            view["projection_components"] = proj.components if proj else {}
            view["season_stats"] = season_stats
            view["ownership"] = ownership
            out_players.append(view)

        return {"horizon": horizon, "players": out_players}


@tool
async def get_team_strength(
    team_name_or_manager: str,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Compute a fantasy team's per-stat totals across its current roster, with
    league-wide percentile rank for each stat. Tells you where the team is
    strong vs weak by category.

    Use for: "where am I weak", "what does my team need", "who has the best
    rebounding team", "is X's team strong in steals".

    Args:
      team_name_or_manager: team name OR manager nickname (case + diacritic
        insensitive). Returns ambiguous list if multiple match.

    Output (CATEGORY leagues — head, roto):
      {team_name, manager, rank, scoring_type,
       stats: [{stat_name, total, league_avg, percentile_rank, ranking,
                lower_is_better}, ...]}

    Output (POINTS leagues — point, headpoint):
      {team_name, manager, rank, scoring_type,
       total_fantasy_points, league_avg_fantasy_points, fps_ranking,
       stats: [{stat_name, raw_total, fantasy_points_contribution,
                pct_of_team_fps}, ...]}

      In points leagues, percentile ranks per stat are NOT meaningful for
      strategy — only total fantasy points matter. The output instead shows
      where the team's fantasy points come from (the contribution of each
      stat to the total). Use this descriptively, not strategically. The
      strategic number is `total_fantasy_points` and `fps_ranking`.
    """
    user_id, league_id = get_context(config)
    needle = fold_ascii(team_name_or_manager)
    if not needle:
        return {"error": "empty search"}

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        teams = (
            await db.execute(select(Team).where(Team.league_id == league_id))
        ).scalars().all()
        matches = [
            t
            for t in teams
            if needle in fold_ascii(t.name) or needle in fold_ascii(t.manager_name)
        ]
        if not matches:
            return {"error": f"no team or manager matched '{team_name_or_manager}'"}
        if len(matches) > 1:
            return {
                "ambiguous": [
                    {"team_name": t.name, "manager": t.manager_name, "rank": t.rank}
                    for t in matches
                ]
            }
        target_team = matches[0]

        # Pull latest season stats for ALL rostered players across ALL teams
        # in this league. Compute per-team totals.
        team_player_q = await db.execute(
            select(RosterPlayer.team_id, RosterPlayer.player_id)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(Team.league_id == league_id)
        )
        team_to_players: dict[int, list[int]] = {}
        all_player_ids: set[int] = set()
        for tid, pid in team_player_q.all():
            team_to_players.setdefault(tid, []).append(pid)
            all_player_ids.add(pid)

        if not all_player_ids:
            return {"error": "no roster data"}

        latest_dates_subq = (
            select(
                PlayerStats.player_id,
                func.max(PlayerStats.as_of_date).label("max_date"),
            )
            .where(
                PlayerStats.scope == "season",
                PlayerStats.player_id.in_(all_player_ids),
            )
            .group_by(PlayerStats.player_id)
            .subquery()
        )
        stat_rows = (
            await db.execute(
                select(PlayerStats.player_id, PlayerStats.stat_id, PlayerStats.value)
                .join(
                    latest_dates_subq,
                    (latest_dates_subq.c.player_id == PlayerStats.player_id)
                    & (latest_dates_subq.c.max_date == PlayerStats.as_of_date),
                )
                .where(PlayerStats.scope == "season")
            )
        ).all()
        # player_stats: player_id -> {stat_id: value}
        player_stats: dict[int, dict[str, float]] = {}
        for pid, sid, value in stat_rows:
            if value is None:
                continue
            player_stats.setdefault(pid, {})[sid] = float(value)

        # Tally per team per stat
        # Only include counting stats (skip percentages — they don't sum)
        countable_ids = {
            "0", "1", "3", "4", "7", "8", "10", "12", "13", "14", "15",
            "16", "17", "18", "19",
        }
        # Inverse stats — for percentile_rank, lower is better.
        inverse = {"19"}

        team_totals: dict[int, dict[str, float]] = {}
        for tid, pids in team_to_players.items():
            t_totals: dict[str, float] = {}
            for pid in pids:
                stats = player_stats.get(pid, {})
                for sid, val in stats.items():
                    if sid not in countable_ids:
                        continue
                    t_totals[sid] = t_totals.get(sid, 0.0) + val
            team_totals[tid] = t_totals

        scoring_type = league.scoring_type
        is_points_league = scoring_type in ("point", "headpoint")

        # In points leagues, derive each team's TOTAL fantasy points using
        # league.settings_json's stat_modifiers. This is the only thing that
        # matters for standings.
        if is_points_league:
            modifiers = _extract_stat_modifiers(league.settings_json)

            # ACTUAL standings — use teams.points_for + teams.rank for the
            # truth of "where is this team in the league". These reflect what
            # actually happened over the season (right roster at right time,
            # starter vs bench, etc.).
            actual_points_for_by_team = {
                t.id: float(t.points_for) if t.points_for is not None else 0.0
                for t in teams
            }
            actual_target_points = actual_points_for_by_team.get(target_team.id, 0.0)
            n = len(teams)
            league_avg_actual = (
                sum(actual_points_for_by_team.values()) / n if n else 0.0
            )

            # HYPOTHETICAL — apply scoring rules to the CURRENT roster's
            # season-total stats. Useful for "if this exact roster had been
            # together all season, how much would they have scored?" but
            # NOT the same as standings.
            def hypothetical_fps_for(t_totals: dict[str, float]) -> float:
                total = 0.0
                for sid, val in t_totals.items():
                    mod = modifiers.get(sid)
                    if mod is None:
                        continue
                    total += val * mod
                return total

            hyp_fps = {tid: hypothetical_fps_for(t) for tid, t in team_totals.items()}
            target_hyp_fps = hyp_fps.get(target_team.id, 0.0)

            # Per-stat fantasy point contribution from the current roster
            target_t_totals = team_totals.get(target_team.id, {})
            stats_out: list[dict[str, Any]] = []
            for sid in countable_ids:
                raw_total = target_t_totals.get(sid, 0.0)
                if raw_total == 0:
                    continue
                modifier = modifiers.get(sid, 0.0)
                contribution = raw_total * modifier
                if contribution == 0:
                    continue
                pretty = next(
                    (name for _, (i, name) in STAT_ID_BY_ALIAS.items() if i == sid),
                    f"stat_{sid}",
                )
                stats_out.append(
                    {
                        "stat_name": pretty,
                        "raw_total": round(raw_total, 2),
                        "fantasy_points_contribution": round(contribution, 2),
                        "pct_of_team_fps": round(
                            100 * contribution / target_hyp_fps, 1
                        )
                        if target_hyp_fps
                        else 0.0,
                    }
                )
            stats_out.sort(
                key=lambda s: abs(s["fantasy_points_contribution"]), reverse=True
            )

            return {
                "team_name": target_team.name,
                "manager": target_team.manager_name,
                "is_user_team": target_team.is_user_team,
                "scoring_type": scoring_type,
                # ACTUAL standings — use these for "where am I ranked"
                "actual_total_fantasy_points": round(actual_target_points, 2),
                "actual_rank": target_team.rank,
                "actual_league_avg_fantasy_points": round(league_avg_actual, 2),
                "n_teams": n,
                # HYPOTHETICAL — current roster x season stats
                "hypothetical_current_roster_fps": round(target_hyp_fps, 2),
                # Stat breakdown from current roster (descriptive)
                "stats": stats_out,
                "note": (
                    "POINTS LEAGUE — actual_rank and actual_total_fantasy_points "
                    "are the truth of where this team stands (driven by who was on "
                    "the roster all season, starter/bench decisions, etc.). "
                    "hypothetical_current_roster_fps is what THIS exact current "
                    "roster would have scored if they'd been together all year — "
                    "useful for assessing current roster strength but NOT the same "
                    "as standings. The per-stat breakdown comes from the current "
                    "roster, so it's descriptive of who this team has NOW, not "
                    "what they actually scored."
                ),
            }

        # CATEGORY leagues (head, roto): per-stat percentile ranks ARE strategic.
        stats_out: list[dict[str, Any]] = []
        for sid in countable_ids:
            values_by_team = {
                tid: t_totals.get(sid, 0.0) for tid, t_totals in team_totals.items()
            }
            if all(v == 0 for v in values_by_team.values()):
                continue
            sorted_teams = sorted(
                values_by_team.items(),
                key=lambda kv: kv[1],
                reverse=(sid not in inverse),
            )
            ranking = next(
                (i + 1 for i, (tid, _) in enumerate(sorted_teams) if tid == target_team.id),
                None,
            )
            n = len(sorted_teams)
            target_value = values_by_team.get(target_team.id, 0.0)
            league_avg = sum(values_by_team.values()) / n if n else 0.0
            percentile = (
                round(100 * (n - ranking) / max(n - 1, 1), 1) if ranking else 0.0
            )
            pretty = next(
                (name for _, (i, name) in STAT_ID_BY_ALIAS.items() if i == sid),
                f"stat_{sid}",
            )
            stats_out.append(
                {
                    "stat_name": pretty,
                    "total": round(target_value, 2),
                    "league_avg": round(league_avg, 2),
                    "ranking": ranking,
                    "percentile_rank": percentile,
                    "lower_is_better": sid in inverse,
                }
            )

        return {
            "team_name": target_team.name,
            "manager": target_team.manager_name,
            "rank": target_team.rank,
            "is_user_team": target_team.is_user_team,
            "scoring_type": scoring_type,
            "stats": stats_out,
        }


def _extract_stat_modifiers(settings_json) -> dict[str, float]:
    """Local copy of the projection-engine helper, kept here to avoid
    importing from the engine into a tool module."""
    out: dict[str, float] = {}
    if not isinstance(settings_json, dict):
        return out
    sm = settings_json.get("stat_modifiers") or {}
    stats = sm.get("stats") if isinstance(sm, dict) else None
    if not isinstance(stats, list):
        return out
    for wrapper in stats:
        if not isinstance(wrapper, dict):
            continue
        s = wrapper.get("stat")
        if not isinstance(s, dict):
            continue
        stat_id = str(s.get("stat_id")) if s.get("stat_id") is not None else None
        try:
            value = float(s.get("value")) if s.get("value") not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        if stat_id and value is not None:
            out[stat_id] = value
    return out
