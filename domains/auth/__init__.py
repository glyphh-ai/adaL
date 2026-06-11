"""
Authentication Domain.

Handles JWT validation, authorization, and security weight computation.
"""

from domains.auth.service import AuthService, Permission, User

__all__ = ["AuthService", "Permission", "User"]
