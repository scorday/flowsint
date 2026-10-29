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


def test_viewer_cannot_promote_node(client, db_session, graph):
    headers, sketch = seed(db_session, Role.VIEWER)
    response = client.put(
        f"/api/sketches/{sketch.id}/nodes/edit",
        json={"nodeId": "object", "updates": {"nodeRole": "primary"}},
        headers=headers,
    )
    assert response.status_code == 403
    graph.update_node.assert_not_called()


def test_editor_can_promote_node_with_existing_update_permission(
    client, db_session, graph
):
    headers, sketch = seed(db_session, Role.EDITOR)
    graph.update_node.return_value = "object"
    response = client.put(
        f"/api/sketches/{sketch.id}/nodes/edit",
        json={"nodeId": "object", "updates": {"nodeRole": "primary"}},
        headers=headers,
    )
    assert response.status_code == 200
    graph.update_node.assert_called_once_with(
        element_id="object", updates={"nodeRole": "primary"}
    )


@pytest.mark.parametrize("role", ["unknown", None, [], {}])
def test_invalid_membership_role_is_rejected(client, db_session, graph, role):
    headers, sketch = seed(db_session, Role.EDITOR)
    response = client.put(
        f"/api/sketches/{sketch.id}/nodes/edit",
        json={"nodeId": "object", "updates": {"nodeRole": role}},
        headers=headers,
    )
    assert response.status_code == 422
    graph.update_node.assert_not_called()


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


@pytest.mark.parametrize("role, expected", [(Role.VIEWER, 403), (Role.EDITOR, 200)])
def test_manual_match_check_requires_edit_access(
    client, db_session, graph, role, expected
):
    headers, sketch = seed(db_session, role)
    graph.find_node_matches.return_value = [
        {"node": {"id": "existing"}, "match": "exact", "on_sketch": False}
    ]
    body = {
        "id": "candidate",
        "nodeType": "email",
        "nodeLabel": "a@example.com",
        "nodeProperties": {"email": "a@example.com"},
        "nodeMetadata": {},
    }
    response = client.post(
        f"/api/sketches/{sketch.id}/nodes/matches", headers=headers, json=body
    )
    assert response.status_code == expected
    if expected == 200:
        assert response.json()[0]["node"]["id"] == "existing"
        graph.find_node_matches.assert_called_once()
    else:
        graph.find_node_matches.assert_not_called()
    graph.create_node.assert_not_called()


def test_manual_match_check_never_leaks_other_investigations(client, db_session, graph):
    headers, _ = seed(db_session, Role.OWNER)
    _, foreign = seed(db_session, Role.OWNER)
    body = {
        "id": "candidate",
        "nodeType": "email",
        "nodeLabel": "a@example.com",
        "nodeProperties": {},
        "nodeMetadata": {},
    }
    response = client.post(
        f"/api/sketches/{foreign.id}/nodes/matches", headers=headers, json=body
    )
    assert response.status_code == 403
    graph.find_node_matches.assert_not_called()


def test_viewer_can_preview_exploration_but_not_attach_it(client, db_session, graph):
    headers, sketch = seed(db_session, Role.VIEWER)
    graph.explore_graph.return_value = {
        "nds": [],
        "rls": [],
        "paths": [],
        "truncated": False,
    }
    graph.search_graph_nodes.return_value = {"nodes": [], "has_more": False}
    graph.exploration_catalog.return_value = {
        "node_types": [],
        "edge_types": [],
        "truncated": False,
    }
    url = f"/api/sketches/{sketch.id}"
    assert (
        client.post(
            f"{url}/exploration", headers=headers, json={"root_id": "root", "depth": 5}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{url}/investigation-objects/search",
            headers=headers,
            json={"query": "Alice"},
        ).status_code
        == 200
    )
    catalog = client.get(f"{url}/exploration/catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["sketches"] == [{"id": str(sketch.id), "title": "View"}]
    assert (
        client.post(
            f"{url}/subgraph", headers=headers, json={"node_ids": ["root"]}
        ).status_code
        == 403
    )
    graph.attach_subgraph.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"root_id": "x", "depth": 0},
        {"root_id": "x", "depth": 6},
        {"root_id": "x", "scope_key": "foreign"},
        {"root_id": "x", "mode": "cypher"},
    ],
)
def test_exploration_rejects_unbounded_or_scope_overriding_requests(
    client, db_session, graph, body
):
    headers, sketch = seed(db_session, Role.OWNER)
    assert (
        client.post(
            f"/api/sketches/{sketch.id}/exploration", headers=headers, json=body
        ).status_code
        == 422
    )
    graph.explore_graph.assert_not_called()


def test_exploration_checks_investigation_access_before_querying_graph(
    client, db_session, graph
):
    headers, _ = seed(db_session, Role.OWNER)
    _, foreign = seed(db_session, Role.OWNER)
    url = f"/api/sketches/{foreign.id}"
    assert (
        client.post(
            f"{url}/exploration", headers=headers, json={"root_id": "root"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{url}/investigation-objects/search",
            headers=headers,
            json={"query": "Alice"},
        ).status_code
        == 403
    )
    assert client.get(f"{url}/exploration/catalog", headers=headers).status_code == 403
    graph.explore_graph.assert_not_called()
    graph.search_graph_nodes.assert_not_called()
    graph.exploration_catalog.assert_not_called()
