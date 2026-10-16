"""Exercise upgrade/downgrade against a disposable database, independent of ORM create_all."""

import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, inspect, select


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


def test_global_visibility_consolidates_conflicts_without_changing_legacy_rows():
    def load(filename, module_name):
        path = Path(__file__).parents[1] / "alembic/versions" / filename
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    legacy_migration = load("f5a6b7c8d9e0_enricher_visibility.py", "legacy_visibility")
    migration = load("a6b7c8d9e0f1_global_enricher_visibility.py", "global_visibility")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            legacy_migration.upgrade()
            legacy = Table("enricher_visibility", MetaData(), autoload_with=connection)
            original = [
                dict(
                    id=uuid4().hex,
                    enricher_key=key,
                    project_id=project,
                    is_visible=visible,
                    created_by="previous-admin",
                )
                for key, project, visible in [
                    ("builtin:conflict", "a", True),
                    ("builtin:conflict", "b", False),
                    ("builtin:enabled", "a", True),
                    ("builtin:enabled", "b", True),
                    ("template:one", "__standalone__", False),
                ]
            ]
            connection.execute(legacy.insert(), original)
            before = list(connection.execute(select(legacy)).mappings())
            migration.upgrade()
            global_table = Table(
                "enricher_visibility_global", MetaData(), autoload_with=connection
            )
            assert "project_id" not in global_table.c
            assert dict(
                connection.execute(
                    select(global_table.c.enricher_key, global_table.c.is_visible)
                ).all()
            ) == {
                "builtin:conflict": False,
                "builtin:enabled": True,
                "template:one": False,
            }
            assert inspect(connection).get_unique_constraints(
                "enricher_visibility_global"
            )[0]["column_names"] == ["enricher_key"]
            assert list(connection.execute(select(legacy)).mappings()) == before
            migration.downgrade()
            assert not inspect(connection).has_table("enricher_visibility_global")
            assert list(connection.execute(select(legacy)).mappings()) == before
    engine.dispose()
