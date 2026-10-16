"""Operator bootstrap never creates a graph before SQL succeeds or prints secrets."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from alembic.script import ScriptDirectory

from flowsint_core.avl4_import import bootstrap


def test_readiness_accepts_the_deployed_migration_head():
    migrations = Path(__file__).resolve().parents[3] / "flowsint-api" / "alembic"
    assert bootstrap.SQL_REVISION == ScriptDirectory(str(migrations)).get_current_head()


def test_initialize_orders_migration_constraint_and_readiness(monkeypatch):
    for key in ("NEO4J_URI_BOLT", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.setenv(key, "test-value")
    session = MagicMock()
    driver = MagicMock()
    driver.__enter__.return_value = driver
    driver.session.return_value.__enter__.return_value = session
    order = []
    with (
        patch.object(
            bootstrap.subprocess, "run", side_effect=lambda *a, **k: order.append("sql")
        ) as sql,
        patch.object(bootstrap.GraphDatabase, "driver", return_value=driver),
        patch.object(
            bootstrap, "check_storage", side_effect=lambda: order.append("ready")
        ),
    ):
        session.run.side_effect = lambda *args: order.append("graph") or MagicMock()
        bootstrap.initialize()
    assert order == ["sql", "graph", "ready"]
    sql.assert_called_once_with(
        ["alembic", "upgrade", "head"], check=True, capture_output=True
    )
    session.run.assert_called_once_with(bootstrap.CONSTRAINT)


def test_failed_sql_never_initializes_graph():
    with (
        patch.object(
            bootstrap.subprocess, "run", side_effect=RuntimeError("private-password")
        ),
        patch.object(bootstrap.GraphDatabase, "driver") as graph,
    ):
        with pytest.raises(RuntimeError):
            bootstrap.initialize()
    graph.assert_not_called()


def test_readiness_does_not_run_migrations_or_ddl(monkeypatch):
    monkeypatch.setattr("sys.argv", ["bootstrap", "--check"])
    with (
        patch.object(bootstrap, "check_storage") as check,
        patch.object(bootstrap, "initialize") as init,
    ):
        assert bootstrap.main() == 0
    check.assert_called_once()
    init.assert_not_called()


def test_bootstrap_failure_output_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["bootstrap"])
    with patch.object(
        bootstrap, "initialize", side_effect=RuntimeError("private-password")
    ):
        assert bootstrap.main() == 1
    output = capsys.readouterr()
    assert "private-password" not in output.err
    assert "failed" in output.err
