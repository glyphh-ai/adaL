"""
API Routes for Ada.
"""

from api.routes.health import router as health_router
from api.routes.tokens import router as tokens_router

__all__ = [
    "health_router",
    "tokens_router",
]
