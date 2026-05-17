"""JWT helpers + auth dependency for FastAPI routes."""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.engine import get_session
from app.db.models import User

ACCESS_TOKEN_TTL = timedelta(days=30)
COOKIE_NAME = "fc_session"


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> int:
    """Return user_id from a valid token. Raises HTTPException if invalid/expired."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid session")
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid session payload")


async def get_current_user(
    fc_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_session),
) -> User:
    if not fc_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user_id = decode_token(fc_session)
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Cookie-auth admin gate.

    Reads ADMIN_USER_IDS env (comma-separated User.id list) and rejects
    anyone not in the set. Empty list = admin endpoints unreachable via
    cookie. Used for the eval dashboard (/api/admin/evals/*); the legacy
    X-Admin-Secret header still protects sync/projection routes for CLI
    callers.
    """
    settings = get_settings()
    allowed = settings.admin_user_id_set
    if not allowed or user.id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access required",
        )
    return user
