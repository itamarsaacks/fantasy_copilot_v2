"""Expose the league's rules / settings to the agent.

Reads from leagues.settings_json (the full Yahoo settings blob we stored at
OAuth time) and projects the fields users actually ask about into a clean
dict. Answers questions like:
  - "what are my waiver days?"
  - "how much FAAB does each team have?"
  - "when's the trade deadline?"
  - "do trades need to be approved?"
  - "how many playoff teams?"
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agent.tools._helpers import get_context
from app.db.engine import SessionLocal
from app.db.models import League


WAIVER_TYPE_LABELS = {
    "FR": "Free agents (first-come, no waivers)",
    "C": "Continuous waivers — claims process daily",
    "R": "Reverse standings — worst team gets priority",
    "S": "Standard rolling waivers (priority moves to last after a claim)",
}

TRADE_RATIFY_LABELS = {
    "yes": "Commissioner approves all trades",
    "no": "Trades are auto-approved (no review)",
    "vote": "League-wide vote required",
    "none": "No approval required",
    "commish": "Commissioner approves all trades",
}

DRAFT_STATUS_LABELS = {
    "predraft": "Draft has not happened yet",
    "draftpaused": "Draft is paused",
    "drafting": "Draft is in progress",
    "postdraft": "Draft is complete",
}


@tool
async def get_league_rules(config: RunnableConfig) -> dict[str, Any]:
    """Return the league's settings / rules in plain English.

    Use for questions about how the league actually works:
      - waiver schedule, waiver type, FAAB usage, max adds
      - trade deadline, trade approval rules, max trades per season
      - playoff bracket size + start week
      - draft status + type
      - season start/end dates, current week

    Output:
      {league_name, scoring_type, season, current_week,
       waivers: {type, type_label, time, rule, uses_faab, max_adds},
       trades: {end_date, ratify_type, ratify_label, max_per_season,
                reject_time_hours, allow_dropping},
       playoffs: {start_week, num_teams, has_consolation,
                  num_consolation_teams, uses_reseeding},
       draft: {status, status_label, type, time_iso, is_auction,
               post_draft_players_rule},
       roster: {positions: [{position, count}], total_slots},
       misc: {persistent_url, is_publicly_viewable, allow_intra_division_trade}}

    Not every league has every field set. Missing values appear as null.
    """
    user_id, league_id = get_context(config)
    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        s = league.settings_json or {}
        if not isinstance(s, dict):
            return {"error": "league settings are not stored in expected format"}

        waivers = {
            "type": s.get("waiver_type"),
            "type_label": WAIVER_TYPE_LABELS.get(s.get("waiver_type", ""), None),
            "time": s.get("waiver_time"),
            "rule": s.get("waiver_rule"),
            "uses_faab": _yn(s.get("uses_faab")),
            "max_adds": _safe_int(s.get("max_adds")) or _safe_int(s.get("max_weekly_adds")),
            "trade_lock_after_pickup": _yn(s.get("trade_lock_after_pickup")),
        }

        trades = {
            "end_date": s.get("trade_end_date"),
            "ratify_type": s.get("trade_ratify_type"),
            "ratify_label": TRADE_RATIFY_LABELS.get(
                str(s.get("trade_ratify_type", "")).lower(), None
            ),
            "max_per_season": _safe_int(s.get("max_trades")),
            "reject_time_hours": _safe_int(s.get("trade_reject_time")),
            "allow_dropping_during_trade": _yn(s.get("allow_dropping")),
            "allow_intra_division_trade": _yn(s.get("allow_intra_division_trade")),
        }

        playoffs = {
            "start_week": _safe_int(s.get("playoff_start_week")),
            "num_teams": _safe_int(s.get("num_playoff_teams")),
            "has_consolation": _yn(s.get("has_playoff_consolation_games")),
            "num_consolation_teams": _safe_int(s.get("num_playoff_consolation_teams")),
            "uses_reseeding": _yn(s.get("uses_playoff_reseeding")),
            "uses_lock_eliminated_teams": _yn(s.get("uses_lock_eliminated_teams")),
        }

        draft = {
            "status": s.get("draft_status"),
            "status_label": DRAFT_STATUS_LABELS.get(s.get("draft_status", ""), None),
            "type": s.get("draft_type"),
            "time_iso": _epoch_to_iso(s.get("draft_time")),
            "is_auction": _yn(s.get("is_auction_draft")),
            "post_draft_players_rule": s.get("post_draft_players"),
            "auction_budget": _safe_int(s.get("auction_budget")),
        }

        # Roster positions live in s["roster_positions"]["roster_position"]
        roster_positions: list[dict[str, Any]] = []
        rp_block = s.get("roster_positions") or {}
        if isinstance(rp_block, dict):
            entries = rp_block.get("roster_position")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("position"):
                        roster_positions.append(
                            {
                                "position": entry.get("position"),
                                "count": _safe_int(entry.get("count")),
                                "abbreviation": entry.get("abbreviation"),
                            }
                        )
        total_slots = sum(p["count"] for p in roster_positions if p.get("count"))

        misc = {
            "persistent_url": s.get("persistent_url"),
            "is_publicly_viewable": _yn(s.get("is_publicly_viewable")),
            "renew": s.get("renew"),
            "renewable": _yn(s.get("renewable")),
            "weekly_deadline": s.get("weekly_deadline"),
            "league_update_timestamp": _epoch_to_iso(s.get("league_update_timestamp")),
        }

        return {
            "league_name": league.name,
            "scoring_type": league.scoring_type,
            "season": league.season,
            "current_week": league.current_week,
            "num_teams": league.num_teams,
            "waivers": waivers,
            "trades": trades,
            "playoffs": playoffs,
            "draft": draft,
            "roster": {
                "positions": roster_positions,
                "total_slots": total_slots if total_slots else None,
            },
            "misc": misc,
        }


def _yn(value) -> bool | None:
    if value is None or value == "":
        return None
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return None


def _safe_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _epoch_to_iso(value) -> str | None:
    """Yahoo timestamps come as unix-epoch strings or ints. Convert to ISO."""
    if value is None or value == "":
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OSError, ValueError):
        return None
