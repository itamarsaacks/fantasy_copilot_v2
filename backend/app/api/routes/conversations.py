"""Conversation list / detail endpoints. Owns the app-level metadata for
chat threads. The actual message history lives in LangGraph's checkpoint
tables and is fetched via the saver when a thread is resumed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.checkpointer import get_checkpointer
from app.db.engine import get_session
from app.db.models import Conversation, League, User
from app.security import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConversationOut(BaseModel):
    id: int
    thread_id: str
    title: str
    league_id: int
    league_name: str | None
    last_message_at: datetime | None
    created_at: datetime


class ConversationCreate(BaseModel):
    league_id: int


class ConversationListItem(BaseModel):
    id: int
    thread_id: str
    title: str
    last_message_at: datetime | None
    created_at: datetime


class MessageOut(BaseModel):
    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_name: str | None = None


class ConversationDetail(BaseModel):
    id: int
    thread_id: str
    title: str
    league_id: int
    last_message_at: datetime | None
    messages: list[MessageOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_owned(
    db: AsyncSession, user: User, conversation_id: int
) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id or conv.archived_at is not None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


async def _ensure_league_owned(
    db: AsyncSession, user: User, league_id: int
) -> League:
    league = await db.get(League, league_id)
    if league is None or league.user_id != user.id:
        raise HTTPException(status_code=404, detail="league not found")
    return league


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ConversationListItem])
async def list_conversations(
    league_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    limit: int = 20,
):
    """List the user's recent (non-archived) conversations in the given league."""
    await _ensure_league_owned(db, user, league_id)
    rows = (
        await db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                Conversation.league_id == league_id,
                Conversation.archived_at.is_(None),
            )
            .order_by(desc(Conversation.last_message_at).nullslast(), desc(Conversation.created_at))
            .limit(max(1, min(int(limit), 50)))
        )
    ).scalars().all()
    return [
        ConversationListItem(
            id=c.id,
            thread_id=c.thread_id,
            title=c.title,
            last_message_at=c.last_message_at,
            created_at=c.created_at,
        )
        for c in rows
    ]


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a new (empty) conversation. Returns the thread_id to use on /api/chat."""
    league = await _ensure_league_owned(db, user, body.league_id)
    thread_id = str(uuid.uuid4())
    conv = Conversation(
        user_id=user.id,
        league_id=league.id,
        thread_id=thread_id,
        title="New chat",
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        id=conv.id,
        thread_id=conv.thread_id,
        title=conv.title,
        league_id=conv.league_id,
        league_name=league.name,
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Return the full message history for a conversation by replaying it from
    the LangGraph checkpoint store.
    """
    conv = await _ensure_owned(db, user, conversation_id)
    saver = get_checkpointer()
    config = {"configurable": {"thread_id": conv.thread_id}}
    state = await saver.aget(config)
    messages: list[MessageOut] = []
    if state is not None:
        for m in (state.values or {}).get("messages", []) or []:
            role, content, tool_name = _stringify_message(m)
            if content or tool_name:
                messages.append(
                    MessageOut(role=role, content=content, tool_name=tool_name)
                )
    return ConversationDetail(
        id=conv.id,
        thread_id=conv.thread_id,
        title=conv.title,
        league_id=conv.league_id,
        last_message_at=conv.last_message_at,
        messages=messages,
    )


@router.delete("/{conversation_id}")
async def archive_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Soft-delete (archive) a conversation. We keep the LangGraph checkpoints
    so the thread could be restored later if we ever want.
    """
    conv = await _ensure_owned(db, user, conversation_id)
    conv.archived_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "id": conversation_id}


# ---------------------------------------------------------------------------
# Helpers used by /api/chat (importable from chat.py)
# ---------------------------------------------------------------------------


async def get_or_create_for_thread(
    db: AsyncSession, user: User, league: League, thread_id: str | None
) -> Conversation:
    """If thread_id is supplied and matches an existing conversation, return it.
    Otherwise create a new conversation with a fresh thread_id.
    """
    if thread_id:
        existing = (
            await db.execute(
                select(Conversation).where(
                    Conversation.thread_id == thread_id,
                    Conversation.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    conv = Conversation(
        user_id=user.id,
        league_id=league.id,
        thread_id=thread_id or str(uuid.uuid4()),
        title="New chat",
    )
    db.add(conv)
    await db.flush()
    return conv


def derive_title(message: str, max_len: int = 60) -> str:
    """Cheap title from the first user message: trim + truncate."""
    text = " ".join(message.split())
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or "New chat"


def _stringify_message(m: Any) -> tuple[str, str, str | None]:
    """Return (role, content, tool_name?) for a langchain BaseMessage."""
    m_type = (getattr(m, "type", "") or m.__class__.__name__).lower()
    content = getattr(m, "content", "") or ""

    if isinstance(content, list):
        # AIMessage with structured content blocks
        pieces = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "\n".join(p for p in pieces if p)
    if not isinstance(content, str):
        content = str(content)

    if "human" in m_type or m_type == "user":
        return "user", content, None
    if "ai" in m_type or m_type == "assistant":
        return "assistant", content, None
    if "tool" in m_type:
        return "tool", content, getattr(m, "name", None)
    return m_type, content, None
