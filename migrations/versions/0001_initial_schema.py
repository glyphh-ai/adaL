"""Initial schema — clean baseline for the Ada runtime.

Two tables: tokens (API access) and ada_thoughts (persistent memory).
No vector columns, no extensions — plain relational storage.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tokens ──
    op.create_table(
        "tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(12), nullable=True),
        sa.Column("org_id", sa.String(255), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), server_default='["read", "write"]'),
        sa.Column("status", sa.String(50), server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_token_status", "tokens", ["status"])
    op.create_index("idx_token_org", "tokens", ["org_id"])
    op.create_index("idx_token_org_model", "tokens", ["org_id", "model_id"])

    # ── ada_thoughts ──
    op.create_table(
        "ada_thoughts",
        sa.Column("thought_id", sa.String(64), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("speaker", sa.String(50), nullable=False, server_default="incoming"),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("last_accessed", sa.Float(), nullable=False),
        sa.Column("extra_data", postgresql.JSONB(), server_default="{}"),
        sa.Column("archived", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_thought_accessed", "ada_thoughts", [sa.text("last_accessed DESC")]
    )
    op.create_index("idx_thought_archived", "ada_thoughts", ["archived"])


def downgrade() -> None:
    op.drop_table("ada_thoughts")
    op.drop_table("tokens")
