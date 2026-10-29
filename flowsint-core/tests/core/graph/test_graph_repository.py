"""Fail-closed unit contracts; persistence is exercised in the live suite.

The previous query-string mocks assumed sketch-owned entities and accepted
successful writes without executing Cypher. The disposable-Neo4j suite now
covers actual creation, coalescing, updates, memberships and migration.
"""

from unittest.mock import MagicMock

import pytest

from flowsint_core.core.graph.identity import GraphScope
from flowsint_core.core.graph.repository import Neo4jGraphRepository, _identifier
from flowsint_core.core.graph.schema import require_schema


def schema_rows():
    return [
        {
            "name": "graph_scope_key",
            "labelsOrTypes": ["GraphScope"],
            "properties": ["key"],
            "type": "UNIQUENESS",
        },
        {
            "name": "graph_entity_uid",
            "labelsOrTypes": ["GraphEntity"],
            "properties": ["uid"],
            "type": "UNIQUENESS",
        },
        {
            "name": "graph_view_key",
            "labelsOrTypes": ["GraphView"],
            "properties": ["scope_key", "sketch_id"],
            "type": "UNIQUENESS",
        },
    ]


@pytest.fixture
def repo():
    connection = MagicMock()
    connection.query.return_value = schema_rows()
    return Neo4jGraphRepository(
        connection, scope=GraphScope("project", "investigation", ("a", "b"))
    )


def test_no_unscoped_repository_can_be_created():
    with pytest.raises(TypeError, match="scope"):
        Neo4jGraphRepository(MagicMock())


def test_missing_schema_prevents_writes():
    connection = MagicMock()
    connection.query.return_value = []
    with pytest.raises(RuntimeError, match="schema is required"):
        Neo4jGraphRepository(connection, scope=GraphScope("project", "investigation"))
    connection.run_transaction.assert_not_called()


def test_constraint_name_alone_is_not_evidence_of_uniqueness():
    connection = MagicMock()
    rows = schema_rows()
    rows[0]["labelsOrTypes"] = ["WrongLabel"]
    connection.query.return_value = rows
    with pytest.raises(RuntimeError, match="schema is required"):
        require_schema(connection)


@pytest.mark.parametrize(
    "value", ["", None, "x` SET n.admin=true", "x\\", "x\n", "x\x00"]
)
def test_graph_identifier_rejects_escape_sequences(value):
    with pytest.raises(ValueError):
        _identifier(value)


def test_identifiers_with_spaces_are_quoted_not_interpolated_as_code():
    assert _identifier("WORKS FOR") == "`WORKS FOR`"


def test_arbitrary_cypher_is_not_a_backdoor(repo):
    with pytest.raises(PermissionError, match="isolation"):
        repo.query("MATCH (n) DETACH DELETE n")
    repo._connection.run_transaction.assert_not_called()


def test_foreign_view_id_rejected_before_storage(repo):
    with pytest.raises(PermissionError):
        repo._params("another-investigation-view")


def test_batch_discards_queued_operations_on_exception(repo):
    repo.add_to_batch("node", node_obj={"nodeType": "domain"}, sketch_id="a")
    with pytest.raises(RuntimeError):
        with repo:
            raise RuntimeError("abort")
    assert repo._batch_operations == []
    repo._connection.run_transaction.assert_not_called()


def test_unknown_batch_operation_is_rejected(repo):
    with pytest.raises(ValueError):
        repo.add_to_batch("custom-cypher", query="DELETE n")


def test_batch_size_must_be_positive(repo):
    with pytest.raises(ValueError):
        repo.set_batch_size(0)
