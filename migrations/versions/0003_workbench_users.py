"""Workbench users + sessions: human auth for the management UI.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False,
                  server_default="admin"),
        sa.Column("allowed_space", sa.String(64), nullable=True),
        sa.Column("must_change_password", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False,
                  server_default="admin"),
        sa.Column("allowed_space", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("users")
