"""Graph-view operations must keep investigation permissions at the API boundary."""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from flowsint_core.core.auth import create_access_token
from flowsint_core.core.graph import GraphData
from flowsint_core.core.models import (
    Investigation,
    InvestigationUserRole,
    Profile,
    Sketch,
)
from flowsint_core.core.types import Role


def seed(db, role):
    user = Profile(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="unused")
    investigation = Investigation(id=uuid4(), name="Case", owner_id=user.id)
    sketch = Sketch(
        id=uuid4(), title="View", owner_id=user.id, investigation_id=investigation.id
    )
    db.add_all(
        [
            user,
            investigation,
            sketch,
            InvestigationUserRole(
                user_id=user.id, investigation_id=investigation.id, roles=[role]
            ),
        ]
    )
    db.commit()
    return {
        "Authorization": f"Bearer {create_access_token({'sub': user.email})}"
    }, sketch


@pytest.fixture
def graph(monkeypatch):
    service = MagicMock()
    service.get_investigation_graph.return_value = GraphData(nodes=[], edges=[])
    service.delete_nodes.return_value = 1
    monkeypatch.setattr(
        "flowsint_core.core.services.sketch_service.create_graph_service",
        lambda *a, **kw: service,
    )
    return service


def test_viewer_can_read_common_graph_but_cannot_attach_delete_or_import(
    client, db_session, graph
):
    headers, sketch = seed(db_session, Role.VIEWER)
    url = f"/api/sketches/{sketch.id}"
    assert client.get(f"{url}/investigation-graph", headers=headers).status_code == 200
    assert (
        client.post(
            f"{url}/subgraph", json={"node_ids": ["x"]}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE",
            f"{url}/investigation-elements",
            json={"node_ids": ["x"]},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{url}/import/execute",
            data={"entity_mappings_json": json.dumps({"nodes": [], "edges": []})},
            headers=headers,
        ).status_code
        == 403
    )
    graph.attach_subgraph.assert_not_called()
    graph.delete_from_investigation.assert_not_called()
    graph.batch_create_nodes.assert_not_called()


def test_editor_can_detach_but_not_delete_from_investigation(client, db_session, graph):
    headers, sketch = seed(db_session, Role.EDITOR)
    url = f"/api/sketches/{sketch.id}"
    assert (
        client.post(
            f"{url}/subgraph", json={"node_ids": ["x"], "edge_ids": []}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE", f"{url}/nodes", json={"nodeIds": ["x"]}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE",
            f"{url}/investigation-elements",
            json={"node_ids": ["x"]},
            headers=headers,
        ).status_code
        == 403
    )
    graph.delete_nodes.assert_called_once_with(["x"])
    graph.delete_from_investigation.assert_not_called()


def test_owner_global_delete_is_a_distinct_operation(client, db_session, graph):
    headers, sketch = seed(db_session, Role.OWNER)
    assert (
        client.request(
            "DELETE",
            f"/api/sketches/{sketch.id}/investigation-elements",
            json={"node_ids": ["x"], "edge_ids": ["e"]},
            headers=headers,
        ).status_code
        == 200
    )
    graph.delete_from_investigation.assert_called_once_with(["x"], ["e"])
    graph.delete_nodes.assert_not_called()


def test_view_cannot_move_between_investigations(client, db_session, graph):
    headers, sketch = seed(db_session, Role.OWNER)
    original_investigation = sketch.investigation_id
    response = client.put(
        f"/api/sketches/{sketch.id}",
        json={"investigation_id": str(uuid4())},
        headers=headers,
    )
    assert response.status_code == 400
    db_session.refresh(sketch)
    assert sketch.investigation_id == original_investigation
