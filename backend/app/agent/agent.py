"""Deep agent — instantiated once at module import and reused per request.

The agent is stateless w.r.t. user/league context: that comes in via
`config={"configurable": {"user_id": ..., "league_id": ...}}` at invoke time.
"""

from __future__ import annotations

# IMPORTANT: env_bridge MUST come before deepagents/langchain imports so
# ANTHROPIC_API_KEY / LANGSMITH_* are visible.
from app.agent import env_bridge  # noqa: F401

from deepagents import create_deep_agent  # noqa: E402

from app.agent.tools.roster import get_my_roster  # noqa: E402

SYSTEM_PROMPT = """You are Fantasy Copilot, an AI assistant for Yahoo Fantasy NBA.

Hard rules:
- You NEVER estimate a stat. If you don't have a tool that gives you a number, say so.
- All player and team data must come from a tool, not from your training data.
- When the user asks about their roster, call the get_my_roster tool.
- When you don't know something, say so plainly. Do not make up players, teams, or stats.

Style:
- Be concise. The user wants real signal, not filler.
- Reference players by their full name on first mention, then last name only.
- Use the league's scoring type to frame advice (e.g. "point" leagues care about
  total fantasy points; "head" leagues care about category wins).
"""

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[get_my_roster],
    system_prompt=SYSTEM_PROMPT,
)
