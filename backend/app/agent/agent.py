"""Deep agent — single instance per scoring type, reused per request.

User/league/thread context flows in via config={"configurable": {...}} at
invoke time, so tools and the checkpointer stay scoped per-call without
rebuilding the agent.

Conversation memory: the agent is built with the LangGraph PostgresSaver
checkpointer (initialized in app.agent.checkpointer). On invoke, pass
config.configurable.thread_id and LangGraph automatically loads prior
state and appends new messages.
"""

from __future__ import annotations

# IMPORTANT: env_bridge MUST come before deepagents/langchain imports.
from app.agent import env_bridge  # noqa: F401

from functools import lru_cache  # noqa: E402

from deepagents import create_deep_agent  # noqa: E402

from app.agent.checkpointer import get_checkpointer  # noqa: E402
from app.agent.prompts import build_system_prompt  # noqa: E402
from app.agent.tools.analytics import (  # noqa: E402
    compare_players,
    get_team_strength,
    get_top_by_stat,
    get_top_players_overall,
)
from app.agent.tools.free_agents import get_free_agents  # noqa: E402
from app.agent.tools.league import get_league_summary  # noqa: E402
from app.agent.tools.league_rules import get_league_rules  # noqa: E402
from app.agent.tools.player import find_player  # noqa: E402
from app.agent.tools.projections import (  # noqa: E402
    get_player_projection,
    top_projected_free_agents,
)
from app.agent.tools.roster import get_my_roster  # noqa: E402
from app.agent.tools.team import get_team_roster  # noqa: E402
from app.agent.tools.web_search import search_recent_news  # noqa: E402

ALL_TOOLS = [
    get_my_roster,
    get_league_summary,
    get_league_rules,
    get_team_roster,
    get_free_agents,
    find_player,
    get_player_projection,
    top_projected_free_agents,
    get_top_players_overall,
    get_top_by_stat,
    compare_players,
    get_team_strength,
    search_recent_news,
]

MODEL = "anthropic:claude-sonnet-4-6"


@lru_cache(maxsize=8)
def _agent_for_scoring_type(scoring_type: str):
    """Build (or reuse) a deep agent for a given league scoring type.

    NOTE: this is called per request from the chat handler, after the
    checkpointer has been started in app lifespan. We pass it via the
    `checkpointer` kwarg so the agent automatically persists conversation
    state per thread_id.
    """
    return create_deep_agent(
        model=MODEL,
        tools=ALL_TOOLS,
        system_prompt=build_system_prompt(scoring_type),
        checkpointer=get_checkpointer(),
    )


def get_agent(scoring_type: str):
    """Public accessor — always go through here so the cache is shared."""
    return _agent_for_scoring_type(scoring_type or "headpoint")


def reset_agent_cache() -> None:
    """Clear cached agents — used after the checkpointer is replaced (tests)."""
    _agent_for_scoring_type.cache_clear()
