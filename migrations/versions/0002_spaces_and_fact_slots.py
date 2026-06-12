"""Spaces + fact_slots: the SQL query surface and multi-space scoping.

Revision ID: 0002
Revises: 0001_initial
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ada_thoughts",
        sa.Column("space_id", sa.String(64), nullable=False,
                  server_default="main"),
    )
    op.create_index("ix_ada_thoughts_space_id", "ada_thoughts", ["space_id"])

    op.create_table(
        "fact_slots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("space_id", sa.String(64), nullable=False,
                  server_default="main"),
        sa.Column("thought_id", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(255), nullable=True),
        sa.Column("layer", sa.String(32), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("predicate", sa.String(255), nullable=True),
        sa.Column("key", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Integer(), nullable=False,
                  server_default="1"),
    )
    op.create_index("idx_slots_lrv", "fact_slots",
                    ["space_id", "layer", "role", "value", "is_current"])
    op.create_index("idx_slots_entity", "fact_slots",
                    ["space_id", "entity", "is_current"])
    op.create_index("idx_slots_entity_lr", "fact_slots",
                    ["space_id", "entity", "layer", "role"])
    op.create_index("idx_slots_key", "fact_slots",
                    ["space_id", "key", "version"])
    op.create_index("idx_slots_thought", "fact_slots", ["thought_id"])


def downgrade() -> None:
    op.drop_table("fact_slots")
    op.drop_index("ix_ada_thoughts_space_id", "ada_thoughts")
    op.drop_column("ada_thoughts", "space_id")
