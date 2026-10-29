"""Integration contract against an explicitly selected disposable Neo4j.

No application .env is used. The fixture never touches another scope, and
refuses a remote URI. Start the temporary test server from the runbook first.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from neo4j import GraphDatabase

from flowsint_core.core.graph.identity import GraphScope, IdentityConflict
from flowsint_core.core.graph.migration import apply_backup, snapshot
from flowsint_core.core.graph.repository import Neo4jGraphRepository
from flowsint_core.core.graph.schema import install_schema


class TestConnection:
    __test__ = False

    def __init__(self, driver):
        self.driver = driver

    def query(self, query, parameters=None):
        with self.driver.session() as session:
            return session.run(query, parameters or {}).data()

    def execute_write(self, query, parameters=None):
        return self.run_transaction(lambda tx: tx.run(query, parameters or {}).data())

    def run_transaction(self, operation):
        with self.driver.session() as session:
            return session.execute_write(operation)


@pytest.fixture
def graph():
    uri = os.getenv("FLOWSINT_TEST_NEO4J_URI")
    if not uri:
        pytest.skip(
            "Set FLOWSINT_TEST_NEO4J_URI for the disposable graph integration suite"
        )
    url = urlsplit(uri)
    if url.hostname not in {"127.0.0.1", "localhost"} or url.port != 17687:
        pytest.fail(
            "Integration tests require the isolated loopback Neo4j on port 17687"
        )
    driver = GraphDatabase.driver(uri, auth=None)
    connection = TestConnection(driver)
    install_schema(connection)
    scope = GraphScope(f"test-{uuid4()}", str(uuid4()), ("view-a", "view-b"))
    repo = Neo4jGraphRepository(connection, scope=scope)
    try:
        yield repo, connection
    finally:
        connection.execute_write(
            "MATCH (n) WHERE n.scope_key = $scope DETACH DELETE n", {"scope": scope.key}
        )
        connection.execute_write(
            "MATCH (n:GraphScope {key: $scope}) DELETE n", {"scope": scope.key}
        )
        driver.close()


def vk(user_id=123, **extra):
    return {
        "nodeType": "socialaccount",
        "nodeLabel": f"id{user_id}@vk.ru",
        "nodeProperties.platform": "vk.ru",
        "nodeProperties.username.value": f"id{user_id}",
        "nodeProperties.vk_user_id": user_id,
        **extra,
    }


def test_roles_are_per_view_and_enrichment_preserves_manual_and_legacy_roles(graph):
    repo, connection = graph
    primary = repo.create_node(vk(801, nodeRole="primary"), "view-a")
    secondary = repo.create_node(vk(802, nodeRole="secondary"), "view-a")
    legacy = repo.create_node(vk(803), "view-a")
    connection.execute_write(
        "MATCH (:GraphView {scope_key: $scope, sketch_id: 'view-a'})-[m:SHOWS]->"
        "(:GraphEntity {uid: $id}) REMOVE m.nodeRole",
        {"scope": repo.scope.key, "id": legacy},
    )
    for uid, number in [(primary, 801), (secondary, 802), (legacy, 803)]:
        repo.create_node(vk(number, id=uid, nodeRole="secondary"), "view-a")
    roles = {
        n["id"]: n["data"]["nodeRole"] for n in repo.get_sketch_graph("view-a")["nodes"]
    }
    assert roles == {primary: "primary", secondary: "secondary", legacy: "primary"}
    repo.attach_subgraph([secondary], [], "view-b")
    assert repo.get_sketch_graph("view-b")["nodes"][0]["data"]["nodeRole"] == "primary"
    repo.update_node(secondary, {"nodeRole": "primary"}, "view-a")
    repo.create_node(vk(802, id=secondary, nodeRole="secondary"), "view-a")
    assert all(
        n["data"]["nodeRole"] == "primary"
        for n in repo.get_sketch_graph("view-a")["nodes"]
    )
    assert all(
        "nodeRole" not in n["data"] for n in repo.get_investigation_graph()["nodes"]
    )


def exploration_chain(repo, length=5):
    ids = [
        repo.create_node(vk(1000 + i), "view-a" if i < 2 else "view-b")
        for i in range(length + 1)
    ]
    repo.attach_subgraph([ids[1]], [], "view-b")
    edges = [
        repo.create_relationship_by_element_id(
            ids[i],
            ids[i + 1],
            "FRIEND_OF" if i == 0 else "WORKS_WITH",
            "view-a" if i == 0 else "view-b",
        )["id"]
        for i in range(length)
    ]
    return ids, edges


def test_exploration_crosses_views_up_to_five_steps_without_mutation(graph):
    repo, _ = graph
    ids, links = exploration_chain(repo)
    before = repo.get_investigation_graph()
    result = repo.explore_graph(
        {"root_id": ids[0], "mode": "path", "target_id": ids[-1], "depth": 5}, "view-a"
    )
    assert result["paths"] == [{"node_ids": ids, "edge_ids": links}]
    assert set(result["on_sketch"]) == set(ids[:2])
    assert result["edge_views"][links[0]] == ["view-a"]
    assert result["edge_views"][links[1]] == ["view-b"]
    assert not result["truncated"]
    assert (
        repo.explore_graph(
            {"root_id": ids[0], "mode": "path", "target_id": ids[-1], "depth": 4},
            "view-a",
        )["paths"]
        == []
    )
    for depth in range(1, 6):
        result = repo.explore_graph({"root_id": ids[0], "depth": depth}, "view-a")
        assert {n["id"] for n in result["nodes"]} == set(ids[: depth + 1])
        assert result["distances"][ids[depth]] == depth
    assert repo.get_investigation_graph() == before


def test_exploration_preserves_arrows_and_respects_filters(graph):
    repo, _ = graph
    ids, links = exploration_chain(repo, 2)
    options = {"root_id": ids[-1], "target_id": ids[0], "mode": "path", "depth": 2}
    reverse = repo.explore_graph(options, "view-b")
    assert reverse["paths"][0]["node_ids"] == list(reversed(ids))
    assert (
        next(edge for edge in reverse["edges"] if edge["id"] == links[0])["source"]
        == ids[0]
    )
    assert repo.explore_graph({**options, "directed": True}, "view-b")["paths"] == []
    assert (
        repo.explore_graph({**options, "edge_types": ["FRIEND_OF"]}, "view-b")["paths"]
        == []
    )
    assert (
        repo.explore_graph({**options, "node_types": ["organization"]}, "view-b")[
            "paths"
        ]
        == []
    )
    assert (
        len(
            repo.explore_graph({**options, "node_types": ["socialaccount"]}, "view-b")[
                "paths"
            ]
        )
        == 1
    )
    repo.attach_subgraph([ids[0]], [], "view-b")
    boundary = repo.create_relationship_by_element_id(
        ids[0], ids[2], "OTHER", "view-b"
    )["id"]
    neighborhood = repo.explore_graph({"root_id": ids[1], "depth": 1}, "view-a")
    assert boundary in [e["id"] for e in neighborhood["edges"]]


def test_exploration_is_scoped_and_ignores_tombstones(graph):

    repo, connection = graph
    ids, links = exploration_chain(repo)
    other = Neo4jGraphRepository(
        connection,
        scope=GraphScope("foreign-project", repo.scope.investigation_id, ("foreign",)),
    )
    try:
        foreign_id = other.create_node(vk(), "foreign")
        assert repo.search_graph_nodes("", [foreign_id], "view-a")["nodes"] == []
        with pytest.raises(ValueError, match="Object not found"):
            repo.explore_graph(
                {"root_id": ids[0], "mode": "path", "target_id": foreign_id}, "view-a"
            )
        repo.delete_from_investigation([ids[2]], [], "view-a")
        assert repo.search_graph_nodes("", [ids[2]], "view-a")["nodes"] == []
        assert repo.explore_graph({"root_id": ids[0], "depth": 5}, "view-a")[
            "distances"
        ] == {ids[0]: 0, ids[1]: 1}
    finally:
        connection.execute_write(
            "MATCH (n) WHERE n.scope_key = $scope DETACH DELETE n",
            {"scope": other.scope.key},
        )
        connection.execute_write(
            "MATCH (n:GraphScope {key: $scope}) DELETE n", {"scope": other.scope.key}
        )


def test_exploration_returns_all_parallel_paths_without_cycles(graph):

    repo, _ = graph
    ids, links = exploration_chain(repo, 2)
    repo.attach_subgraph([ids[0]], [], "view-b")
    direct = repo.create_relationship_by_element_id(ids[0], ids[2], "KNOWS", "view-b")[
        "id"
    ]
    options = {"root_id": ids[0], "mode": "path", "target_id": ids[2], "depth": 5}
    result = repo.explore_graph(options, "view-a")
    assert {tuple(p["edge_ids"]) for p in result["paths"]} == {(direct,), tuple(links)}


def test_manual_matches_find_known_alias_across_views_without_writes(graph):
    repo, connection = graph
    uid = repo.create_node(
        vk(**{"nodeProperties.vk_screen_name": "alice", "x": 17}), "view-a"
    )
    before = repo.get_investigation_graph()
    matches = repo.find_node_matches(
        {
            "nodeType": "socialaccount",
            "nodeLabel": "New label",
            "nodeProperties.platform": "vk.com",
            "nodeProperties.profile_url": "https://vk.ru/alice",
        },
        "view-b",
    )
    assert [(row["id"], row["match"], row["on_sketch"]) for row in matches] == [
        (uid, "exact", False)
    ]
    assert repo.find_node_matches(vk(), "view-a")[0]["on_sketch"] is True
    assert repo.get_investigation_graph() == before
    # If another writer attaches between check and submit, server upsert remains canonical.
    assert repo.create_node(vk(), "view-b") == uid
    assert len(repo.get_investigation_graph()["nodes"]) == 1


def test_manual_name_matches_are_only_suggestions_and_scoped(graph):
    repo, connection = graph
    person = {
        "nodeType": "person",
        "nodeLabel": "Alice Smith",
        "nodeProperties.full_name": "Alice Smith",
    }
    first = repo.create_node(person, "view-a")
    second = repo.create_node(person, "view-b")
    other = Neo4jGraphRepository(
        connection, scope=GraphScope(repo.scope.project_id, str(uuid4()), ("foreign",))
    )
    try:
        other.create_node(person, "foreign")
        matches = repo.find_node_matches(
            {**person, "nodeLabel": "Alice", "nodeProperties.full_name": "Alice"},
            "view-b",
        )
        assert {row["id"] for row in matches} == {first, second}
        assert all(row["match"] == "possible" for row in matches)
        assert matches[0]["on_sketch"] is True
        repo.delete_from_investigation([first], [], "view-a")
        assert [row["id"] for row in repo.find_node_matches(person, "view-b")] == [
            second
        ]
        assert (
            repo.find_node_matches({"nodeType": "person", "nodeLabel": "Al"}, "view-b")
            == []
        )
    finally:
        connection.execute_write(
            "MATCH (n) WHERE n.scope_key = $scope DETACH DELETE n",
            {"scope": other.scope.key},
        )
        connection.execute_write(
            "MATCH (n:GraphScope {key: $scope}) DELETE n", {"scope": other.scope.key}
        )


def test_manual_matches_do_not_use_labels_as_exact_identity(graph):
    repo, _ = graph
    repo.create_node(vk(**{"nodeLabel": "Alice"}), "view-a")
    assert repo.find_node_matches(vk(456, **{"nodeLabel": "Alice"}), "view-b") == []
    assert (
        repo.find_node_matches(
            {"nodeType": "socialaccount", "nodeLabel": "Alice"}, "view-b"
        )[0]["match"]
        == "possible"
    )
    with pytest.raises(IdentityConflict):
        repo.find_node_matches(
            vk(456, **{"nodeProperties.profile_url": "https://vk.com/id123"}), "view-b"
        )


def test_explicit_maintenance_migrates_in_avl4_mode_while_request_access_stays_closed(
    graph, monkeypatch
):
    from flowsint_core.core.graph.connection import Neo4jConnection
    from flowsint_core.core.graph.maintenance import MaintenanceGraphConnection
    from flowsint_core.core.project_scope import project_scope

    repo, connection = graph
    old = connection.execute_write(
        "CREATE (n:socialaccount) SET n = $props RETURN elementId(n) AS id",
        {"props": {**vk(), "sketch_id": "view-a"}},
    )[0]["id"]
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    try:
        with project_scope(None):
            with pytest.raises(PermissionError, match="Verified project context"):
                Neo4jConnection.get_instance().query("RETURN 1")
            operator = MaintenanceGraphConnection(connection.driver)
            archive = snapshot(operator, repo.scope)
            mapping = apply_backup(operator, archive)
            assert repo.get_sketch_graph("view-a")["nodes"][0]["id"] == mapping[old]
    finally:
        connection.execute_write(
            "MATCH (n) WHERE elementId(n) = $id AND NOT n:GraphEntity DETACH DELETE n",
            {"id": old},
        )


def test_task_json_and_model_copy_keep_unknown_person_identity_across_enrichers(graph):
    import json

    from flowsint_core.core.enricher_base import Enricher
    from flowsint_core.core.graph import GraphService
    from flowsint_types import Individual, SocialAccount

    repo, _ = graph
    service = GraphService("view-a", repo, enable_batching=True)
    person = Individual(full_name="Alice")
    original = service.create_node_from_flowsint_type(person)

    # The queue and the next enricher's generic input adapter must preserve
    # identity even for a person who has no safe deduplication key.
    class PersonEnricher(Enricher):
        InputType = Individual

        @classmethod
        def name(cls):
            return "test_person"

        @classmethod
        def key(cls):
            return "individual"

        @classmethod
        def category(cls):
            return "test"

        async def scan(self, values):
            return values

    enricher = PersonEnricher(sketch_id="view-a", graph_service=service)
    restored = enricher.preprocess(json.loads(json.dumps([person.task_dump()])))[0]
    observed = restored.model_copy(update={"occupation": "Engineer"})
    assert service.create_node_from_flowsint_type(observed) == original
    account = SocialAccount(username="id123", platform="vk.ru")
    service.create_node_from_flowsint_type(account)
    service.create_relationship(observed, account, "HAS_ACCOUNT")
    service.flush()
    assert len(repo.get_investigation_graph()["nodes"]) == 2
    assert len(repo.get_investigation_graph()["edges"]) == 1
    assert not repo.get_sketch_graph("view-b")["nodes"]


def test_common_graph_and_id_reads_refuse_legacy_data(graph):
    repo, connection = graph
    old = connection.execute_write(
        "CREATE (n:individual {sketch_id: 'view-a', nodeLabel: 'legacy'}) RETURN elementId(n) AS id"
    )[0]["id"]
    try:
        with pytest.raises(RuntimeError, match="migration is required"):
            repo.get_investigation_graph()
        with pytest.raises(RuntimeError, match="migration is required"):
            repo.get_nodes_by_ids([old], "view-a")
    finally:
        connection.execute_write(
            "MATCH (n) WHERE elementId(n) = $id DELETE n", {"id": old}
        )


def test_imported_legacy_identity_reuses_migrated_name_only_person(graph):
    repo, connection = graph
    props = {
        "nodeType": "individual",
        "nodeLabel": "Alice",
        "nodeProperties.full_name": "Alice",
        "sketch_id": "view-a",
    }
    old = connection.execute_write(
        "CREATE (n:individual) SET n = $props RETURN elementId(n) AS id",
        {"props": props},
    )[0]["id"]
    try:
        mapping = apply_backup(connection, snapshot(connection, repo.scope))
        assert repo.create_node({**props, "id": old}, "view-b") == mapping[old]
        assert len(repo.get_investigation_graph()["nodes"]) == 1
    finally:
        connection.execute_write(
            "MATCH (n) WHERE elementId(n) = $id AND NOT n:GraphEntity DETACH DELETE n",
            {"id": old},
        )


def test_avl4_import_projects_two_sql_materials_to_one_shared_entity(graph, db_session):
    from datetime import timedelta

    from flowsint_core.avl4_import.graph import Neo4jMaterialProjection
    from flowsint_core.avl4_import.service import CardImportService
    from flowsint_core.core.models import Sketch
    from flowsint_core.core.project_scope import ProjectScope, project_scope

    from ...services.test_avl4_card_import import command
    from .test_graph_references import seed

    _, connection = graph
    scope = seed(db_session, f"test-{uuid4()}")
    view_a = UUID(scope.sketch_ids[0])
    view_b = uuid4()
    try:
        with project_scope(ProjectScope("alice", scope.project_id)):
            db_session.add(
                Sketch(
                    id=view_b,
                    title="work",
                    investigation_id=UUID(scope.investigation_id),
                )
            )
            db_session.commit()
            service = CardImportService(
                db_session,
                Neo4jMaterialProjection(connection, db=db_session),
                "https://flowsint.test",
            )
            first = command(
                UUID(scope.investigation_id), view_a, project=scope.project_id
            )
            result_a = service.run(first)
            newer = first.model_copy(
                update={
                    "operation_id": uuid4(),
                    "sketch_id": view_b,
                    "snapshot": first.snapshot.model_copy(
                        update={
                            "title": "Newer observation",
                            "captured_at": first.snapshot.captured_at
                            + timedelta(seconds=1),
                            "source_updated_at": first.snapshot.source_updated_at
                            + timedelta(seconds=1),
                        }
                    ),
                }
            )
            result_b = service.run(newer)
            assert result_a.node_id == result_b.node_id
            # Re-projecting the first view's saved snapshot must not roll back
            # a newer observation imported through the second SQL material.
            service.run(first.model_copy(update={"operation_id": uuid4()}))
            repo = Neo4jGraphRepository(
                connection,
                scope=GraphScope(
                    scope.project_id, scope.investigation_id, (str(view_a), str(view_b))
                ),
            )
            common = repo.get_investigation_graph()["nodes"]
            assert len(common) == 1
            assert common[0]["data"]["nodeLabel"] == "Newer observation"
            assert (
                repo.get_sketch_graph(str(view_a))["nodes"][0]["id"] == result_b.node_id
            )
            assert (
                repo.get_sketch_graph(str(view_b))["nodes"][0]["id"] == result_b.node_id
            )
    finally:
        connection.execute_write(
            "MATCH (n) WHERE n.scope_key = $scope DETACH DELETE n", {"scope": scope.key}
        )
        connection.execute_write(
            "MATCH (n:GraphScope {key: $scope}) DELETE n", {"scope": scope.key}
        )


def test_migration_retries_sql_phase_with_durable_node_and_edge_aliases(
    graph, db_session
):
    from flowsint_core.core.graph.references import (
        repair_sql_references,
        sql_reference_snapshot,
    )
    from flowsint_core.core.models import Log
    from flowsint_core.core.project_scope import ProjectScope, project_scope

    from .test_graph_references import seed

    _, connection = graph
    scope = seed(db_session, f"test-{uuid4()}")
    view = scope.sketch_ids[0]
    legacy = []
    try:
        for number in (123, 456):
            legacy.append(
                connection.execute_write(
                    "CREATE (n:socialaccount) SET n = $props RETURN elementId(n) AS id",
                    {
                        "props": {
                            **vk(number),
                            "sketch_id": view,
                            "project_id": scope.project_id,
                        }
                    },
                )[0]["id"]
            )
        edge = connection.execute_write(
            "MATCH (a), (b) WHERE elementId(a) = $a AND elementId(b) = $b CREATE (a)-[r:FRIEND_OF]->(b) RETURN elementId(r) AS id",
            {"a": legacy[0], "b": legacy[1]},
        )[0]["id"]
        with project_scope(ProjectScope("operator", scope.project_id)):
            db_session.add(
                Log(
                    sketch_id=UUID(view),
                    content={"node_id": legacy[0], "edge_id": edge},
                )
            )
            db_session.commit()
        backup = snapshot(connection, scope)
        backup["sql_references"] = sql_reference_snapshot(db_session.get_bind(), scope)
        mapping = apply_backup(connection, backup)
        # Simulate an interrupted two-store operation: graph committed, SQL
        # is still untouched. A fresh invocation reconstructs BOTH mappings.
        retry = snapshot(connection, scope)
        assert not retry["nodes"]
        retry_mapping = apply_backup(connection, retry)
        assert retry_mapping[legacy[0]] == mapping[legacy[0]]
        assert retry_mapping[edge] == mapping[edge]
        assert (
            repair_sql_references(
                db_session.get_bind(),
                scope,
                retry_mapping,
                expected=backup["sql_references"],
            )
            == 1
        )
        logs = sql_reference_snapshot(db_session.get_bind(), scope)
        assert any(
            r["fields"].get("content")
            == {"node_id": mapping[legacy[0]], "edge_id": mapping[edge]}
            for r in logs
        )
        assert repair_sql_references(db_session.get_bind(), scope, retry_mapping) == 0
    finally:
        connection.execute_write(
            "MATCH (n) WHERE n.scope_key = $scope OR elementId(n) IN $ids DETACH DELETE n",
            {"scope": scope.key, "ids": legacy},
        )
        connection.execute_write(
            "MATCH (n:GraphScope {key: $scope}) DELETE n", {"scope": scope.key}
        )


def test_entities_shared_layout_independent_and_enrichment_does_not_expand_other_views(
    graph,
):
    repo, _ = graph
    first = repo.create_node(vk(x=10, y=20), "view-a")
    second = repo.create_node(vk(x=90, y=80), "view-b")
    assert first == second
    friend = repo.create_node(vk(456), "view-a")
    edge = repo.create_relationship_by_element_id(first, friend, "FRIEND_OF", "view-a")
    repo.update_node(
        first, {"nodeProperties.display_name": "Alice", "nodeFlag": "red"}, "view-a"
    )
    a, b = repo.get_sketch_graph("view-a"), repo.get_sketch_graph("view-b")
    assert len(a["nodes"]) == 2 and len(b["nodes"]) == 1
    assert len(a["edges"]) == 1 and not b["edges"]
    assert b["nodes"][0]["data"]["nodeProperties.display_name"] == "Alice"
    assert b["nodes"][0]["data"]["x"] == 90
    assert b["nodes"][0]["data"].get("nodeFlag") is None
    assert next(n for n in a["nodes"] if n["id"] == first)["data"]["x"] == 10
    repo.attach_subgraph([], [edge["id"]], "view-b")
    assert len(repo.get_sketch_graph("view-b")["nodes"]) == 2
    assert repo.get_sketch_graph("view-b")["edges"][0]["id"] == edge["id"]


def test_detaching_and_deleting_a_view_keep_canonical_data(graph):
    repo, _ = graph
    uid = repo.create_node(vk(), "view-a")
    repo.create_node(vk(), "view-b")
    repo.delete_nodes([uid], "view-a")
    assert not repo.get_sketch_graph("view-a")["nodes"]
    assert len(repo.get_sketch_graph("view-b")["nodes"]) == 1
    repo.delete_all_sketch_nodes("view-b")
    assert len(repo.get_investigation_graph()["nodes"]) == 1
    repo.attach_subgraph([uid], [], "view-a")
    repo.delete_from_investigation([uid], [], "view-a")
    assert not repo.get_investigation_graph()["nodes"]
    assert not repo.get_sketch_graph("view-a")["nodes"]


def test_same_typed_directed_edge_is_shared_but_reverse_direction_is_distinct(graph):
    repo, _ = graph
    a = repo.create_node(vk(), "view-a")
    b = repo.create_node(vk(456), "view-a")
    repo.attach_subgraph([a, b], [], "view-b")
    first = repo.create_relationship_by_element_id(a, b, "FRIEND_OF", "view-a")
    second = repo.create_relationship_by_element_id(a, b, "FRIEND_OF", "view-b")
    assert first["id"] == second["id"]
    repo.create_relationship_by_element_id(b, a, "FRIEND_OF", "view-a")
    assert len(repo.get_investigation_graph()["edges"]) == 2
    repo.delete_relationships([first["id"]], "view-a")
    assert len(repo.get_sketch_graph("view-a")["edges"]) == 1
    assert len(repo.get_sketch_graph("view-b")["edges"]) == 1


def test_alias_resolution_coalesces_views_and_preserves_typed_edges(graph):
    repo, _ = graph
    alias = repo.create_node(
        {
            "nodeType": "socialaccount",
            "nodeLabel": "Alice",
            "nodeProperties.profile_url": "https://vk.com/alice",
            "x": 17,
        },
        "view-a",
    )
    numeric = repo.create_node(vk(x=90), "view-b")
    friend = repo.create_node(vk(456), "view-a")
    repo.create_relationship_by_element_id(alias, friend, "FRIEND_OF", "view-a")
    resolved = repo.create_node(
        vk(**{"nodeProperties.vk_screen_name": "alice"}), "view-a"
    )
    assert resolved in {alias, numeric}
    assert len(repo.get_investigation_graph()["nodes"]) == 2
    assert len(repo.get_sketch_graph("view-b")["nodes"]) == 1
    assert repo.get_sketch_graph("view-a")["edges"][0]["type"] == "FRIEND_OF"
    assert repo.get_nodes_by_ids([numeric], "view-b")
    with pytest.raises(IdentityConflict):
        repo.create_node(
            vk(999, **{"nodeProperties.vk_screen_name": "alice"}), "view-a"
        )
    assert len(repo.get_investigation_graph()["nodes"]) == 2


def test_parallel_enrichers_do_not_duplicate_entities(graph):
    repo, _ = graph
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(
            pool.map(
                lambda i: repo.create_node(vk(), "view-a" if i % 2 else "view-b"),
                range(8),
            )
        )
    assert len(set(ids)) == 1
    assert len(repo.get_investigation_graph()["nodes"]) == 1


def test_equal_names_are_independent_and_foreign_ids_cannot_be_attached(graph):
    repo, connection = graph
    person = {
        "nodeType": "individual",
        "nodeLabel": "Alice",
        "nodeProperties.full_name": "Alice",
    }
    assert repo.create_node(person, "view-a") != repo.create_node(person, "view-b")
    other = Neo4jGraphRepository(
        connection, scope=GraphScope(repo.scope.project_id, str(uuid4()))
    )
    foreign = other.create_node(vk(), "view-a")
    try:
        with pytest.raises(ValueError):
            repo.attach_subgraph([foreign], [], "view-a")
        assert not repo.get_nodes_by_ids([foreign], "view-a")
        assert (
            other.update_node(
                repo.get_investigation_graph()["nodes"][0]["id"],
                {"nodeLabel": "forged"},
                "view-a",
            )
            is None
        )
    finally:
        other.delete_investigation_graph("view-a")


def test_failed_batch_is_atomic(graph):
    repo, _ = graph
    with pytest.raises(ValueError):
        repo.batch_create_nodes([vk(), {"nodeType": "bad`type"}], "view-a")
    assert not repo.get_investigation_graph()["nodes"]


def test_migration_preserves_layout_shared_edges_and_is_repeatable(graph):
    repo, connection = graph
    legacy = []
    for view, x in (("view-a", 10), ("view-b", 90)):
        for user_id in (123, 456):
            rows = connection.execute_write(
                "CREATE (n:socialaccount) SET n = $props RETURN elementId(n) AS id",
                {
                    "props": {
                        **vk(user_id),
                        "sketch_id": view,
                        "x": x,
                        "nodeProperties.display_name": view,
                    }
                },
            )
            legacy.append(rows[0]["id"])
        connection.execute_write(
            """MATCH (a), (b) WHERE elementId(a) = $a AND elementId(b) = $b
            CREATE (a)-[:FRIEND_OF {sketch_id: $view, confidence_level: 0.9}]->(b)""",
            {"a": legacy[-2], "b": legacy[-1], "view": view},
        )
    backup = snapshot(connection, repo.scope)
    mapping = apply_backup(connection, backup)
    assert mapping[legacy[0]] == mapping[legacy[2]]
    assert len(repo.get_investigation_graph()["nodes"]) == 2
    assert len(repo.get_investigation_graph()["edges"]) == 1
    assert repo.get_sketch_graph("view-a")["nodes"][0]["data"]["x"] == 10
    assert repo.get_sketch_graph("view-b")["nodes"][0]["data"]["x"] == 90
    apply_backup(connection, backup)
    assert len(repo.get_investigation_graph()["nodes"]) == 2
    assert len(repo.get_sketch_graph("view-a")["edges"]) == 1


def test_migration_refuses_stale_backup_and_keeps_originals(graph):
    repo, connection = graph
    rows = connection.execute_write(
        "CREATE (n:socialaccount) SET n = $props RETURN elementId(n) AS id",
        {"props": {**vk(), "sketch_id": "view-a"}},
    )
    backup = snapshot(connection, repo.scope)
    connection.execute_write(
        "MATCH (n) WHERE elementId(n) = $id SET n.nodeLabel = 'changed'",
        {"id": rows[0]["id"]},
    )
    try:
        with pytest.raises(ValueError, match="changed since backup"):
            apply_backup(connection, backup)
        assert len(snapshot(connection, repo.scope)["nodes"]) == 1
    finally:
        connection.execute_write(
            "MATCH (n) WHERE elementId(n) = $id DETACH DELETE n", {"id": rows[0]["id"]}
        )


def test_migration_keeps_tombstones_without_reviving_deleted_appearances(graph):
    import json

    repo, connection = graph
    originals = []
    for view, deleted in (("view-a", None), ("view-b", "2026-10-20T00:00:00Z")):
        row = connection.execute_write(
            "CREATE (n:socialaccount) SET n = $props RETURN elementId(n) AS id",
            {"props": {**vk(), "sketch_id": view, "deleted_at": deleted, "x": 12}},
        )[0]
        originals.append(row["id"])
    try:
        backup = snapshot(connection, repo.scope)
        mapping = apply_backup(connection, backup)
        assert mapping[originals[0]] == mapping[originals[1]]
        assert len(repo.get_sketch_graph("view-a")["nodes"]) == 1
        assert not repo.get_sketch_graph("view-b")["nodes"]
        data = repo.get_investigation_graph()["nodes"][0]["data"]
        records = [json.loads(record) for record in data["migration_records"]]
        assert {r["id"] for r in records} == set(originals)
        assert any(r["data"].get("deleted_at") for r in records)
    finally:
        connection.execute_write(
            "MATCH (n) WHERE elementId(n) IN $ids AND NOT n:GraphEntity DETACH DELETE n",
            {"ids": originals},
        )


def test_json_round_trip_reuses_unknown_person_and_preserves_view_and_edge_attributes(
    graph,
):
    import json
    from dataclasses import asdict

    from flowsint_core.core.graph import GraphService
    from flowsint_core.imports.import_service import EntityMapping, ImportService
    from flowsint_core.imports.json.parse_json import parse_json

    repo, _ = graph
    person = repo.create_node(
        {
            "nodeType": "individual",
            "nodeLabel": "Alice",
            "nodeProperties.full_name": "Alice",
            "x": 12,
            "y": 34,
        },
        "view-a",
    )
    account = repo.create_node(
        vk(**{"nodeProperties.display_name": "Alice VK"}), "view-a"
    )
    repo.create_relationship_by_element_id(
        person,
        account,
        "HAS_ACCOUNT",
        "view-a",
        properties={
            "confidence_level": 0.8,
            "source_url": "https://example.com/evidence",
        },
    )
    service = GraphService("view-a", repo)
    exported = service.get_sketch_graph().model_dump(mode="json", serialize_as_any=True)
    preview = parse_json(json.dumps(exported).encode(), 100)
    mappings = []
    for group in preview.entities.values():
        for entry in group.results:
            mappings.append(
                EntityMapping(
                    id=entry.node_id,
                    entity_type=entry.detected_type,
                    nodeLabel=entry.obj.nodeLabel,
                    data=entry.obj.model_dump(mode="json"),
                    node_id=entry.node_id,
                    graph_uid=entry.graph_uid,
                    presentation=entry.presentation,
                )
            )
    imported = ImportService(GraphService("view-b", repo)).execute_import(
        mappings, [asdict(e) for e in preview.edges]
    )
    assert not imported.errors
    assert len(repo.get_investigation_graph()["nodes"]) == 2
    assert len(repo.get_investigation_graph()["edges"]) == 1
    target = repo.get_sketch_graph("view-b")
    assert next(n for n in target["nodes"] if n["id"] == person)["data"]["x"] == 12
    assert (
        next(n for n in target["nodes"] if n["id"] == account)["data"][
            "nodeProperties.display_name"
        ]
        == "Alice VK"
    )
    assert target["edges"][0]["data"]["confidence_level"] == 0.8
    assert target["edges"][0]["data"]["source_url"] == "https://example.com/evidence"


def test_shared_card_snapshot_uses_actual_time_and_cannot_be_replaced_by_generic_import(
    graph,
):
    repo, _ = graph
    snapshot = {
        "nodeType": "avl4_card",
        "nodeLabel": "newer",
        "avl4_import_key": "card-identity",
        "nodeProperties.source_updated_at": "2026-10-20T12:00:00+03:00",
        "nodeProperties.captured_at": "2026-10-20T12:00:01+03:00",
    }
    uid = repo.project_material(snapshot, "view-a")
    # 10:00 UTC is newer than 12:00 +03:00; compare instants, not ISO text.
    repo.project_material(
        {
            **snapshot,
            "nodeLabel": "latest",
            "nodeProperties.source_updated_at": "2026-10-20T10:00:00Z",
        },
        "view-b",
    )
    repo.project_material(snapshot, "view-a")
    assert repo.get_investigation_graph()["nodes"][0]["data"]["nodeLabel"] == "latest"
    result = repo.batch_create_nodes(
        [{**snapshot, "id": uid, "nodeLabel": "forged"}], "view-b"
    )
    assert result["node_ids"] == [uid]
    assert repo.get_sketch_graph("view-b")["nodes"][0]["data"]["nodeLabel"] == "latest"
    with pytest.raises(ValueError):
        repo.update_node(uid, {"nodeLabel": "forged"}, "view-a")
    with pytest.raises(ValueError):
        repo.batch_create_nodes([{**snapshot, "id": "not-this-card"}], "view-b")


def test_alias_bridge_with_a_deleted_candidate_does_not_leave_duplicate_entities(graph):
    repo, _ = graph
    numeric = repo.create_node(vk(), "view-a")
    repo.delete_from_investigation([numeric], [], "view-a")
    alias = repo.create_node(
        {
            "nodeType": "socialaccount",
            "nodeLabel": "Alice",
            "nodeProperties.profile_url": "https://vk.com/alice",
        },
        "view-b",
    )
    resolved = repo.create_node(
        vk(**{"nodeProperties.vk_screen_name": "alice"}), "view-b"
    )
    assert resolved in {numeric, alias}
    assert len(repo.get_investigation_graph()["nodes"]) == 1
    assert not repo.get_sketch_graph("view-a")["nodes"]
    assert len(repo.get_sketch_graph("view-b")["nodes"]) == 1


def test_edge_rename_and_coalescing_preserve_ids_aliases_histories_and_views(graph):
    import json

    repo, _ = graph
    a, b = repo.create_node(vk(), "view-a"), repo.create_node(vk(456), "view-a")
    repo.attach_subgraph([a, b], [], "view-b")
    first = repo.create_relationship_by_element_id(
        a, b, "KNOWS", "view-a", {"confidence_level": 0.2, "origin": "one"}
    )
    repo.update_relationship(first["id"], {"confidence_level": 0.4}, "view-a")
    renamed = repo.update_relationship(first["id"], {"label": "FRIEND_OF"}, "view-a")
    assert renamed["id"] == first["id"]
    other = repo.create_relationship_by_element_id(
        a, b, "KNOWS", "view-b", {"origin": "two"}
    )
    winner = repo.update_relationship(other["id"], {"label": "FRIEND_OF"}, "view-b")
    assert winner["id"] == first["id"]
    assert len(repo.get_investigation_graph()["edges"]) == 1
    assert repo.get_sketch_graph("view-b")["edges"][0]["id"] == winner["id"]
    data = repo.get_investigation_graph()["edges"][0]["data"]
    assert other["id"] in data["legacy_ids"]
    assert any(event["previous"] == 0.2 for event in json.loads(data["graph_history"]))
    assert (
        repo.update_relationship(other["id"], {"caption": "old link works"}, "view-b")[
            "id"
        ]
        == winner["id"]
    )
    repo.delete_relationships([other["id"]], "view-b")
    assert not repo.get_sketch_graph("view-b")["edges"]
    repo.attach_subgraph([], [other["id"], winner["id"]], "view-b")
    assert len(repo.get_sketch_graph("view-b")["edges"]) == 1
    repo.delete_from_investigation([], [other["id"]], "view-b")
    assert not repo.get_sketch_graph("view-a")["edges"]


def test_deleted_view_and_investigation_reject_writes_from_previously_admitted_tasks(
    graph,
):
    repo, _ = graph
    uid = repo.create_node(vk(), "view-a")
    repo.create_node(vk(), "view-b")
    repo.delete_all_sketch_nodes("view-a")
    repo.delete_all_sketch_nodes("view-a")  # SQL deletion retry
    with pytest.raises(PermissionError, match="view has been deleted"):
        repo.create_node(vk(456), "view-a")
    assert repo.get_sketch_graph("view-b")["nodes"][0]["id"] == uid
    repo.delete_investigation_graph("view-b")
    repo.delete_investigation_graph("view-b")
    with pytest.raises(PermissionError, match="Investigation graph has been deleted"):
        repo.create_node(vk(789), "view-b")
    assert not repo.get_investigation_graph()["nodes"]


def test_complete_search_and_atomic_apply_above_old_limits(graph):
    from flowsint_core.core.graph.exploration import (
        ExplorationOptions,
        InvestigationExplorer,
    )

    repo, connection = graph
    root = repo.create_node(vk(987654), "view-a")
    # Seed a star efficiently: >200 objects, >500 edges and >5000 scanned
    # relationships, without touching any other scope.
    connection.execute_write(
        """MATCH (a:GraphEntity {scope_key: $scope, uid: $root})
        UNWIND range(1, 12050) AS i
        CREATE (b:GraphEntity {scope_key: $scope, uid: 'large-' + toString(i),
          nodeType: 'socialaccount', nodeLabel: 'Person ' + toString(i)})
        CREATE (a)-[:FRIEND_OF {scope_key: $scope, uid: 'edge-' + toString(i), view_ids: ['view-b']}]->(b)""",
        {"scope": repo.scope.key, "root": root},
    )
    explorer = InvestigationExplorer(connection, repo.scope)
    resources = {kind: {} for kind in ("nodes", "edges", "paths")}
    for kind, rows in explorer.iter_results(
        ExplorationOptions(root_id=root, depth=1), "view-a"
    ):
        assert len(rows) <= 500
        resources[kind].update({row["id"]: row for row in rows})
    assert len(resources["nodes"]) == 12051
    assert len(resources["edges"]) == 12050

    # The final batch contains an invalidated item: earlier batches must roll back.
    def invalid():
        yield "nodes", list(resources["nodes"].values())[:500]
        yield "nodes", [{"id": "deleted-or-foreign"}]

    before = repo.get_sketch_graph("view-b")
    with pytest.raises(ValueError, match="changed"):
        repo.attach_result_batches(invalid, "view-b")
    assert repo.get_sketch_graph("view-b") == before

    def valid():
        for kind in ("nodes", "edges"):
            rows = list(resources[kind].values())
            for offset in range(0, len(rows), 500):
                yield kind, rows[offset : offset + 500]

    repo.attach_result_batches(valid, "view-b")
    created = repo.get_sketch_graph("view-b")
    assert len(created["nodes"]) == 12051
    assert len(created["edges"]) == 12050
    assert len(repo.get_sketch_graph("view-a")["nodes"]) == 1


def test_complete_path_search_exceeds_twenty_paths(graph):
    from flowsint_core.core.graph.exploration import (
        ExplorationOptions,
        InvestigationExplorer,
    )

    repo, connection = graph
    root, target = [repo.create_node(vk(998800 + i), "view-a") for i in range(2)]
    connection.execute_write(
        """MATCH (a:GraphEntity {scope_key: $scope, uid: $root}),
                  (z:GraphEntity {scope_key: $scope, uid: $target})
        UNWIND range(1, 75) AS i
        CREATE (b:GraphEntity {scope_key: $scope, uid: 'via-' + toString(i),
            nodeType: 'socialaccount', nodeLabel: 'Via ' + toString(i)})
        CREATE (a)-[:FRIEND_OF {scope_key: $scope, uid: 'first-' + toString(i)}]->(b)
        CREATE (b)-[:FRIEND_OF {scope_key: $scope, uid: 'second-' + toString(i)}]->(z)""",
        {"scope": repo.scope.key, "root": root, "target": target},
    )
    paths = [
        p
        for kind, rows in InvestigationExplorer(connection, repo.scope).iter_results(
            ExplorationOptions(root_id=root, target_id=target, mode="path", depth=2),
            "view-a",
        )
        if kind == "paths"
        for p in rows
    ]
    assert len(paths) == 75
    assert all(len(p["node_ids"]) == len(set(p["node_ids"])) for p in paths)


def test_graph_keyset_pages_are_complete_and_reject_mixed_revisions(graph):
    repo, _ = graph
    ids, edges = exploration_chain(repo, 4)
    repo.attach_subgraph(ids, edges, "view-a")
    revision = None
    for kind, expected in (("nodes", set(ids)), ("edges", set(edges))):
        after, found = "", []
        while True:
            page = repo.get_sketch_graph_page("view-a", kind, after, 2, revision)
            revision = page["revision"]
            assert len(page[kind]) <= 2
            found.extend(row["id"] for row in page[kind])
            if not page["has_more"]:
                break
            assert page["after"] > after
            after = page["after"]
        assert set(found) == expected
        assert len(found) == len(expected)
    repo.create_node(vk(99887766), "view-a")
    with pytest.raises(ValueError, match="changed"):
        repo.get_sketch_graph_page("view-a", "nodes", "", 2, revision)


def test_neighborhood_type_filter_does_not_whitelist_a_previous_path_target(graph):
    repo, _ = graph
    root, neighbor = [repo.create_node(vk(775500 + i), "view-a") for i in range(2)]
    organization = repo.create_node(
        {
            "nodeType": "organization",
            "nodeLabel": "Excluded target",
            "nodeProperties.name": "Excluded target",
        },
        "view-a",
    )
    repo.create_relationship_by_element_id(root, neighbor, "FRIEND_OF", "view-a")
    repo.create_relationship_by_element_id(root, organization, "WORKS_AT", "view-a")
    options = {
        "mode": "neighborhood",
        "root_id": root,
        "target_id": organization,
        "depth": 1,
        "node_types": ["socialaccount"],
    }
    result = repo.explore_graph(options, "view-a")
    assert {node["id"] for node in result["nodes"]} == {root, neighbor}
    assert len(result["edges"]) == 1
