"""Scoped, repeatable repair of persisted graph references during migration.

Only structural references are rewritten. Free text and domain identifiers
(such as SocialAccount.id) are observations, not internal graph references.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine

from ..models import (
    Analysis,
    Avl4ImportOperation,
    Avl4Material,
    Chat,
    ChatMessage,
    Log,
    Scan,
)
from .identity import GraphScope

SCALAR_REFS = frozenset(
    {
        "node_id",
        "nodeId",
        "edge_id",
        "edgeId",
        "relationship_id",
        "relationshipId",
        "source",
        "target",
        "_graph_uid",
        "from_element_id",
        "to_element_id",
    }
)
LIST_REFS = frozenset(
    {
        "node_ids",
        "nodeIds",
        "edge_ids",
        "edgeIds",
        "relationshipIds",
        "relationship_ids",
        "oldNodes",
        "highlightedNodeIds",
    }
)


def remap_references(value: Any, mapping: dict[str, str], *, field: str = "") -> Any:
    if isinstance(value, str):
        return mapping.get(value, value) if field in SCALAR_REFS | LIST_REFS else value
    if isinstance(value, list):
        return [remap_references(item, mapping, field=field) for item in value]
    if isinstance(value, dict):
        graph_object = (
            "nodeType" in value
            or "nodeProperties" in value
            or {"source", "target"} <= value.keys()
        )
        return {
            key: mapping.get(item, item)
            if key == "id" and graph_object and isinstance(item, str)
            else remap_references(item, mapping, field=key)
            for key, item in value.items()
        }
    return value


def _targets(scope: GraphScope) -> list[tuple[Any, Any, tuple[str, ...]]]:
    project, investigation = scope.project_id, UUID(scope.investigation_id)
    sketches = [UUID(sketch) for sketch in scope.sketch_ids]
    materials, operations = Avl4Material.__table__, Avl4ImportOperation.__table__
    chats = Chat.__table__
    material_ids = select(materials.c.id).where(
        materials.c.project_id == project, materials.c.investigation_id == investigation
    )
    chat_ids = select(chats.c.id).where(
        chats.c.project_id == project, chats.c.investigation_id == investigation
    )
    return [
        (materials, materials.c.investigation_id == investigation, ("node_id",)),
        (operations, operations.c.material_id.in_(material_ids), ("result",)),
        (Log.__table__, Log.__table__.c.sketch_id.in_(sketches), ("content",)),
        (Scan.__table__, Scan.__table__.c.sketch_id.in_(sketches), ("details",)),
        (
            ChatMessage.__table__,
            ChatMessage.__table__.c.chat_id.in_(chat_ids),
            ("content", "context"),
        ),
        (
            Analysis.__table__,
            Analysis.__table__.c.investigation_id == investigation,
            ("content",),
        ),
    ]


def _rows(
    connection: Connection, scope: GraphScope, *, lock: bool = False
) -> list[dict[str, Any]]:
    result = []
    for table, restriction, fields in _targets(scope):
        query = (
            select(table.c.id, *(table.c[name] for name in fields))
            .where(table.c.project_id == scope.project_id, restriction)
            .order_by(table.c.id)
        )
        if lock:
            query = query.with_for_update()
        for row in connection.execute(query).mappings():
            result.append(
                {
                    "table": table.name,
                    "id": str(row["id"]),
                    "fields": {name: row[name] for name in fields},
                }
            )
    return result


def sql_reference_snapshot(engine: Engine, scope: GraphScope) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return _rows(connection, scope)


def repair_sql_references(
    engine: Engine,
    scope: GraphScope,
    mapping: dict[str, str],
    *,
    expected: list[dict[str, Any]] | None = None,
) -> int:
    """Apply one SQL transaction after graph apply; retries use durable aliases.

    PostgreSQL and Neo4j are independent transactions. If this phase fails the
    graph retains aliases, so the command can safely resume without a reverse
    graph migration or rewriting unstructured evidence.
    """
    targets = {
        table.name: (table, restriction) for table, restriction, _ in _targets(scope)
    }
    count = 0
    with engine.begin() as connection:
        rows = _rows(connection, scope, lock=True)
        if expected is not None and rows != expected:
            raise ValueError(
                "SQL references changed since backup; capture a fresh backup and retry"
            )
        for row in rows:
            rewritten = {
                name: remap_references(value, mapping, field=name)
                for name, value in row["fields"].items()
            }
            if rewritten == row["fields"]:
                continue
            table, restriction = targets[row["table"]]
            connection.execute(
                update(table)
                .where(
                    table.c.id == UUID(row["id"]),
                    table.c.project_id == scope.project_id,
                    restriction,
                )
                .values(**rewritten)
            )
            count += 1
    return count
