import copy
from uuid import uuid4

import pytest

from flowsint_core.core.graph import migration
from flowsint_core.core.graph.migration import restored_reference_mapping


def archives():
    old_db, new_db = uuid4(), uuid4()
    a, b, r = f"4:{old_db}:1", f"4:{old_db}:2", f"5:{old_db}:1"
    backup = {
        "version": 1,
        "scope": {
            "project_id": "p",
            "investigation_id": str(uuid4()),
            "sketch_ids": ["view"],
        },
        "nodes": [
            {
                "id": a,
                "labels": ["individual"],
                "data": {
                    "nodeType": "individual",
                    "nodeLabel": "Alice",
                    "sketch_id": "view",
                },
            },
            {
                "id": b,
                "labels": ["individual"],
                "data": {
                    "nodeType": "individual",
                    "nodeLabel": "Bob",
                    "sketch_id": "view",
                },
            },
        ],
        "edges": [
            {
                "id": r,
                "source": a,
                "target": b,
                "type": "RELATED_TO",
                "data": {"confidence": 0.8},
            }
        ],
    }
    restored = copy.deepcopy(backup)
    for node in restored["nodes"]:
        node["id"] = node["id"].replace(str(old_db), str(new_db))
    for edge in restored["edges"]:
        for key in ("id", "source", "target"):
            edge[key] = edge[key].replace(str(old_db), str(new_db))
    return backup, restored


def test_native_restore_repairs_database_uuid_only_after_verifying_all_records():
    backup, restored = archives()
    mapping = restored_reference_mapping(backup, restored)
    assert len(mapping) == 3
    assert mapping[backup["nodes"][0]["id"]] == restored["nodes"][0]["id"]
    assert mapping[backup["edges"][0]["id"]] == restored["edges"][0]["id"]


@pytest.mark.parametrize(
    "change", ["property", "label", "type", "endpoint", "count", "scope", "format"]
)
def test_restore_refuses_matching_numeric_ids_with_different_evidence(change):
    backup, restored = archives()
    if change == "property":
        restored["nodes"][0]["data"]["nodeLabel"] = "Someone else"
    elif change == "label":
        restored["nodes"][0]["labels"] = ["organization"]
    elif change == "type":
        restored["edges"][0]["type"] = "OTHER"
    elif change == "endpoint":
        restored["edges"][0]["source"] = restored["nodes"][1]["id"]
    elif change == "count":
        restored["edges"] = []
    elif change == "scope":
        restored["scope"]["investigation_id"] = str(uuid4())
    else:
        restored["nodes"][0]["id"] = "1"
    with pytest.raises(ValueError):
        restored_reference_mapping(backup, restored)


def test_private_archive_never_overwrites_existing_evidence(tmp_path):
    backup, _ = archives()
    target = tmp_path / "before.json"
    migration.write_backup(target, backup)
    original = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        migration.write_backup(target, backup)
    assert target.read_bytes() == original


def test_operator_command_rejects_wrong_project_before_connecting_to_graph(
    db_session, monkeypatch
):
    from unittest.mock import MagicMock

    from flowsint_core.core import postgre_db

    graph = MagicMock()
    monkeypatch.setattr(postgre_db, "engine", db_session.get_bind())
    monkeypatch.setattr(migration.Neo4jConnection, "get_instance", graph)
    monkeypatch.setattr(
        "sys.argv", ["migration", "--project", "wrong", "--investigation", str(uuid4())]
    )
    with pytest.raises(SystemExit) as error:
        migration.main()
    assert error.value.code == 2
    graph.assert_not_called()


def test_restore_refuses_sql_divergence_before_any_repairs(db_session, monkeypatch):
    from unittest.mock import MagicMock

    from flowsint_core.core.graph.identity import GraphScope
    from flowsint_core.core.graph.references import sql_reference_snapshot

    from .test_graph_references import seed

    scope = seed(db_session, "restore-project")
    backup, restored = archives()
    for archive in (backup, restored):
        archive["scope"] = {
            "project_id": scope.project_id,
            "investigation_id": scope.investigation_id,
            "sketch_ids": list(scope.sketch_ids),
        }
        for node in archive["nodes"]:
            node["data"]["sketch_id"] = scope.sketch_ids[0]
    backup["sql_references"] = []  # Graph matches, SQL is from a different backup.
    connection = MagicMock()
    connection.query.return_value = [{"total": 0}]
    monkeypatch.setattr(migration, "snapshot", lambda *args: restored)
    before = sql_reference_snapshot(db_session.get_bind(), scope)
    with pytest.raises(ValueError, match="SQL references differ"):
        migration.repair_restored_sql_references(
            db_session.get_bind(),
            connection,
            backup,
            GraphScope(scope.project_id, scope.investigation_id, scope.sketch_ids),
            apply=True,
        )
    assert sql_reference_snapshot(db_session.get_bind(), scope) == before
