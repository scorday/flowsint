from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from flowsint_core.avl4_import.contracts import CardImportCommand, CardSnapshot
from flowsint_core.avl4_import.graph import Neo4jMaterialProjection
from flowsint_core.avl4_import.repository import Avl4ImportOperation, Avl4Material
from flowsint_core.avl4_import.service import CardImportService, ImportRejected
from flowsint_core.core.graph.repository import Neo4jGraphRepository
from flowsint_core.core.graph.serializer import GraphSerializer
from flowsint_core.core.models import Investigation, Sketch
from flowsint_core.core.project_scope import ProjectScope, project_scope


class MemoryGraph:
    def __init__(self):
        self.nodes = {}
        self.fail_after_write = False
        self.calls = 0

    def project(self, material):
        self.calls += 1
        self.nodes[material.material_key] = dict(material.snapshot)
        if self.fail_after_write:
            raise OSError("private graph connection detail")
        return "element:" + material.material_key


def command(inv, sketch, *, card_id="card-a", project="project-a", **kwargs):
    now = datetime.now(timezone.utc)
    return CardImportCommand(
        operation_id=uuid4(),
        actor_id="alice",
        project_id=project,
        investigation_id=inv,
        sketch_id=sketch,
        snapshot=CardSnapshot(
            card_type="shared",
            card_id=card_id,
            title="Same title",
            markdown="original",
            monitoring_url="https://monitoring.test/feed?cardId=" + card_id,
            published_at=now,
            source_updated_at=now,
            captured_at=now,
        ),
        **kwargs,
    )


@pytest.fixture
def setup_import(db_session):
    with project_scope(ProjectScope("alice", "project-a")):
        inv = Investigation(id=uuid4(), name="Case")
        sketch = Sketch(id=uuid4(), title="Graph", investigation_id=inv.id)
        db_session.add_all([inv, sketch])
        db_session.commit()
        inv_id, sketch_id = inv.id, sketch.id
        graph = MemoryGraph()
        yield (
            CardImportService(db_session, graph, "https://flowsint.test"),
            graph,
            inv_id,
            sketch_id,
        )


def test_idempotent_operations_and_stable_card_identity(setup_import, db_session):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    result = service.run(first)
    assert service.run(first) == result
    assert graph.calls == 1
    assert db_session.query(Avl4ImportOperation).one().completed_at is not None
    # A fresh request is still the same material, even if the source title changed.
    other = first.model_copy(
        update={
            "operation_id": uuid4(),
            "snapshot": first.snapshot.model_copy(update={"title": "Changed"}),
        }
    )
    assert service.run(other).action == "existing"
    assert list(graph.nodes.values())[0]["title"] == "Same title"
    service.run(command(inv, sketch, card_id="card-b"))
    assert len(graph.nodes) == 2
    assert db_session.query(Avl4Material).count() == 2
    assert result.url.endswith(f"/{inv}/graph/{sketch}#pid=project-a")


def test_refresh_is_explicit_and_compare_and_swap(setup_import):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    result = service.run(first)
    updated = first.model_copy(
        update={
            "operation_id": uuid4(),
            "refresh": True,
            "expected_snapshot_hash": result.snapshot_hash,
            "snapshot": first.snapshot.model_copy(update={"markdown": "new snapshot"}),
        }
    )
    refreshed = service.run(updated)
    assert refreshed.action == "updated"
    assert list(graph.nodes.values())[0]["markdown"] == "new snapshot"
    assert service.run(updated) == refreshed
    # Replaying the first completed request never rolls a newer snapshot back.
    assert service.run(first) == result
    assert list(graph.nodes.values())[0]["markdown"] == "new snapshot"
    with pytest.raises(ImportRejected, match="SNAPSHOT_CONFLICT"):
        service.run(updated.model_copy(update={"operation_id": uuid4()}))


def test_graph_success_then_failure_is_recoverable_with_first_snapshot(
    setup_import, db_session
):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    graph.fail_after_write = True
    with pytest.raises(ImportRejected, match="IMPORT_UNAVAILABLE"):
        service.run(first)
    assert db_session.query(Avl4ImportOperation).one().result is None
    graph.fail_after_write = False
    retry = first.model_copy(
        update={
            "snapshot": first.snapshot.model_copy(
                update={"markdown": "changed after timeout"}
            )
        }
    )
    assert service.run(retry).action == "created"
    assert len(graph.nodes) == 1
    assert list(graph.nodes.values())[0]["markdown"] == "original"


def test_sql_completion_failure_after_graph_does_not_duplicate(
    setup_import, monkeypatch
):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    original_commit = service.repo.commit
    calls = 0

    def commit():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("completion SQL failed")
        original_commit()

    monkeypatch.setattr(service.repo, "commit", commit)
    with pytest.raises(ImportRejected):
        service.run(first)
    assert service.run(first).node_id.startswith("element:")
    assert len(graph.nodes) == 1


def test_stale_pending_operation_projects_latest_snapshot(setup_import):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    graph.fail_after_write = True
    with pytest.raises(ImportRejected):
        service.run(first)
    graph.fail_after_write = False
    updated = first.model_copy(
        update={
            "operation_id": uuid4(),
            "refresh": True,
            "expected_snapshot_hash": first.snapshot.content_hash,
            "snapshot": first.snapshot.model_copy(update={"markdown": "new"}),
        }
    )
    service.run(updated)
    service.run(first)
    assert list(graph.nodes.values())[0]["markdown"] == "new"


def test_idempotency_key_conflict_and_target_boundary(setup_import, db_session):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    service.run(first)
    with pytest.raises(ImportRejected, match="OPERATION_CONFLICT"):
        service.run(
            first.model_copy(
                update={
                    "snapshot": first.snapshot.model_copy(update={"card_id": "other"})
                }
            )
        )
    with pytest.raises(ImportRejected, match="TARGET_NOT_FOUND"):
        service.run(command(uuid4(), sketch))
    with project_scope(ProjectScope("alice", "project-b")):
        with pytest.raises(ImportRejected, match="TARGET_NOT_FOUND"):
            service.run(command(inv, sketch, project="project-b"))
        assert db_session.query(Avl4Material).all() == []
    assert len(graph.nodes) == 1


def test_project_members_can_import_without_local_users(setup_import):
    service, graph, inv, sketch = setup_import
    with project_scope(ProjectScope("bob", "project-a")):
        result = service.run(
            command(inv, sketch).model_copy(update={"actor_id": "bob"})
        )
    assert result.action == "created"


def test_projection_requires_constraint_and_uses_id_not_title(setup_import):
    service, _, inv, sketch = setup_import
    connection = MagicMock()
    connection.query.return_value = [{"total": 0}]
    projection = Neo4jMaterialProjection(connection)
    material = Avl4Material(
        material_key="a" * 64,
        sketch_id=sketch,
        project_id="project-a",
        snapshot=command(inv, sketch).snapshot.model_dump(mode="json"),
        snapshot_hash="b" * 64,
        revision=1,
    )
    with pytest.raises(RuntimeError, match="constraint"):
        projection.project(material)
    connection.execute_write.assert_not_called()
    connection.query.return_value = [{"total": 1}]
    connection.execute_write.return_value = [{"id": "node"}]
    assert projection.project(material) == "node"
    query, params = connection.execute_write.call_args.args
    assert "avl4_import_key: $key" in query
    assert "nodeLabel:" not in query
    assert params["props"]["nodeLabel"] == "Same title"
    parsed = GraphSerializer.neo4j_dict_to_graph_node(
        {
            "id": "node",
            "data": {
                **params["props"],
                "nodeMetadata.created_at": "2026-10-16T00:00:00Z",
            },
        }
    )
    assert parsed.nodeProperties.card_id == "card-a"
    assert parsed.nodeLabel == "Same title"


def test_generic_graph_writes_cannot_forge_or_edit_imports():
    connection = MagicMock()
    graph = Neo4jGraphRepository(connection)
    with pytest.raises(ValueError):
        graph.create_node({"nodeType": "avl4material", "nodeLabel": "fake"}, "sketch")
    graph.update_node("node", {"title": "edit", "avl4_import_key": "forged"}, "sketch")
    query, params = connection.query.call_args.args
    assert "NOT n:avl4material" in query
    assert "avl4_import_key" not in params["props"]


def test_revocation_after_durable_intent_prevents_graph_write(
    setup_import, monkeypatch
):
    from flowsint_core.core.platform_auth import AccessDenied

    service, graph, inv, sketch = setup_import
    checks = 0

    def verify(*_):
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise AccessDenied

    monkeypatch.setattr("flowsint_core.core.platform_auth.verify_actor_sync", verify)
    with project_scope(ProjectScope("alice", "project-a", worker=True)):
        with pytest.raises(AccessDenied):
            service.run(command(inv, sketch))
    assert graph.calls == 0


@pytest.mark.parametrize("collision", ["material", "operation"])
def test_unique_constraint_race_recovers_without_duplicates(
    setup_import, db_session, monkeypatch, collision
):
    service, graph, inv, sketch = setup_import
    first = command(inv, sketch)
    original = service.run(first)
    lookup = getattr(service.repo, collision)
    stale = True

    def stale_lookup(identifier):
        nonlocal stale
        if stale:
            stale = False
            return None
        return lookup(identifier)

    monkeypatch.setattr(service.repo, collision, stale_lookup)
    request = (
        first
        if collision == "operation"
        else first.model_copy(update={"operation_id": uuid4()})
    )
    result = service.run(request)
    assert result.material_id == original.material_id
    assert db_session.query(Avl4Material).count() == 1
    assert db_session.query(Avl4ImportOperation).count() == (
        1 if collision == "operation" else 2
    )
    assert len(graph.nodes) == 1
