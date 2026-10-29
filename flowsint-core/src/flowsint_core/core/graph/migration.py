"""Explicit, backed-up migration from sketch-owned to investigation-owned data.

The command is dry-run by default. It never connects to any storage other than
its configured SQL/Neo4j endpoints. Run with API and workers quiesced; never run
this as part of application startup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from .connection import Neo4jConnection
from .identity import (
    PRESENTATION,
    GraphScope,
    check_identity_compatibility,
    identity_keys,
)
from .references import remap_references, repair_sql_references, sql_reference_snapshot
from .repository import Neo4jGraphRepository, _identifier
from .schema import install_schema


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def snapshot(connection: Any, scope: GraphScope) -> dict[str, Any]:
    """Capture legacy records, including tombstones and edge properties."""
    nodes = connection.query(
        """MATCH (n) WHERE n.sketch_id IN $sketches
        AND NOT n:GraphEntity AND NOT n:GraphView
        RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS data ORDER BY id""",
        {"sketches": list(scope.sketch_ids)},
    )
    edges = connection.query(
        """MATCH (a)-[r]->(b)
        WHERE elementId(a) IN $ids OR elementId(b) IN $ids
        RETURN elementId(r) AS id, elementId(a) AS source, elementId(b) AS target,
            type(r) AS type, properties(r) AS data ORDER BY id""",
        {"ids": [n["id"] for n in nodes]},
    )
    return {
        "version": 1,
        "scope": {
            "project_id": scope.project_id,
            "investigation_id": scope.investigation_id,
            "sketch_ids": list(scope.sketch_ids),
        },
        "nodes": nodes,
        "edges": edges,
    }


def _properties(node: dict[str, Any], scope: GraphScope) -> dict[str, Any]:
    props = dict(node["data"])
    if props.get("project_id") not in (None, scope.project_id):
        raise ValueError("Legacy entity has a conflicting project")
    props["nodeType"] = str(
        props.get("nodeType") or props.get("type") or node["labels"][0]
    ).lower()
    props["nodeLabel"] = props.get("nodeLabel", props.get("label", "Unknown"))
    if props["nodeType"] in {"avl4_card", "avl4material"}:
        props["nodeType"] = "avl4_card"
        kind, card_id = (
            props.get("nodeProperties.card_type"),
            props.get("nodeProperties.card_id"),
        )
        if kind and card_id:
            props["avl4_import_key"] = hashlib.sha256(
                json.dumps(
                    [
                        scope.project_id,
                        scope.investigation_id,
                        kind,
                        props.get("nodeProperties.source_project_id"),
                        card_id,
                    ],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
    return props


def validate_snapshot(backup: dict[str, Any]) -> GraphScope:
    if backup.get("version") != 1:
        raise ValueError("Unsupported graph backup")
    scope = GraphScope(
        backup["scope"]["project_id"],
        backup["scope"]["investigation_id"],
        tuple(backup["scope"]["sketch_ids"]),
    )
    ids = {n["id"] for n in backup["nodes"]}
    keys_by_group: list[set[str]] = []
    for node in backup["nodes"]:
        if node["data"].get("sketch_id") not in scope.sketch_ids:
            raise ValueError("Backup contains an entity outside the investigation")
        props = _properties(node, scope)
        keys = set(identity_keys(props))
        groups = [g for g in keys_by_group if g.intersection(keys)]
        for group in groups:
            keys.update(group)
            keys_by_group.remove(group)
        check_identity_compatibility(list(keys))
        if keys:
            keys_by_group.append(keys)
    nodes_by_id = {n["id"]: n for n in backup["nodes"]}
    for edge in backup["edges"]:
        _identifier(edge["type"])
        if edge["source"] not in ids or edge["target"] not in ids:
            raise ValueError("Legacy edge crosses the investigation boundary")
        source_view = nodes_by_id[edge["source"]]["data"]["sketch_id"]
        target_view = nodes_by_id[edge["target"]]["data"]["sketch_id"]
        if source_view != target_view or edge["data"].get("sketch_id") not in (
            None,
            source_view,
        ):
            raise ValueError("Legacy edge has a conflicting view")
    return scope


def write_backup(path: Path, backup: dict[str, Any]) -> None:
    validate_snapshot(backup)
    with os.fdopen(
        os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
    ) as file:
        file.write(_bytes(backup))
        file.flush()
        os.fsync(file.fileno())


def restored_reference_mapping(
    backup: dict[str, Any], restored: dict[str, Any]
) -> dict[str, str]:
    """Verify a native restore before repairing database-UUID-based elementIds.

    Native dump/load can replace the database UUID while preserving record IDs.
    Numeric suffixes alone are NEVER sufficient evidence: every label, property,
    relationship type and endpoint must match the archived investigation exactly.
    """
    original_scope, current_scope = (
        validate_snapshot(backup),
        validate_snapshot(restored),
    )
    if original_scope != current_scope:
        raise ValueError("Restored graph scope differs from backup")

    def record_key(element_id: str) -> tuple[str, str]:
        parts = element_id.split(":")
        if len(parts) != 3 or parts[0] not in {"4", "5"} or not parts[2].isdigit():
            raise ValueError("Unsupported restored elementId format")
        UUID(parts[1])
        return parts[0], parts[2]

    mapping: dict[str, str] = {}
    for collection in ("nodes", "edges"):
        current = {record_key(r["id"]): r for r in restored[collection]}
        if len(current) != len(restored[collection]) or len(current) != len(
            backup[collection]
        ):
            raise ValueError("Restored graph record count differs from backup")
        for old in backup[collection]:
            new = current.get(record_key(old["id"]))
            if new is None or old["data"] != new["data"]:
                raise ValueError("Restored graph properties differ from backup")
            if collection == "nodes":
                if sorted(old["labels"]) != sorted(new["labels"]):
                    raise ValueError("Restored graph labels differ from backup")
            elif (
                old["type"] != new["type"]
                or mapping[old["source"]] != new["source"]
                or mapping[old["target"]] != new["target"]
            ):
                raise ValueError("Restored relationship differs from backup")
            mapping[old["id"]] = new["id"]
    return mapping


def repair_restored_sql_references(
    engine: Any,
    connection: Any,
    backup: dict[str, Any],
    scope: GraphScope,
    *,
    apply: bool = False,
) -> dict[str, int | str]:
    """Reconcile restored legacy graph/SQL while all writers remain stopped."""
    if validate_snapshot(backup) != scope or "sql_references" not in backup:
        raise ValueError(
            "Restore requires the matching graph and SQL reference archive"
        )
    canonical = connection.query(
        "MATCH (n:GraphEntity {scope_key: $scope}) RETURN count(n) AS total",
        {"scope": scope.key},
    )
    if canonical and canonical[0]["total"]:
        raise ValueError(
            "Restore reconciliation requires the pre-migration legacy graph"
        )
    mapping = restored_reference_mapping(backup, snapshot(connection, scope))
    current_sql = sql_reference_snapshot(engine, scope)
    if current_sql not in (
        backup["sql_references"],
        remap_references(backup["sql_references"], mapping),
    ):
        raise ValueError("Restored SQL references differ from the archived snapshot")
    repaired = (
        repair_sql_references(engine, scope, mapping, expected=current_sql)
        if apply
        else 0
    )
    return {
        "mapped_records": len(mapping),
        "sql_rows_repaired": repaired,
        "status": "restored references repaired"
        if apply
        else "restore verified (dry run)",
    }


def apply_backup(connection: Neo4jConnection, backup: dict[str, Any]) -> dict[str, str]:
    """Migrate one entire investigation atomically; refuse a stale backup."""
    scope = validate_snapshot(backup)
    repo = Neo4jGraphRepository(connection, scope=scope)

    def operation(tx: Any) -> dict[str, str]:
        tx.run(
            """MERGE (g:GraphScope {key: $scope})
            SET g.revision = coalesce(g.revision, 0) + 1 RETURN g.deleted_at AS deleted_at""",
            scope=scope.key,
        ).single()
        state = tx.run(
            "MATCH (g:GraphScope {key: $scope}) RETURN g.deleted_at AS deleted_at",
            scope=scope.key,
        ).single()
        if state and state.get("deleted_at"):
            raise PermissionError("Cannot migrate a deleted investigation")

        class Reader:
            def query(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
                return cast(list[dict[str, Any]], tx.run(query, params).data())

        current = snapshot(Reader(), scope)
        if not current["nodes"]:
            # Retrying after success must not create duplicate appearances or
            # revive deleted source records.
            rows = tx.run(
                """MATCH (n:GraphEntity {scope_key: $scope})
                UNWIND coalesce(n.legacy_ids, []) AS old RETURN old, n.uid AS id
                UNION ALL
                MATCH ()-[r]->() WHERE r.scope_key = $scope
                UNWIND coalesce(r.legacy_ids, []) AS old RETURN old, r.uid AS id""",
                scope=scope.key,
            ).data()
            return {r["old"]: r["id"] for r in rows}
        if _bytes(current) != _bytes(
            {key: backup[key] for key in ("version", "scope", "nodes", "edges")}
        ):
            raise ValueError(
                "Graph changed since backup; quiesce writers and capture a fresh backup"
            )
        # Original data is recoverable from the fsynced archive; transaction
        # rollback restores it automatically on any failure during apply.
        tx.run(
            """MATCH (n) WHERE elementId(n) IN $ids DETACH DELETE n""",
            ids=[n["id"] for n in backup["nodes"]],
        ).consume()
        mapping: dict[str, str] = {}
        for node in sorted(
            backup["nodes"], key=lambda n: n["data"].get("deleted_at") is None
        ):
            props = _properties(node, scope)
            props.pop("id", None)
            # Unknown/name-only identities deliberately remain independent.
            uid = repo._upsert_node(
                tx, props, props["sketch_id"], trusted=props["nodeType"] == "avl4_card"
            )
            tx.run(
                """MATCH (n:GraphEntity {scope_key: $scope, uid: $uid})
                SET n.legacy_ids = coalesce(n.legacy_ids, []) + $old,
                    n.migration_records = coalesce(n.migration_records, []) + $record""",
                scope=scope.key,
                uid=uid,
                old=[node["id"]],
                record=[_bytes(node).decode()],
            ).consume()
            tx.run(
                """MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->
                (:GraphEntity {scope_key: $scope, uid: $uid})
                SET m.migration_layouts = coalesce(m.migration_layouts, []) + $layout""",
                scope=scope.key,
                sketch=props["sketch_id"],
                uid=uid,
                layout=[
                    _bytes(
                        {
                            "legacy_id": node["id"],
                            **{k: v for k, v in props.items() if k in PRESENTATION},
                        }
                    ).decode()
                ],
            ).consume()
            mapping[node["id"]] = uid
        # A later alias bridge may coalesce two earlier migrated entities.
        aliases = tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope})
            UNWIND coalesce(n.legacy_ids, []) AS old RETURN old, n.uid AS id""",
            scope=scope.key,
        ).data()
        mapping.update({r["old"]: r["id"] for r in aliases})
        node_records = {n["id"]: n for n in backup["nodes"]}
        for edge in sorted(
            backup["edges"], key=lambda e: e["data"].get("deleted_at") is None
        ):
            source, target = mapping[edge["source"]], mapping[edge["target"]]
            view = (
                edge["data"].get("sketch_id")
                or node_records[edge["source"]]["data"]["sketch_id"]
            )
            deleted = edge["data"].get("deleted_at")
            props = dict(edge["data"])
            result = repo._edge(
                tx,
                source,
                target,
                edge["type"],
                props,
                [] if deleted else [view],
                discriminator=str(props.get("event_key", props.get("hash", ""))),
                deleted_at=deleted,
            )
            tx.run(
                """MATCH ()-[r]->() WHERE r.scope_key = $scope AND r.uid = $uid
                SET r.legacy_ids = coalesce(r.legacy_ids, []) + $old,
                    r.migration_records = coalesce(r.migration_records, []) + $record""",
                scope=scope.key,
                uid=result["id"],
                old=[edge["id"]],
                record=[_bytes(edge).decode()],
            ).consume()
            mapping[edge["id"]] = result["id"]
        active_pairs = {
            (mapping[n["id"]], n["data"]["sketch_id"])
            for n in backup["nodes"]
            if not n["data"].get("deleted_at")
        }
        active_ids = {uid for uid, _ in active_pairs}
        for node in backup["nodes"]:
            deleted = node["data"].get("deleted_at")
            if not deleted:
                continue
            uid, view = mapping[node["id"]], node["data"]["sketch_id"]
            if (uid, view) not in active_pairs:
                tx.run(
                    """MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->
                    (:GraphEntity {scope_key: $scope, uid: $uid}) DELETE m""",
                    scope=scope.key,
                    sketch=view,
                    uid=uid,
                ).consume()
            if uid not in active_ids:
                tx.run(
                    """MATCH (n:GraphEntity {scope_key: $scope, uid: $uid}) SET n.deleted_at = $deleted""",
                    scope=scope.key,
                    uid=uid,
                    deleted=deleted,
                ).consume()
        tx.run(
            """MATCH (g:GraphScope {key: $scope}) SET g.schema_version = 2""",
            scope=scope.key,
        ).consume()
        return mapping

    return connection.run_transaction(operation)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--investigation", required=True, type=UUID)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--restore-references",
        action="store_true",
        help="Verify a native rollback and repair SQL elementId references using an existing archive",
    )
    args = parser.parse_args()
    if args.apply and args.backup is None:
        parser.error("--apply requires --backup (a new private archive file)")
    if args.restore_references and args.backup is None:
        parser.error(
            "--restore-references requires --backup (the pre-migration archive)"
        )
    from sqlalchemy import select

    from ..models import Investigation, Sketch
    from ..postgre_db import engine

    # This is an operator command, not a request. Explicitly scoped Core SQL
    # avoids constructing any replicated Auth user/project identity.
    with engine.connect() as db:
        investigation = db.execute(
            select(Investigation.__table__.c.id).where(
                Investigation.__table__.c.id == args.investigation,
                Investigation.__table__.c.project_id == args.project,
            )
        ).first()
        if investigation is None:
            parser.error("Investigation does not exist in the selected project")
        rows = db.execute(
            select(Sketch.__table__.c.id)
            .where(
                Sketch.__table__.c.investigation_id == args.investigation,
                Sketch.__table__.c.project_id == args.project,
            )
            .order_by(Sketch.__table__.c.id)
        ).all()
    scope = GraphScope(
        args.project, str(args.investigation), tuple(str(r[0]) for r in rows)
    )
    connection = Neo4jConnection.get_instance()
    if args.restore_references:
        restored_backup = json.loads(args.backup.read_text())
        print(
            json.dumps(
                repair_restored_sql_references(
                    engine, connection, restored_backup, scope, apply=args.apply
                )
            )
        )
        return 0
    backup = snapshot(connection, scope)
    backup["sql_references"] = sql_reference_snapshot(engine, scope)
    validate_snapshot(backup)
    print(
        json.dumps(
            {
                "legacy_nodes": len(backup["nodes"]),
                "legacy_edges": len(backup["edges"]),
                "apply": args.apply,
            }
        )
    )
    if args.backup:
        write_backup(args.backup, backup)
    if args.apply:
        install_schema(connection)
        mapping = apply_backup(connection, backup)
        repaired = repair_sql_references(
            engine, scope, mapping, expected=backup["sql_references"]
        )
        print(
            json.dumps(
                {
                    "mapped_records": len(mapping),
                    "sql_rows_repaired": repaired,
                    "status": "migrated",
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
