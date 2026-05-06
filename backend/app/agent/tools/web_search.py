"""Web search tool for current player status / injury / lineup news.

Backed by Tavily. Used to answer "is X playing tonight", "any update on the
trade rumor", "did anyone get injured today" — questions that need fresh
external context our DB doesn't have yet.

CRITICAL GUARDRAIL: this tool MUST NOT be used to fetch stat numbers.
Search results are unstructured text and easy to misquote. The system prompt
forbids the LLM from quoting any stat from these snippets. Stats always come
from get_player_projection / get_my_roster / find_player.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

# env_bridge has already populated TAVILY_API_KEY from Settings before any
# agent module imports langchain_tavily. We import lazily inside the tool
# body so a missing key produces a graceful error rather than blowing up at
# import time.

log = logging.getLogger(__name__)


@tool
async def search_recent_news(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web for RECENT news/status about NBA players or teams.

    Use this for STATUS information only:
      - "is Joel Embiid playing tonight?"
      - "is the Wemby trade rumor real?"
      - "what time does the Lakers vs Heat game tip off?"
      - "did anyone get injured in tonight's games?"
      - "what's the latest on the Giannis injury timeline?"

    Args:
      query: a focused natural-language search query.
      max_results: how many snippets to return (default 5, max 10).

    Output:
      {answer: str (Tavily's summarized answer or empty),
       results: [{title, url, content, score}, ...]}.

    DO NOT use this tool for:
      - Stat numbers ("how many points did X score") — use projections / DB.
      - Anything you could answer from get_my_roster / get_league_summary /
        get_team_roster / get_free_agents / find_player /
        get_player_projection / top_projected_free_agents.
    """
    max_results = max(1, min(int(max_results), 10))

    try:
        from langchain_tavily import TavilySearch
    except ImportError as exc:
        return {"error": f"langchain_tavily not installed: {exc}"}

    try:
        search = TavilySearch(
            max_results=max_results,
            topic="news",
            include_answer=True,
            search_depth="basic",
        )
    except Exception as exc:
        # Most likely cause: TAVILY_API_KEY not set.
        return {
            "error": (
                f"web search unavailable: {exc.__class__.__name__}: {exc}. "
                "Likely cause: TAVILY_API_KEY missing in backend/.env."
            )
        }

    try:
        raw = await search.ainvoke({"query": query})
    except Exception as exc:
        log.exception("tavily search failed")
        return {"error": f"search failed: {exc.__class__.__name__}: {exc}"}

    # langchain-tavily returns either a dict or a string depending on config.
    if isinstance(raw, dict):
        return {
            "answer": raw.get("answer") or "",
            "results": [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "content": r.get("content"),
                    "score": r.get("score"),
                }
                for r in (raw.get("results") or [])[:max_results]
            ],
        }
    return {"answer": "", "results": [], "raw": str(raw)[:500]}
