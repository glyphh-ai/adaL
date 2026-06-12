"""
SQLAlchemy database models for the Ada runtime.

Two tables:
  tokens       — API tokens for runtime access (org-scoped)
  ada_thoughts — Ada's persistent memory (content + structured metadata)
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Use JSONB on PostgreSQL, plain JSON on SQLite/others
JSONType = JSON().with_variant(JSONB(), "postgresql")

from infrastructure.database.connection import Base


class Token(Base):
    """
    Token model - API tokens for runtime access.

    Tokens are scoped to org_id (required) and optionally model_id.
    A token with model_id=None grants access to all models in the org.
    Stored as SHA-256 hashes — the raw token is shown once at creation.
    """
    __tablename__ = "tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True)
    token_prefix = Column(String(12), nullable=True)  # first 8 chars for identification
    org_id = Column(String(255), nullable=False, index=True)
    model_id = Column(String(255), nullable=True, index=True)  # nullable for org-wide tokens
    permissions = Column(JSONType, default=lambda: ["read", "write"])
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_token_status", status),
        Index("idx_token_org", org_id),
        Index("idx_token_org_model", org_id, model_id),
    )

    def __repr__(self) -> str:
        return f"<Token(id={self.id}, org_id={self.org_id}, status={self.status})>"


class WorkbenchUser(Base):
    """
    Human login for the workbench (the management UI).

    Users are the human principal; tokens are the machine principal.
    Both resolve onto the same permission layer. First boot seeds
    root/root with must_change_password=1 — the workbench refuses to
    render anything else until the password is rotated.
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    username = Column(String(64), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="admin")  # admin | member | viewer
    allowed_space = Column(String(64), nullable=True)  # None = all spaces
    must_change_password = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<WorkbenchUser({self.username}, role={self.role})>"


class WorkbenchSession(Base):
    """
    Browser session for a workbench login.

    Stored as SHA-256 hashes — the raw session token lives only in the
    httponly cookie. user_id is nullable so the control plane can mint
    short-lived space-scoped sessions with no local user behind them.
    """
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    token_hash = Column(String(255), nullable=False, unique=True)
    user_id = Column(String(36), nullable=True, index=True)
    username = Column(String(64), nullable=False)  # denormalized for display
    role = Column(String(16), nullable=False, default="admin")
    allowed_space = Column(String(64), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class AdaThought(Base):
    """
    Ada's persistent thought memory.

    Each thought is a natural language statement plus its structured
    metadata (universal-schema slots, versioned-key chain fields).
    Archived thoughts remain in the DB but are excluded from active recall.
    """
    __tablename__ = "ada_thoughts"

    thought_id = Column(String(64), primary_key=True)
    space_id = Column(String(64), nullable=False, default="main", index=True)
    content = Column(Text, nullable=False)
    speaker = Column(String(50), nullable=False, default="incoming")
    access_count = Column(Integer, default=0, nullable=False)
    created_at = Column(Float, nullable=False)
    last_accessed = Column(Float, nullable=False)
    extra_data = Column(JSONType, default=dict)
    archived = Column(Integer, default=0, nullable=False)  # 1 = cold storage

    __table_args__ = (
        Index("idx_thought_accessed", last_accessed.desc()),
        Index("idx_thought_archived", archived),
    )

    def __repr__(self) -> str:
        return f"<AdaThought({self.thought_id}, '{self.content[:30]}')>"


class FactSlot(Base):
    """
    One row per filled universal-schema slot — the SQL query surface.

    Maintained at write time alongside ada_thoughts. The closed op set
    compiles to fixed templates over this table; `predicate` is
    denormalized from relational.predicate so shared slots
    (relational.object holds jobs AND hobbies AND pets) can be
    disambiguated without a self-join.
    """
    __tablename__ = "fact_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    space_id = Column(String(64), nullable=False, default="main")
    thought_id = Column(String(64), nullable=False)
    entity = Column(String(255), nullable=True)     # normalized entity name
    layer = Column(String(32), nullable=False)
    role = Column(String(32), nullable=False)
    value = Column(Text, nullable=False)            # normalized lowercase
    predicate = Column(String(255), nullable=True)  # relational.predicate, normalized
    key = Column(String(255), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    is_current = Column(Integer, default=1, nullable=False)

    __table_args__ = (
        Index("idx_slots_lrv", space_id, layer, role, value, is_current),
        Index("idx_slots_entity", space_id, entity, is_current),
        Index("idx_slots_key", space_id, key, version),
        Index("idx_slots_thought", thought_id),
    )
