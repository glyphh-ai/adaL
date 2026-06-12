"""
Workbench user + session service.

Users are the human principal (workbench login); tokens remain the
machine principal (MCP clients). Sessions issued here resolve onto the
same permission layer as tokens — see AuthService.validate_session.

First boot seeds root/root with must_change_password=1.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth.passwords import hash_password, verify_password
from domains.models.db_models import WorkbenchSession, WorkbenchUser

logger = logging.getLogger(__name__)

SESSION_TTL_HOURS = 24
MIN_PASSWORD_LENGTH = 8

# role → permission strings, mirroring token permissions
ROLE_PERMISSIONS = {
    "admin": ["read", "write", "admin"],
    "member": ["read", "write"],
    "viewer": ["read"],
}


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def ensure_default_admin(db: AsyncSession) -> bool:
    """Seed root/root (forced rotation) when no users exist yet.
    Returns True if the default admin was created on this call."""
    existing = (await db.execute(select(WorkbenchUser).limit(1))).first()
    if existing:
        return False
    db.add(WorkbenchUser(
        username="root",
        password_hash=hash_password("root"),
        role="admin",
        must_change_password=1,
    ))
    await db.commit()
    logger.warning("Seeded default workbench admin root/root — "
                   "password change is forced at first login")
    return True


async def get_user(db: AsyncSession, username: str) -> Optional[WorkbenchUser]:
    return (await db.execute(select(WorkbenchUser).where(
        WorkbenchUser.username == username,
        WorkbenchUser.status == "active",
    ))).scalar_one_or_none()


async def authenticate(db: AsyncSession, username: str,
                       password: str) -> Optional[WorkbenchUser]:
    """Verify credentials; returns the user or None. Constant-ish time:
    a dummy verify runs even when the username is unknown."""
    user = await get_user(db, username)
    if user is None:
        verify_password(password, hash_password("-"))
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.utcnow()
    await db.commit()
    return user


async def create_session(db: AsyncSession, user: WorkbenchUser,
                         ttl_hours: int = SESSION_TTL_HOURS) -> str:
    """Issue a session; returns the raw token (cookie value). Only the
    hash is stored."""
    raw = f"adas_{secrets.token_urlsafe(32)}"
    db.add(WorkbenchSession(
        token_hash=_hash(raw),
        user_id=str(user.id),
        username=user.username,
        role=user.role,
        allowed_space=user.allowed_space,
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    ))
    await db.commit()
    return raw


async def validate_session(db: AsyncSession, raw: str
                           ) -> Optional[tuple[WorkbenchSession, Optional[WorkbenchUser]]]:
    """Resolve a raw session token to its row (+ user when one exists).
    Returns None for unknown, revoked, or expired sessions."""
    if not raw or not raw.startswith("adas_"):
        return None
    sess = (await db.execute(select(WorkbenchSession).where(
        WorkbenchSession.token_hash == _hash(raw),
        WorkbenchSession.revoked_at.is_(None),
    ))).scalar_one_or_none()
    if sess is None or sess.expires_at < datetime.utcnow():
        return None
    user = None
    if sess.user_id:
        from uuid import UUID
        user = (await db.execute(select(WorkbenchUser).where(
            WorkbenchUser.id == UUID(sess.user_id),
            WorkbenchUser.status == "active",
        ))).scalar_one_or_none()
        if user is None:
            return None  # user disabled/deleted → session dies with them
    return sess, user


async def revoke_session(db: AsyncSession, raw: str) -> None:
    sess = (await db.execute(select(WorkbenchSession).where(
        WorkbenchSession.token_hash == _hash(raw),
    ))).scalar_one_or_none()
    if sess and sess.revoked_at is None:
        sess.revoked_at = datetime.utcnow()
        await db.commit()


async def revoke_other_sessions(db: AsyncSession, user_id: str,
                                keep_raw: str) -> int:
    """Kill every other session for a user (after a password change)."""
    keep = _hash(keep_raw)
    rows = (await db.execute(select(WorkbenchSession).where(
        WorkbenchSession.user_id == user_id,
        WorkbenchSession.revoked_at.is_(None),
    ))).scalars().all()
    n = 0
    for s in rows:
        if s.token_hash != keep:
            s.revoked_at = datetime.utcnow()
            n += 1
    await db.commit()
    return n


def check_password_policy(username: str, new_password: str) -> Optional[str]:
    """Returns an error message, or None when acceptable."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    if new_password.lower() == username.lower():
        return "password must not equal the username"
    if new_password.lower() == "root":
        return "that one is taken"
    return None


async def change_password(db: AsyncSession, user: WorkbenchUser,
                          new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    user.must_change_password = 0
    await db.commit()
