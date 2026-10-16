"""Exercise upgrade/downgrade against a disposable database, independent of ORM create_all."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_visibility_migration_round_trip():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/f5a6b7c8d9e0_enricher_visibility.py"
    )
    spec = importlib.util.spec_from_file_location("visibility_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            schema = inspect(connection)
            assert schema.has_table("enricher_visibility")
            assert {
                column["name"] for column in schema.get_columns("enricher_visibility")
            } == {"id", "enricher_key", "is_visible", "project_id", "created_by"}
            assert schema.get_unique_constraints("enricher_visibility")[0][
                "column_names"
            ] == ["project_id", "enricher_key"]
            migration.downgrade()
            assert not inspect(connection).has_table("enricher_visibility")
    engine.dispose()
