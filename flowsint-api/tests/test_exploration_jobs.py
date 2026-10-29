"""Search snapshots stay private and apply only with current permissions."""

from contextlib import nullcontext
from threading import Lock
from uuid import UUID, uuid4

import fakeredis
import pytest
from test_investigation_graph_access import seed

from flowsint_core.core.graph.exploration_results import ExplorationResults
from flowsint_core.core.types import Role


@pytest.fixture
def jobs(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    lock = Lock()
    original = ExplorationResults.__init__
    monkeypatch.setattr(
        ExplorationResults,
        "__init__",
        lambda self, result_id: original(self, result_id, client),
    )
    monkeypatch.setattr(ExplorationResults, "lock", lambda self: lock)
    from flowsint_core.tasks import exploration

    monkeypatch.setattr(
        exploration.search_investigation, "apply_async", lambda **kw: None
    )
    monkeypatch.setattr(exploration.apply_exploration, "apply_async", lambda **kw: None)
    return exploration


def start(client, headers, sketch):
    base = f"/api/sketches/{sketch.id}/exploration/jobs"
    response = client.post(base, json={"root_id": "root", "depth": 1}, headers=headers)
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    result = ExplorationResults(job_id)
    result.state("running")
    result.append("nodes", [{"id": f"node{i}"} for i in range(1201)])
    result.state("completed")
    return base + "/" + job_id, result


def test_reader_can_page_select_and_cancel_but_cannot_apply(client, db_session, jobs):
    headers, sketch = seed(db_session, Role.VIEWER)
    url, result = start(client, headers, sketch)
    page = client.get(url + "/page?kind=nodes&page=20&size=50", headers=headers)
    assert page.status_code == 200
    assert len(page.json()["items"]) == 50
    assert page.json()["totals"]["nodes"] == 1201
    for action in ("attach", "create"):
        response = client.post(
            url + "/apply",
            json={"action": action, "title": "View", "revision": 0},
            headers=headers,
        )
        assert response.status_code == 403
    assert result.summary()["status"] == "completed"
    response = client.post(
        url + "/selection",
        json={"kind": "nodes", "checked": False, "ids": ["node1001"], "revision": 0},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["selected"]["nodes"] == 1200


def test_search_snapshot_is_private_and_expiry_is_explicit(client, db_session, jobs):
    headers, sketch = seed(db_session, Role.ADMIN)
    url, result = start(client, headers, sketch)
    result.redis.hset(result.key("meta"), "owner", str(uuid4()))
    assert client.get(url, headers=headers).status_code == 400
    assert client.get(url + "/page?kind=nodes", headers=headers).status_code == 400
    result.redis.delete(result.key("meta"))
    response = client.get(url, headers=headers)
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_apply_freezes_complete_selection_and_rechecks_revision(
    client, db_session, jobs
):
    headers, sketch = seed(db_session, Role.ADMIN)
    url, result = start(client, headers, sketch)
    assert (
        client.post(
            url + "/apply",
            json={"action": "create", "title": "New", "revision": 5},
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.post(
            url + "/apply",
            json={"action": "create", "title": "New", "revision": 0},
            headers=headers,
        ).status_code
        == 202
    )
    assert result.summary()["status"] == "applying"
    assert (
        client.post(
            url + "/selection",
            json={"kind": "all", "checked": False, "revision": 0},
            headers=headers,
        ).status_code
        == 400
    )


def test_worker_creates_from_every_batch_without_using_page_data(
    client, db_session, jobs, monkeypatch
):
    headers, sketch = seed(db_session, Role.ADMIN)
    url, result = start(client, headers, sketch)
    rows = []
    from unittest.mock import MagicMock

    graph = MagicMock()
    graph.attach_result_batches.side_effect = lambda batches: rows.extend(
        row for _, batch in batches() for row in batch
    )
    monkeypatch.setattr(
        "flowsint_core.core.services.sketch_service.create_graph_service",
        lambda *a, **kw: graph,
    )
    monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
    assert (
        client.post(
            url + "/apply",
            json={"action": "create", "title": "Complete view", "revision": 0},
            headers=headers,
        ).status_code
        == 202
    )
    jobs.apply_exploration.run(
        result_id=result.id,
        sketch_id=str(sketch.id),
        actor=str(sketch.owner_id),
        action="create",
        title="Complete view",
    )
    assert len(rows) == 1201
    status = client.get(url, headers=headers).json()
    assert status["status"] == "applied"
    assert status["sketch_id"] != str(sketch.id)
    from flowsint_core.core.models import Sketch

    created = (
        db_session.query(Sketch).filter(Sketch.id == UUID(status["sketch_id"])).first()
    )
    assert created is not None and created.title == "Complete view"


def test_page_input_is_bounded_and_failed_snapshots_cannot_apply(
    client, db_session, jobs
):
    headers, sketch = seed(db_session, Role.ADMIN)
    url, result = start(client, headers, sketch)
    for query in ("kind=nodes&page=-1", "kind=nodes&size=500000", "kind=invalid"):
        assert client.get(url + "/page?" + query, headers=headers).status_code == 422
    result.state("failed", error="incomplete")
    assert (
        client.post(
            url + "/apply", json={"action": "attach", "revision": 0}, headers=headers
        ).status_code
        == 400
    )


def test_apply_rolls_back_new_sql_sketch_on_any_graph_batch_failure(
    client, db_session, jobs, monkeypatch
):
    from unittest.mock import MagicMock

    from flowsint_core.core.models import Sketch

    headers, sketch = seed(db_session, Role.ADMIN)
    url, result = start(client, headers, sketch)
    initial = db_session.query(Sketch).count()
    graph = MagicMock()
    graph.attach_result_batches.side_effect = ValueError("deleted item")
    monkeypatch.setattr(
        "flowsint_core.core.services.sketch_service.create_graph_service",
        lambda *a, **kw: graph,
    )
    monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
    assert (
        client.post(
            url + "/apply",
            json={"action": "create", "title": "Incomplete", "revision": 0},
            headers=headers,
        ).status_code
        == 202
    )
    with pytest.raises(Exception, match="deleted item"):
        jobs.apply_exploration.run(
            result_id=result.id,
            sketch_id=str(sketch.id),
            actor=str(sketch.owner_id),
            action="create",
            title="Incomplete",
        )
    assert db_session.query(Sketch).count() == initial
