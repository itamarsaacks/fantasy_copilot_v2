"""Internal helpers shared across agent tools."""

from __future__ import annotations

import unicodedata

from langchain_core.runnables import RunnableConfig


def fold_ascii(s: str | None) -> str:
    """Strip diacritics + lowercase. So 'Nikola Jokić' folds to 'nikola jokic'.

    Used for fuzzy substring matching on player + team + manager names.
    """
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


def get_context(config: RunnableConfig) -> tuple[int, int]:
    """Return (user_id, league_id) from the agent invocation config."""
    cfg = (config or {}).get("configurable") or {}
    user_id = cfg.get("user_id")
    league_id = cfg.get("league_id")
    if not user_id or not league_id:
        raise ValueError("agent config missing user_id or league_id")
    return int(user_id), int(league_id)


def player_view(player, *, include_draft: bool = False) -> dict:
    """Compact dict representation of a Player ORM row, for tool output."""
    out = {
        "name": player.full_name,
        "nba_team": player.nba_team_abbr,
        "primary_position": player.primary_position,
        "eligible_positions": player.eligible_positions or [],
        "status": player.status,
        "percent_owned": float(player.percent_owned) if player.percent_owned else None,
    }
    if include_draft:
        out["draft_avg_pick"] = (
            float(player.draft_avg_pick) if player.draft_avg_pick else None
        )
        out["draft_percent_drafted"] = (
            float(player.draft_percent_drafted) if player.draft_percent_drafted else None
        )
    return out
