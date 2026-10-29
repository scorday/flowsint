"""Consolidate project overrides into a global catalog policy.

The previous table remains intact as the migration/rollback snapshot. When
projects disagree, hiding wins so an explicitly hidden enricher stays hidden.
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enricher_visibility_global",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("enricher_key", sa.String(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enricher_key", name="uq_enricher_visibility_global"),
    )
    connection = op.get_bind()
    legacy = sa.table(
        "enricher_visibility",
        sa.column("enricher_key", sa.String()),
        sa.column("is_visible", sa.Boolean()),
    )
    grouped = sa.select(
        legacy.c.enricher_key,
        sa.func.min(sa.case((legacy.c.is_visible.is_(True), 1), else_=0)).label(
            "visible"
        ),
    ).group_by(legacy.c.enricher_key)
    target = sa.table(
        "enricher_visibility_global",
        sa.column("id", sa.Uuid()),
        sa.column("enricher_key", sa.String()),
        sa.column("is_visible", sa.Boolean()),
    )
    for row in connection.execute(grouped).mappings():
        connection.execute(
            target.insert().values(
                id=uuid4(),
                enricher_key=row["enricher_key"],
                is_visible=bool(row["visible"]),
            )
        )


def downgrade() -> None:
    op.drop_table("enricher_visibility_global")
