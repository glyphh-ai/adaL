"""
Ada configuration.

All configuration is read from environment variables / .env with sensible
defaults. Storage is SQLite by default; setting DATABASE_URL to a Postgres URL
switches the runtime to the Postgres backend (see resolved_storage_backend).
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Ada configuration."""

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8002, description="Server port")

    # Database — SQLite by default; a postgres:// URL enables Postgres.
    database_url: Optional[str] = Field(
        default=None,
        description="DB URL. Unset → SQLite at ~/.ada/ada.db. "
                    "postgresql://… → Postgres backend.",
    )

    # Storage engine: "memory" (in-process indexes, default) or "sql"
    # (fact_slots-backed, O(1) boot, for very large corpora).
    storage_mode: str = Field(
        default="memory", description="memory | sql",
        validation_alias=AliasChoices("ADA_STORAGE", "ADA_STORAGE_MODE"),
    )

    # Auth — when true, /mcp requires a Bearer token (ada token create).
    auth_required: bool = Field(
        default=False, description="Require tokens on /mcp",
        validation_alias=AliasChoices("ADA_AUTH_REQUIRED", "AUTH_REQUIRED"),
    )

    # Dev flags
    enable_docs: bool = Field(default=False, description="Enable /docs endpoint")
    cors_allow_all: bool = Field(default=True, description="Allow all CORS origins")

    # Storage — auto-resolved from DATABASE_URL (see resolved_storage_backend).
    storage_backend: str = Field(default="sqlite")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        from pathlib import Path
        db_dir = Path.home() / ".ada"
        db_dir.mkdir(exist_ok=True)
        return f"sqlite+aiosqlite:///{db_dir}/ada.db"

    @property
    def resolved_storage_backend(self) -> str:
        # postgres when pointed at a persistent Postgres; SQLite otherwise.
        url = self.resolved_database_url.lower()
        if "postgres" in url:
            return "postgres"
        return "sqlite"

    # JWT (for token auth)
    jwt_secret_key: Optional[str] = Field(default=None)

    # Vector dimension
    max_vector_dimension: int = Field(default=65536)

    # Edge generation
    edge_generation_strategy: str = Field(default="lazy")
    edge_ttl_hours: int = Field(default=24)

    # Beam search
    default_beam_width: int = Field(default=5)
    default_max_tree_depth: int = Field(default=3)

    # Logging
    log_level: str = Field(default="INFO")

    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
    )
    cors_origins_production: List[str] = Field(default=[])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_settings() -> None:
    """Validate settings on startup."""
    get_settings()  # triggers pydantic validation
