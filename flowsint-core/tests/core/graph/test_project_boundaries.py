"""Execute hostile-property regressions against the disposable Neo4j."""

import pytest

from .test_investigation_graph_live import graph as graph
from .test_investigation_graph_live import vk


def test_node_creation_cannot_override_verified_scope(graph):
    repo, _ = graph
    uid = repo.create_node(
        vk(sketch_id="foreign", project_id="foreign", investigation_id="foreign"),
        "view-a",
    )
    node = repo.get_sketch_graph("view-a")["nodes"][0]
    assert node["id"] == uid
    assert node["data"]["project_id"] == repo.scope.project_id
    assert node["data"]["investigation_id"] == repo.scope.investigation_id
    assert "sketch_id" not in node["data"]


@pytest.mark.parametrize("operation", ["node", "relationship"])
def test_edit_cannot_move_existing_graph_object_to_another_scope(graph, operation):
    repo, _ = graph
    a, b = repo.create_node(vk(), "view-a"), repo.create_node(vk(456), "view-a")
    payload = {
        "sketch_id": "foreign",
        "project_id": "foreign",
        "investigation_id": "foreign",
        "caption": "Updated",
    }
    if operation == "node":
        repo.update_node(a, payload, "view-a")
        record = repo.get_sketch_graph("view-a")["nodes"][0]
    else:
        edge = repo.create_relationship_by_element_id(a, b, "RELATED_TO", "view-a")
        repo.update_relationship(edge["id"], payload, "view-a")
        record = repo.get_sketch_graph("view-a")["edges"][0]
    assert record["data"]["scope_key"] == repo.scope.key
    assert payload["sketch_id"] == "foreign"
    assert not repo.get_sketch_graph("view-b")["nodes"]


def test_link_by_known_ids_requires_both_endpoints_in_current_view(graph):
    repo, _ = graph
    a, b = repo.create_node(vk(), "view-a"), repo.create_node(vk(456), "view-b")
    assert repo.create_relationship_by_element_id(a, b, "RELATED_TO", "view-a") is None
    assert not repo.get_investigation_graph()["edges"]


def test_batch_links_bind_property_maps_instead_of_interpolating_keys(graph):
    repo, _ = graph
    a, b = repo.create_node(vk(), "view-a"), repo.create_node(vk(456), "view-a")
    hostile_key = "value}) DELETE n //"
    repo.batch_create_edges_by_element_id(
        [
            {
                "from_element_id": a,
                "to_element_id": b,
                "rel_label": "RELATED_TO",
                "properties": {hostile_key: "literal-data", "scope_key": "foreign"},
            }
        ],
        "view-a",
    )
    edge = repo.get_sketch_graph("view-a")["edges"][0]
    assert edge["data"][hostile_key] == "literal-data"
    assert edge["data"]["scope_key"] == repo.scope.key
    assert len(repo.get_investigation_graph()["nodes"]) == 2


@pytest.mark.parametrize(
    "label", ["Type` MATCH (n) DETACH DELETE n //", r"Type\u0060", "Type\nOther"]
)
def test_labels_cannot_escape_into_cypher(graph, label):
    repo, _ = graph
    with pytest.raises(ValueError, match="identifier"):
        repo.create_node({"nodeLabel": "data", "nodeType": label}, "view-a")
    a, b = repo.create_node(vk(), "view-a"), repo.create_node(vk(456), "view-a")
    with pytest.raises(ValueError, match="identifier"):
        repo.create_relationship_by_element_id(a, b, label, "view-a")
    assert len(repo.get_investigation_graph()["nodes"]) == 2
    assert not repo.get_investigation_graph()["edges"]


def test_unicode_relationship_names_are_preserved(graph):
    repo, _ = graph
    a, b = repo.create_node(vk(), "view-a"), repo.create_node(vk(456), "view-a")
    repo.create_relationship_by_element_id(a, b, "Связан с", "view-a")
    assert repo.get_investigation_graph()["edges"][0]["type"] == "Связан с"
