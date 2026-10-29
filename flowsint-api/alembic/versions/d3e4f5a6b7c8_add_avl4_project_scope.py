"""Add AVL4 project scope and audit identities; standalone rows stay isolated.

Revision ID: d3e4f5a6b7c8
Revises: c7d1f0a92b3e
"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c7d1f0a92b3e"
branch_labels = None
depends_on = None

TABLES = (
    "feedbacks",
    "investigations",
    "logs",
    "scans",
    "sketches",
    "flows",
    "analyses",
    "chats",
    "messages",
    "keys",
    "custom_types",
    "enricher_templates",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "project_id",
                sa.String(),
                nullable=False,
                server_default="__standalone__",
            ),
        )
        op.add_column(table, sa.Column("created_by", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    for table in ("keys", "custom_types", "enricher_templates"):
        op.alter_column(table, "owner_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    # A downgrade cannot silently drop project data or invent local Profiles.
    bind = op.get_bind()
    for table in TABLES:
        if bind.execute(
            sa.text(
                f"SELECT 1 FROM {table} WHERE project_id <> '__standalone__' LIMIT 1"
            )
        ).first():
            raise RuntimeError("Remove/export AVL4 project data before downgrading")
    for table in ("keys", "custom_types", "enricher_templates"):
        op.alter_column(table, "owner_id", existing_type=sa.Uuid(), nullable=False)
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_column(table, "created_by")
        op.drop_column(table, "project_id")
