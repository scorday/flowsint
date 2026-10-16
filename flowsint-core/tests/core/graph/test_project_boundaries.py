"""Regression checks for scope-bearing graph queries and hostile properties."""

from unittest.mock import MagicMock

import pytest

from flowsint_core.core.graph import Neo4jGraphRepository


@pytest.fixture
def graph():
    connection = MagicMock()
    return Neo4jGraphRepository(neo4j_connection=connection), connection


def test_node_creation_cannot_override_verified_sketch(graph):
    repo, connection = graph
    repo.create_node(
        {"nodeLabel": "Article", "nodeType": "document", "sketch_id": "foreign"},
        "current",
    )
    query, params = connection.query.call_args.args
    assert params["sketch_id"] == "current"
    assert params["props"]["sketch_id"] == "current"
    assert "foreign" not in query


@pytest.mark.parametrize("operation", ["node", "relationship"])
def test_edit_cannot_move_existing_graph_object_to_another_sketch(graph, operation):
    repo, connection = graph
    payload = {"sketch_id": "foreign", "caption": "Updated"}
    if operation == "node":
        repo.update_node("known-id", payload, "current")
    else:
        repo.update_relationship("known-id", payload, "current")
    query, params = connection.query.call_args.args
    assert "sketch_id = $sketch_id" in query
    assert params["props"]["sketch_id"] == "current"
    assert payload["sketch_id"] == "foreign"  # Input is not mutated during retries.


def test_link_by_known_ids_requires_both_endpoints_in_current_sketch(graph):
    repo, connection = graph
    repo.create_relationship_by_element_id(
        "known-foreign-node", "own-node", "RELATED_TO", "current"
    )
    query, params = connection.query.call_args.args
    assert "a.sketch_id = $sketch_id" in query
    assert "b.sketch_id = $sketch_id" in query
    assert params["sketch_id"] == "current"


def test_batch_links_bind_property_maps_instead_of_interpolating_keys(graph):
    repo, connection = graph
    hostile_key = "value}) DELETE n //"
    result = repo.batch_create_edges_by_element_id(
        [
            {
                "from_element_id": "foreign",
                "to_element_id": "own",
                "rel_label": "RELATED_TO",
                "sketch_id": "foreign",
                hostile_key: "literal-data",
            }
        ],
        "current",
    )
    assert result["errors"] == []
    [(query, params)] = connection.execute_batch.call_args.args[0]
    assert "from.sketch_id = $sketch_id" in query
    assert "to.sketch_id = $sketch_id" in query
    assert hostile_key not in query
    assert params["props_0"][hostile_key] == "literal-data"
    assert params["props_0"]["sketch_id"] == "current"


@pytest.mark.parametrize(
    "label", ["Type` MATCH (n) DETACH DELETE n //", r"Type\u0060", "Type\nOther"]
)
def test_labels_cannot_escape_into_cypher(graph, label):
    repo, connection = graph
    with pytest.raises(ValueError, match="identifier"):
        repo.create_node({"nodeLabel": "data", "nodeType": label}, "current")
    with pytest.raises(ValueError, match="identifier"):
        repo.create_relationship_by_element_id("a", "b", label, "current")
    connection.query.assert_not_called()


def test_unicode_relationship_names_are_quoted(graph):
    repo, connection = graph
    repo.create_relationship_by_element_id("a", "b", "Связан с", "current")
    assert "[r:`Связан с`" in connection.query.call_args.args[0]
