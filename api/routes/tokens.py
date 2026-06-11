"""
Token API Routes for Ada Runtime.

CRUD for API tokens stored in the runtime database.
Tokens are used by external services (Boomi, Make.com, agents) to
access listener and MCP endpoints.

Routes:
  POST   /{org_id}/tokens          Create a new token
  GET    /{org_id}/tokens          List active tokens
  DELETE /{org_id}/tokens/{token_id}  Revoke a token
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.models.db_models import Token
from infrastructure.config import get_settings
from infrastructure.database import get_db
from shared.auth import AuthenticatedUser, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/{org_id}/tokens", tags=["tokens"])
settings = get_settings()


async def validate_org_owner(
    org_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Only the org owner (via CLI login) can manage tokens."""
    if current_user.org_id != org_id:
        raise HTTPException(status_code=403, detail="Organization mismatch")
    return current_user


# ── Request / Response models ──

class CreateTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Token name (e.g. 'boomi-prod')")
    model_id: Optional[str] = Field(None, description="Scope to a specific model (None = all models)")
    permissions: List[str] = Field(default=["read", "write"], description="Permissions: read, write, admin")
    expires_days: Optional[int] = Field(default=365, description="Expiration in days (None = never)")


class CreateTokenResponse(BaseModel):
    id: str
    name: str
    token: str  # raw token — shown once
    token_prefix: str
    org_id: str
    model_id: Optional[str] = None
    permissions: List[str]
    expires_at: Optional[datetime] = None


class TokenListResponse(BaseModel):
    tokens: List[Dict[str, Any]]


class RevokeTokenResponse(BaseModel):
    id: str
    status: str


# ── Routes ──

@router.post("", response_model=CreateTokenResponse)
async def create_token(
    org_id: str,
    request: CreateTokenRequest,
    current_user: AuthenticatedUser = Depends(validate_org_owner),
    db: AsyncSession = Depends(get_db),
) -> CreateTokenResponse:
    """Create a new API token. The raw token is returned once — store it securely."""
    raw_token = f"ada_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_prefix = raw_token[:12]

    expires_at = None
    if request.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_days)

    db_token = Token(
        name=request.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        org_id=org_id,
        model_id=request.model_id,
        permissions=request.permissions,
        expires_at=expires_at,
    )
    db.add(db_token)
    await db.flush()

    return CreateTokenResponse(
        id=str(db_token.id),
        name=request.name,
        token=raw_token,
        token_prefix=token_prefix,
        org_id=org_id,
        model_id=request.model_id,
        permissions=request.permissions,
        expires_at=expires_at,
    )


@router.get("")
async def list_tokens(
    org_id: str,
    current_user: AuthenticatedUser = Depends(validate_org_owner),
    db: AsyncSession = Depends(get_db),
) -> TokenListResponse:
    """List active tokens for this org."""
    result = await db.execute(
        select(Token).where(
            Token.org_id == org_id,
            Token.status == "active",
        ).order_by(Token.created_at.desc())
    )
    tokens = result.scalars().all()

    return TokenListResponse(tokens=[
        {
            "id": str(t.id),
            "name": t.name,
            "token_prefix": t.token_prefix or "—",
            "org_id": t.org_id,
            "model_id": t.model_id,
            "permissions": t.permissions,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        }
        for t in tokens
    ])


@router.delete("/{token_id}", response_model=RevokeTokenResponse)
async def revoke_token(
    org_id: str,
    token_id: str,
    current_user: AuthenticatedUser = Depends(validate_org_owner),
    db: AsyncSession = Depends(get_db),
) -> RevokeTokenResponse:
    """Revoke a token by ID."""
    result = await db.execute(
        select(Token).where(
            Token.id == token_id,
            Token.org_id == org_id,
            Token.status == "active",
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise HTTPException(status_code=404, detail="Token not found or already revoked")

    db_token.status = "revoked"
    db_token.revoked_at = datetime.utcnow()

    return RevokeTokenResponse(id=token_id, status="revoked")
