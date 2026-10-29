"""Durable AVL4 card import intents and project-scoped material snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avl4_materials",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("material_key", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sketch_id",
            sa.Uuid(),
            sa.ForeignKey("sketches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
    )
    op.create_index("ix_avl4_materials_project_id", "avl4_materials", ["project_id"])
    op.create_table(
        "avl4_import_operations",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "material_id",
            sa.Uuid(),
            sa.ForeignKey("avl4_materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "project_id", "operation_id", name="uq_avl4_import_operation"
        ),
    )
    op.create_index(
        "ix_avl4_import_operations_project_id", "avl4_import_operations", ["project_id"]
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM avl4_materials LIMIT 1")).first():
        raise RuntimeError("Export/remove imported materials before downgrade")
    op.drop_table("avl4_import_operations")
    op.drop_table("avl4_materials")
