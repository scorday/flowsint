"""Persist project-specific catalog visibility overrides.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
"""

import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enricher_visibility",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("enricher_key", sa.String(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column(
            "project_id", sa.String(), nullable=False, server_default="__standalone__"
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "enricher_key", name="uq_enricher_visibility"
        ),
    )
    op.create_index(
        "ix_enricher_visibility_project_id", "enricher_visibility", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_enricher_visibility_project_id", table_name="enricher_visibility")
    op.drop_table("enricher_visibility")
