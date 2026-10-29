from uuid import uuid4

import pytest

from flowsint_core.core.graph.identity import GraphScope
from flowsint_core.core.graph.references import (
    remap_references,
    repair_sql_references,
    sql_reference_snapshot,
)
from flowsint_core.core.models import (
    Avl4ImportOperation,
    Avl4Material,
    Chat,
    ChatMessage,
    Investigation,
    Log,
    Scan,
    Sketch,
)
from flowsint_core.core.project_scope import ProjectScope, project_scope


def test_remap_rewrites_graph_references_but_keeps_domain_ids_and_prose():
    payload = {
        "message": "4:old",
        "id": "4:old",
        "node_ids": ["4:old", "unknown"],
        "graph": {
            "nodes": [
                {
                    "id": "4:old",
                    "nodeType": "socialaccount",
                    "nodeProperties": {"id": "4:old"},
                }
            ],
            "edges": [{"id": "5:old", "source": "4:old", "target": "4:other"}],
        },
        "result": {"_graph_uid": "4:old"},
    }
    result = remap_references(payload, {"4:old": "node-uuid", "5:old": "edge-uuid"})
    assert result["message"] == result["id"] == "4:old"
    assert result["node_ids"] == ["node-uuid", "unknown"]
    assert result["graph"]["nodes"][0]["id"] == "node-uuid"
    assert result["graph"]["nodes"][0]["nodeProperties"]["id"] == "4:old"
    assert result["graph"]["edges"][0] == {
        "id": "edge-uuid",
        "source": "node-uuid",
        "target": "4:other",
    }
    assert result["result"]["_graph_uid"] == "node-uuid"
    assert payload["node_ids"][0] == "4:old"


def seed(db, project):
    inv, sketch, material, chat = uuid4(), uuid4(), uuid4(), uuid4()
    with project_scope(ProjectScope("operator", project)):
        db.add(Investigation(id=inv, name="case"))
        db.flush()
        db.add_all(
            [
                Sketch(id=sketch, title="view", investigation_id=inv),
                Chat(id=chat, title="chat", investigation_id=inv),
            ]
        )
        db.flush()
        db.add(
            Avl4Material(
                id=material,
                material_key=str(uuid4()),
                investigation_id=inv,
                sketch_id=sketch,
                snapshot={},
                snapshot_hash="a" * 64,
                revision=1,
                node_id="4:old",
            )
        )
        db.flush()
        db.add_all(
            [
                Avl4ImportOperation(
                    operation_id=uuid4(),
                    material_id=material,
                    fingerprint="f" * 64,
                    snapshot={},
                    snapshot_hash="a" * 64,
                    action="created",
                    result={"node_id": "4:old"},
                ),
                Log(
                    sketch_id=sketch,
                    content={
                        "nodes": [{"nodeType": "individual", "id": "4:old"}],
                        "message": "4:old",
                    },
                ),
                Scan(
                    sketch_id=sketch,
                    details={
                        "result": [{"_graph_uid": "4:old", "id": "social-domain-id"}]
                    },
                ),
                ChatMessage(
                    chat_id=chat,
                    content="4:old",
                    context=["Some evidence: 4:old", {"node_id": "4:old"}],
                ),
            ]
        )
        db.commit()
    return GraphScope(project, str(inv), (str(sketch),))


def test_sql_repair_is_repeatable_and_only_changes_the_selected_investigation(
    db_session,
):
    scope = seed(db_session, "a")
    same_project = seed(db_session, "a")
    other_project = seed(db_session, "b")
    engine = db_session.get_bind()
    before = sql_reference_snapshot(engine, scope)
    untouched_same = sql_reference_snapshot(engine, same_project)
    untouched_other = sql_reference_snapshot(engine, other_project)
    assert (
        repair_sql_references(engine, scope, {"4:old": "canonical"}, expected=before)
        == 5
    )
    after = sql_reference_snapshot(engine, scope)
    material = next(r for r in after if r["table"] == "avl4_materials")
    operation = next(r for r in after if r["table"] == "avl4_import_operations")
    assert material["fields"]["node_id"] == "canonical"
    assert operation["fields"]["result"]["node_id"] == "canonical"
    assert sql_reference_snapshot(engine, same_project) == untouched_same
    assert sql_reference_snapshot(engine, other_project) == untouched_other
    assert repair_sql_references(engine, scope, {"4:old": "canonical"}) == 0


def test_sql_repair_refuses_a_stale_archive_without_partial_updates(db_session):
    scope = seed(db_session, "a")
    engine = db_session.get_bind()
    original = sql_reference_snapshot(engine, scope)
    with engine.begin() as connection:
        connection.execute(
            Log.__table__.update()
            .where(Log.__table__.c.project_id == "a")
            .values(content={"message": "new evidence"})
        )
    changed = sql_reference_snapshot(engine, scope)
    with pytest.raises(ValueError, match="changed since backup"):
        repair_sql_references(engine, scope, {"4:old": "canonical"}, expected=original)
    assert sql_reference_snapshot(engine, scope) == changed
