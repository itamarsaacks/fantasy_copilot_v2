"""Chat endpoint with conversation memory.

POST /api/chat with {message, league_id, thread_id?}:
  - If thread_id is supplied + matches, resume that conversation.
  - If absent or unknown, create a fresh conversation.
LangGraph's PostgresSaver handles message history transparently — the agent
sees prior turns automatically based on thread_id.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import get_agent
from app.api.routes.conversations import derive_title, get_or_create_for_thread
from app.db.engine import get_session
from app.db.models import League, User
from app.security import get_current_user

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    league_id: int
    thread_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    tool_calls: int
    league_name: str
    thread_id: str
    conversation_id: int
    title: str


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    league_q = await db.execute(
        select(League).where(League.id == body.league_id, League.user_id == user.id)
    )
    league = league_q.scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found for this user")

    # Resolve / create the conversation row before invoking the agent so
    # thread_id is always set in the agent's config.
    conv = await get_or_create_for_thread(db, user, league, body.thread_id)
    is_first_turn = conv.last_message_at is None

    config = {
        "configurable": {
            "user_id": user.id,
            "league_id": league.id,
            "thread_id": conv.thread_id,
        }
    }
    agent = get_agent(league.scoring_type)
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": body.message}]},
        config=config,
    )

    # Extract reply text + tool-call count from the FULL state (LangGraph
    # returns all messages including history, not just this turn).
    final_text, tool_calls = _extract_latest_assistant(result)

    # Derive a title from the first user message
    if is_first_turn:
        conv.title = derive_title(body.message)
    conv.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conv)

    return ChatResponse(
        reply=final_text or "(empty reply)",
        tool_calls=tool_calls,
        league_name=league.name,
        thread_id=conv.thread_id,
        conversation_id=conv.id,
        title=conv.title,
    )


def _extract_latest_assistant(result) -> tuple[str, int]:
    """Walk the messages list; count tool messages emitted in THIS turn and
    return the LAST assistant message's text content. The "this turn" heuristic
    is: tools after the last user message are this turn's tool calls.
    """
    messages = result.get("messages", []) if isinstance(result, dict) else []
    final_text = ""
    # Find index of last human/user message
    last_user_idx = -1
    for i, m in enumerate(messages):
        m_type = (getattr(m, "type", "") or m.__class__.__name__).lower()
        if "human" in m_type or m_type == "user":
            last_user_idx = i
    tool_calls = 0
    for i, m in enumerate(messages):
        m_type = (getattr(m, "type", "") or m.__class__.__name__).lower()
        if "tool" in m_type and i > last_user_idx:
            tool_calls += 1
        if "ai" in m_type or m_type == "assistant":
            content = getattr(m, "content", "")
            if isinstance(content, str) and content:
                final_text = content
            elif isinstance(content, list):
                pieces = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                if any(pieces):
                    final_text = "\n".join(pieces)
    return final_text, tool_calls
