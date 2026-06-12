"""
Authentication Service for Ada Runtime.

Handles database token validation, authorization checks, and security weight computation.
Supports three deployment modes: local (no auth), self-hosted, and cloud.

Permissions are keyed by org_id. No namespace concept.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.models.db_models import Token
from infrastructure.config import get_settings
from shared.exceptions import (
    AuthenticationException,
    AuthorizationException,
)

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Permission levels for operations."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


@dataclass
class User:
    """Authenticated user with org-scoped permissions and resolved tier."""
    user_id: str
    org_permissions: Dict[str, Set[Permission]] = field(default_factory=dict)  # org_id -> permissions
    org_id: Optional[str] = None
    email: Optional[str] = None
    token_type: str = "token"  # token or local
    tier: str = "free"
    allowed_space: Optional[str] = None  # None = all spaces; else bound to one

    def has_permission(self, org_id: str, permission: Permission) -> bool:
        """Check if user has permission for org."""
        # Wildcard grants access to all orgs
        if "*" in self.org_permissions:
            if permission in self.org_permissions["*"]:
                return True
        if org_id not in self.org_permissions:
            return False
        return permission in self.org_permissions[org_id]

    def can_read(self, org_id: str) -> bool:
        return self.has_permission(org_id, Permission.READ)

    def can_write(self, org_id: str) -> bool:
        return self.has_permission(org_id, Permission.WRITE)

    def is_admin(self, org_id: str) -> bool:
        return self.has_permission(org_id, Permission.ADMIN)


class AuthService:
    """
    Authentication and authorization service.

    Permissions are keyed by org_id. Access checks take org_id and model_id
    as separate parameters.
    """

    def __init__(self, session: Optional[AsyncSession] = None):
        self._session = session
        self._settings = get_settings()

    async def validate_token(self, token: str) -> User:
        """Validate a token and return the authenticated user."""
        if not token:
            raise AuthenticationException("No token provided")

        if token.startswith("Bearer "):
            token = token[7:]

        # Validate via database token lookup
        if self._session:
            return await self._validate_db_token(token)

        # No session available — try standalone lookup
        try:
            from infrastructure.database import async_session_maker
            async with async_session_maker() as session:
                try:
                    self._session = session
                    return await self._validate_db_token(token)
                finally:
                    self._session = None  # never cache a closed session
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            raise AuthenticationException("Invalid or expired token")

    async def _validate_db_token(self, token: str) -> User:
        """Validate a database token by SHA-256 hash lookup."""
        token_hash = self._hash_token(token)

        result = await self._session.execute(
            select(Token).where(
                Token.token_hash == token_hash,
                Token.status == "active",
            )
        )
        db_token = result.scalar_one_or_none()

        if not db_token:
            raise AuthenticationException("Invalid token")

        if db_token.expires_at and db_token.expires_at < datetime.utcnow():
            raise AuthenticationException("Token has expired")

        permissions = {Permission(p) for p in db_token.permissions}

        if db_token.org_id:
            org_permissions = {db_token.org_id: permissions}
        else:
            org_permissions = {"*": permissions}

        return User(
            user_id=f"token:{db_token.id}",
            org_permissions=org_permissions,
            org_id=db_token.org_id,
            token_type="token",
            allowed_space=db_token.model_id,  # model_id column carries the space binding
        )

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def validate_session(self, raw_session: str) -> User:
        """Validate a workbench session cookie and return the same User
        the token path produces — one enforcement path for both
        principals. Sessions pending a forced password rotation are
        rejected here: until root rotates, only /auth works."""
        from domains.auth.users import ROLE_PERMISSIONS, validate_session

        from infrastructure.database import async_session_maker
        async with async_session_maker() as session:
            resolved = await validate_session(session, raw_session)
            if resolved is None:
                raise AuthenticationException("Invalid or expired session")
            sess, wb_user = resolved
            if wb_user is not None and wb_user.must_change_password:
                raise AuthenticationException(
                    "Password change required before anything else")
            permissions = {Permission(p)
                           for p in ROLE_PERMISSIONS.get(sess.role, ["read"])}
            return User(
                user_id=f"session:{sess.username}",
                org_permissions={"*": permissions},
                token_type="session",
                allowed_space=sess.allowed_space,
            )

    async def check_access(
        self,
        user: User,
        org_id: str,
        model_id: str,
        operation: str,
    ) -> bool:
        """
        Check if user has permission for operation on org/model.

        Raises AuthorizationException if not authorized.
        """
        permission_map = {
            "read": Permission.READ,
            "write": Permission.WRITE,
            "admin": Permission.ADMIN,
            "search": Permission.READ,
            "create": Permission.WRITE,
            "update": Permission.WRITE,
            "delete": Permission.WRITE,
            "deploy": Permission.ADMIN,
            "unload": Permission.ADMIN,
            "config": Permission.ADMIN,
        }

        required_permission = permission_map.get(operation, Permission.READ)

        # Check wildcard access
        if "*" in user.org_permissions:
            if required_permission in user.org_permissions["*"]:
                return True

        # Check specific org access
        if user.has_permission(org_id, required_permission):
            return True

        # Admin implies all
        if user.is_admin(org_id):
            return True

        # Write implies read
        if required_permission == Permission.READ and user.can_write(org_id):
            return True

        raise AuthorizationException(
            user_id=user.user_id,
            org_id=org_id,
            model_id=model_id,
            operation=operation,
        )

    def compute_security_weight(
        self,
        user: User,
        glyph_metadata: Dict[str, Any],
    ) -> float:
        """
        Compute security weight for a glyph based on user permissions.

        Returns 0.0 (no access) to 1.0 (full access).
        """
        security_level = glyph_metadata.get("security_level", 0)
        required_clearance = glyph_metadata.get("required_clearance", [])

        if "*" in user.org_permissions and Permission.ADMIN in user.org_permissions["*"]:
            return 1.0

        user_orgs = set(user.org_permissions.keys())
        if required_clearance:
            if not any(c in user_orgs for c in required_clearance):
                return 0.0

        if security_level == 0:
            return 1.0
        elif security_level == 1:
            return 0.8 if Permission.READ in user.org_permissions.get("*", set()) else 0.5
        elif security_level == 2:
            return 0.6 if Permission.WRITE in user.org_permissions.get("*", set()) else 0.3
        else:
            return 0.4 if Permission.ADMIN in user.org_permissions.get("*", set()) else 0.1

    def require_auth(self) -> bool:
        return True
