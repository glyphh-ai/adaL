"""
Authentication middleware for Ada Runtime.

Dual auth: accepts both database-backed API tokens (ada_xxxx) and
Platform JWTs (HS256, from browser/CLI login).

- CLI/API tools use database tokens created via ada token create
- Browser dashboard and CLI use Platform JWTs obtained via device auth flow
- When JWT_SECRET_KEY is set: validates locally with signature verification
- When JWT_SECRET_KEY is unset: validates via Platform GET /auth/me (cached 5min)
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from infrastructure.config import get_settings

logger = logging.getLogger(__name__)

# Cache Platform JWT validations to avoid hitting Platform on every request.
# Maps token_hash -> (AuthenticatedUser, expiry_timestamp)
_platform_jwt_cache: dict[str, tuple["AuthenticatedUser", float]] = {}
_CACHE_TTL = 300  # 5 minutes

PLATFORM_URL = "https://api.ada.ai/api/v1"


@dataclass
class AuthenticatedUser:
    """Authenticated user context from either a database token or Platform JWT."""

    user_id: str
    org_id: str
    role: str
    plan: str = "free"


# HTTP Bearer security scheme (auto_error=False to handle missing tokens manually)
security = HTTPBearer(auto_error=False)


def _is_jwt(token: str) -> bool:
    """Check if a token looks like a JWT (base64url header.payload.signature)."""
    return token.startswith("eyJ") and token.count(".") == 2


def _validate_platform_jwt(token: str) -> AuthenticatedUser:
    """Validate a Platform JWT.

    If jwt_secret_key is configured, validates locally (HS256).
    Otherwise, validates via Platform API call (cached for 5 minutes).
    """
    settings = get_settings()

    # If we have the shared secret, validate locally (fast path)
    if settings.jwt_secret_key:
        return _validate_jwt_locally(token, settings.jwt_secret_key)

    # No shared secret — validate via Platform API (cached)
    return _validate_jwt_via_platform(token)


def _validate_jwt_locally(token: str, secret_key: str) -> AuthenticatedUser:
    """Validate JWT using the shared secret (HS256)."""
    try:
        import jwt

        payload = jwt.decode(token, secret_key, algorithms=["HS256"])

        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return AuthenticatedUser(
            user_id=payload.get("sub", "unknown"),
            org_id=payload.get("org_id", "default"),
            role=payload.get("role", "user"),
            plan=payload.get("plan", "free"),
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validate_jwt_via_platform(token: str) -> AuthenticatedUser:
    """Validate JWT by calling Platform GET /auth/me. Results cached per token."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Check cache
    cached = _platform_jwt_cache.get(token_hash)
    if cached:
        user, expires_at = cached
        if time.time() < expires_at:
            return user
        # Expired cache entry — remove it
        _platform_jwt_cache.pop(token_hash, None)

    # Call Platform
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            res = client.get(
                f"{PLATFORM_URL}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        if res.status_code == 401:
            _platform_jwt_cache.pop(token_hash, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        res.raise_for_status()
        data = res.json()

        user = AuthenticatedUser(
            user_id=str(data.get("id", data.get("user_id", "unknown"))),
            org_id=str(data.get("org_id", "default")),
            role=data.get("role", "user"),
            plan=data.get("plan", "free"),
        )

        # Cache the result
        _platform_jwt_cache[token_hash] = (user, time.time() + _CACHE_TTL)
        return user

    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot reach authentication service. Is the platform reachable?",
        )
    except Exception as e:
        logger.error(f"Platform JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _validate_db_token(token: str) -> AuthenticatedUser:
    """Validate a token by SHA-256 hash lookup in the database."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    try:
        from infrastructure.database import async_session_maker
        from sqlalchemy import select
        from domains.models.db_models import Token

        async with async_session_maker() as session:
            result = await session.execute(
                select(Token).where(
                    Token.token_hash == token_hash,
                    Token.status == "active",
                )
            )
            db_token = result.scalar_one_or_none()

            if not db_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or revoked token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Check expiry
            if db_token.expires_at and db_token.expires_at < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Determine role from permissions
            permissions = db_token.permissions or ["read"]
            role = "admin" if "admin" in permissions else "service"

            return AuthenticatedUser(
                user_id=f"token:{db_token.id}",
                org_id=db_token.org_id,
                role=role,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service unavailable",
        )


async def _validate_token(token: str) -> AuthenticatedUser:
    """Route to JWT or database token validation based on token format."""
    if _is_jwt(token):
        return _validate_platform_jwt(token)
    return await _validate_db_token(token)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthenticatedUser:
    """Validate token and extract user context."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _validate_token(credentials.credentials)


async def require_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthenticatedUser:
    """Require a valid API token for data and query endpoints."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _validate_token(credentials.credentials)


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[AuthenticatedUser]:
    """Optional authentication - returns None if no valid token."""
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None
