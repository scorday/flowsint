"""Exercise Celery's producer validation as well as worker project admission."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from celery.backends.cache import CacheBackend
from kombu import Connection

from flowsint_core.core.project_scope import current_scope
from flowsint_core.tasks.exploration import apply_exploration, search_investigation


@pytest.mark.parametrize("task", [search_investigation, apply_exploration])
def test_exploration_publishes_context_and_worker_consumes_it(task, monkeypatch):
    backend = CacheBackend(app=task.app, backend="memory")
    monkeypatch.setattr(task, "backend", backend)
    monkeypatch.setattr(task.app, "_backend", backend)
    context = {"user_id": "alice", "project_id": "project-a"}
    kwargs = {
        "result_id": str(uuid4()),
        "sketch_id": str(uuid4()),
        "actor": "alice",
        "avl4_context": context,
    }
    if task is apply_exploration:
        kwargs.update(action="create", title="All selected")
    queue = "exploration-dispatch-" + str(uuid4())
    # Keep the real Task.apply_async and its generated __header__ validation.
    with Connection("memory://") as connection:
        task.apply_async(kwargs=kwargs, connection=connection, queue=queue)
        with connection.SimpleQueue(queue) as messages:
            message = messages.get(block=False)
            published = message.payload[1]
            message.ack()
        assert published == kwargs
        with pytest.raises(TypeError, match="unexpected keyword"):
            task.apply_async(
                kwargs={**kwargs, "unknown_option": True},
                connection=connection,
                queue=queue,
            )

    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    verify = MagicMock()
    monkeypatch.setattr("flowsint_core.tasks.project.verify_actor_sync", verify)
    session = MagicMock()
    session.__enter__.return_value = session
    monkeypatch.setattr("flowsint_core.core.postgre_db.SessionLocal", lambda: session)
    scopes = []

    def body(**received):
        assert "avl4_context" not in received
        scopes.append(current_scope())

    monkeypatch.setattr(task, "run", body)
    task.apply(kwargs=published, throw=True)
    verify.assert_called_once_with("alice", "project-a", None)
    assert scopes[0].worker and scopes[0].project_id == "project-a"
    assert current_scope() is None

    verify.side_effect = PermissionError("membership revoked")
    with pytest.raises(PermissionError, match="membership revoked"):
        task.apply(kwargs=published, throw=True)
    assert len(scopes) == 1
    assert current_scope() is None
