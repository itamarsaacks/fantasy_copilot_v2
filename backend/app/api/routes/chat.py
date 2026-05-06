"""Chat endpoint. Phase 4: simple JSON in / JSON out. SSE arrives in Phase 8."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import get_agent
from app.db.engine import get_session
from app.db.models import League, User
from app.security import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    league_id: int


class ChatResponse(BaseModel):
    reply: str
    tool_calls: int
    league_name: str


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

    config = {
        "configurable": {
            "user_id": user.id,
            "league_id": league.id,
        }
    }
    agent = get_agent(league.scoring_type)
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": body.message}]},
        config=config,
    )

    messages = result.get("messages", []) if isinstance(result, dict) else []
    final_text = ""
    tool_calls = 0
    for m in messages:
        # Each message is a langchain BaseMessage; we count tool calls and grab the
        # last assistant text response.
        m_type = getattr(m, "type", "") or m.__class__.__name__.lower()
        if m_type in ("tool", "toolmessage"):
            tool_calls += 1
        if m_type in ("ai", "aimessage"):
            content = getattr(m, "content", "")
            if isinstance(content, str) and content:
                final_text = content
            elif isinstance(content, list):
                # When the assistant produces structured content blocks, join the text ones.
                pieces = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                if any(pieces):
                    final_text = "\n".join(pieces)

    return ChatResponse(
        reply=final_text or "(empty reply)",
        tool_calls=tool_calls,
        league_name=league.name,
    )
