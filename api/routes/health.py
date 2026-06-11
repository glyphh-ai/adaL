"""
Health Check API Routes for Ada Runtime.

Single liveness probe endpoint.
"""

import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter

from ada import __version__

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Liveness probe. Returns healthy if the service is running."""
    return {
        "status": "healthy",
        "version": __version__,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
