import pytest
from celery import Celery

from flowsint_core.core.platform_auth import AccessDenied
from flowsint_core.core.project_scope import current_scope
from flowsint_core.tasks.project import Avl4ProjectTask


class Probe(Avl4ProjectTask):
    name = "avl4-admission-probe"

    def run(self):
        scope = current_scope()
        return scope.user_id, scope.project_id


def test_worker_requires_context_and_revalidates_before_execution(monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    Probe.bind(Celery("admission-test"))
    task = Probe()
    with pytest.raises(PermissionError):
        task()
    calls = []

    def verify(user_id, project_id, private_project_id):
        calls.append((user_id, project_id))

    monkeypatch.setattr("flowsint_core.tasks.project.verify_actor_sync", verify)
    assert task(avl4_context={"user_id": "alice", "project_id": "project-a"}) == (
        "alice",
        "project-a",
    )
    assert calls == [("alice", "project-a")]
    assert current_scope() is None

    def revoked(*args):
        raise AccessDenied

    monkeypatch.setattr("flowsint_core.tasks.project.verify_actor_sync", revoked)
    with pytest.raises(AccessDenied):
        task(avl4_context={"user_id": "alice", "project_id": "project-a"})
    assert current_scope() is None


def test_revocation_is_checked_before_graph_writes(monkeypatch):
    from unittest.mock import MagicMock

    from flowsint_core.core.graph.connection import Neo4jConnection
    from flowsint_core.core.project_scope import ProjectScope, project_scope

    def revoked(*args):
        raise AccessDenied

    monkeypatch.setattr("flowsint_core.core.platform_auth.verify_actor_sync", revoked)
    connection = Neo4jConnection()
    driver = MagicMock()
    monkeypatch.setattr(connection, "_driver", driver)
    with project_scope(
        ProjectScope(user_id="alice", project_id="project-a", worker=True)
    ):
        with pytest.raises(AccessDenied):
            connection.execute_write("CREATE (n)")
    driver.session.assert_not_called()


def test_celery_tracer_consumes_context_before_calling_task_run(monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    monkeypatch.setattr(
        "flowsint_core.tasks.project.verify_actor_sync", lambda *args: None
    )
    app = Celery("tracer-test", broker="memory://", backend="cache+memory://")
    task = app.register_task(Probe())
    result = task.apply(
        kwargs={"avl4_context": {"user_id": "alice", "project_id": "project-a"}}
    )
    assert result.get(propagate=True) == ("alice", "project-a")
    assert current_scope() is None


def test_worker_rejects_a_sketch_from_another_project(db_session, monkeypatch):
    from flowsint_core.core.project_scope import ProjectScope, project_scope
    from flowsint_core.core.services import (
        create_investigation_service,
        create_sketch_service,
    )

    with project_scope(ProjectScope(user_id="alice", project_id="project-a")):
        inv = create_investigation_service(db_session).create("Case", "", "alice")
        sketch_id = (
            create_sketch_service(db_session).create("Graph", "", inv.id, "alice").id
        )
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    monkeypatch.setattr(
        "flowsint_core.tasks.project.verify_actor_sync", lambda *args: None
    )
    monkeypatch.setattr(
        "flowsint_core.core.postgre_db.SessionLocal", lambda: db_session
    )
    app = Celery("foreign-sketch-test", broker="memory://", backend="cache+memory://")
    task = app.register_task(Probe())
    with pytest.raises(PermissionError, match="sketch does not belong"):
        task(
            "unused",
            [],
            str(sketch_id),
            avl4_context={"user_id": "alice", "project_id": "project-b"},
        )
    assert current_scope() is None
