"""
API Routes for Ada.
"""

from api.routes.auth import router as auth_router
from api.routes.health import router as health_router
from api.routes.tokens import router as tokens_router

__all__ = [
    "auth_router",
    "health_router",
    "tokens_router",
]
