"""
Workbench auth routes — human login for the management UI.

  POST   /auth/login            username+password → httponly session cookie
  POST   /auth/change-password  rotate password (the ONLY call allowed
                                while must_change_password is set)
  POST   /auth/logout           revoke the session, clear the cookie
  GET    /auth/me               who am I / do I still need to rotate
  GET    /auth/users            list users            (admin)
  POST   /auth/users            create a user          (admin)
  DELETE /auth/users/{username} disable a user         (admin)

Sessions resolve onto the same permission layer as tokens — the MCP
middleware accepts the cookie too, so a logged-in workbench can call
every tool without a separate bearer token.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth import users as users_svc
from domains.auth.passwords import hash_password
from domains.models.db_models import WorkbenchUser
from infrastructure.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "ada_session"


def _set_cookie(response: Response, request: Request, raw: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, raw,
        httponly=True, samesite="lax", path="/",
        secure=request.url.scheme == "https",
        max_age=users_svc.SESSION_TTL_HOURS * 3600,
    )


async def _session(request: Request, db: AsyncSession,
                   allow_must_change: bool = False):
    """Resolve the session cookie → (session, user). 401 when absent or
    dead; 403 when a forced rotation is pending and this endpoint isn't
    part of the rotation flow."""
    raw = request.cookies.get(SESSION_COOKIE, "")
    resolved = await users_svc.validate_session(db, raw)
    if resolved is None:
        raise HTTPException(401, "Not logged in")
    sess, user = resolved
    if (user is not None and user.must_change_password
            and not allow_must_change):
        raise HTTPException(403, "Password change required before anything else")
    return sess, user


async def require_session(request: Request, db: AsyncSession = Depends(get_db)):
    return await _session(request, db)


async def require_session_rotation_ok(request: Request,
                                      db: AsyncSession = Depends(get_db)):
    return await _session(request, db, allow_must_change=True)


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)):
    sess, user = await _session(request, db)
    if sess.role != "admin":
        raise HTTPException(403, "Admin role required")
    return sess, user


# ── Login / logout / identity ─────────────────────────────────────────

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response,
                db: AsyncSession = Depends(get_db)):
    user = await users_svc.authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(401, "Invalid username or password")
    raw = await users_svc.create_session(db, user)
    _set_cookie(response, request, raw)
    return {
        "username": user.username,
        "role": user.role,
        "allowed_space": user.allowed_space,
        "must_change_password": bool(user.must_change_password),
    }


@router.get("/me")
async def me(ctx=Depends(require_session_rotation_ok)):
    sess, user = ctx
    return {
        "username": sess.username,
        "role": sess.role,
        "allowed_space": sess.allowed_space,
        "must_change_password": bool(user.must_change_password) if user else False,
    }


@router.post("/logout")
async def logout(request: Request, response: Response,
                 db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(SESSION_COOKIE, "")
    if raw:
        await users_svc.revoke_session(db, raw)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"logged_out": True}


# ── Password rotation ─────────────────────────────────────────────────

class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=255)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, request: Request,
                          db: AsyncSession = Depends(get_db),
                          ctx=Depends(require_session_rotation_ok)):
    sess, user = ctx
    if user is None:
        raise HTTPException(403, "This session has no user behind it")
    if not users_svc.verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    err = users_svc.check_password_policy(user.username, body.new_password)
    if err:
        raise HTTPException(422, err)
    await users_svc.change_password(db, user, body.new_password)
    revoked = await users_svc.revoke_other_sessions(
        db, str(user.id), request.cookies.get(SESSION_COOKIE, ""))
    return {"changed": True, "other_sessions_revoked": revoked}


# ── User CRUD (admin) ─────────────────────────────────────────────────

class CreateUserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64,
                          pattern=r"^[a-z0-9][a-z0-9._-]*$")
    password: Optional[str] = Field(None, max_length=255)
    role: str = Field("member", pattern="^(admin|member|viewer)$")
    allowed_space: Optional[str] = None


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db),
                     ctx=Depends(require_admin)):
    rows = (await db.execute(select(WorkbenchUser).order_by(
        WorkbenchUser.created_at))).scalars().all()
    return [{
        "username": u.username, "role": u.role, "status": u.status,
        "allowed_space": u.allowed_space,
        "must_change_password": bool(u.must_change_password),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    } for u in rows]


@router.post("/users", status_code=201)
async def create_user(body: CreateUserIn, db: AsyncSession = Depends(get_db),
                      ctx=Depends(require_admin)):
    existing = (await db.execute(select(WorkbenchUser).where(
        WorkbenchUser.username == body.username))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"user '{body.username}' exists")
    # No password supplied → generate a temporary one, shown once,
    # rotation forced at first login (same flow as root/root).
    import secrets
    temp = None
    password = body.password
    if not password:
        temp = password = secrets.token_urlsafe(9)
    elif (err := users_svc.check_password_policy(body.username, password)):
        raise HTTPException(422, err)
    db.add(WorkbenchUser(
        username=body.username,
        password_hash=hash_password(password),
        role=body.role,
        allowed_space=body.allowed_space,
        must_change_password=1 if temp else 0,
    ))
    await db.commit()
    out = {"username": body.username, "role": body.role,
           "allowed_space": body.allowed_space}
    if temp:
        out["temporary_password"] = temp
        out["note"] = "Shown once — rotation is forced at first login."
    return out


@router.delete("/users/{username}")
async def disable_user(username: str, db: AsyncSession = Depends(get_db),
                       ctx=Depends(require_admin)):
    sess, user = ctx
    if username == sess.username:
        raise HTTPException(422, "You can't disable yourself")
    target = (await db.execute(select(WorkbenchUser).where(
        WorkbenchUser.username == username,
        WorkbenchUser.status == "active"))).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "user not found")
    target.status = "disabled"
    await db.commit()
    return {"username": username, "status": "disabled"}
