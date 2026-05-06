"""Deep agent — single instance, reused per request.

The system prompt is per-league-type (point / headpoint / head / roto). To
avoid building 4 separate agents at import, we build one agent per scoring
type lazily and cache them.

User/league context flows in via config={"configurable": {...}} at invoke
time, so tools stay scoped to (user_id, league_id) without rebuilding.
"""

from __future__ import annotations

# IMPORTANT: env_bridge MUST come before deepagents/langchain imports.
from app.agent import env_bridge  # noqa: F401

from functools import lru_cache  # noqa: E402

from deepagents import create_deep_agent  # noqa: E402

from app.agent.prompts import build_system_prompt  # noqa: E402
from app.agent.tools.free_agents import get_free_agents  # noqa: E402
from app.agent.tools.league import get_league_summary  # noqa: E402
from app.agent.tools.player import find_player  # noqa: E402
from app.agent.tools.roster import get_my_roster  # noqa: E402
from app.agent.tools.team import get_team_roster  # noqa: E402

ALL_TOOLS = [
    get_my_roster,
    get_league_summary,
    get_team_roster,
    get_free_agents,
    find_player,
]

MODEL = "anthropic:claude-sonnet-4-6"


@lru_cache(maxsize=8)
def _agent_for_scoring_type(scoring_type: str):
    """Build (or reuse) a deep agent for a given league scoring type."""
    return create_deep_agent(
        model=MODEL,
        tools=ALL_TOOLS,
        system_prompt=build_system_prompt(scoring_type),
    )


def get_agent(scoring_type: str):
    """Public accessor — always go through here so the cache is shared."""
    return _agent_for_scoring_type(scoring_type or "headpoint")
