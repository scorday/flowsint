"""Investigation-owned Neo4j entities with independent sketch memberships.

All mutations acquire the investigation lock in the same database transaction.
This serialises identity resolution (including alias promotion) and typed edge
upserts; two concurrent enrichers cannot create copies of the same entity.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar
from uuid import uuid4

from .connection import GraphConnectionProtocol, Neo4jConnection
from .identity import (
    RESERVED,
    GraphScope,
    IdentityConflict,
    check_identity_compatibility,
    identity_keys,
    merge_properties,
    split_properties,
)
from .schema import require_schema
from .types import GraphDict

T = TypeVar("T")


def _snapshot_time(properties: GraphDict, key: str) -> datetime:
    value = properties.get(f"nodeProperties.{key}")
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Snapshot times require a timezone")
    return parsed.astimezone(timezone.utc)


def _identifier(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(c in "`\\" or ord(c) < 32 for c in value)
    ):
        raise ValueError("Invalid graph identifier")
    return f"`{value}`"


class Neo4jGraphRepository:
    def __init__(
        self,
        neo4j_connection: GraphConnectionProtocol | None = None,
        *,
        scope: GraphScope,
    ):
        self._connection = neo4j_connection or Neo4jConnection.get_instance()
        self.scope = scope
        require_schema(self._connection)
        self._batch_operations: list[tuple[str, dict[str, Any]]] = []
        self._batch_size = 100

    def _params(self, sketch_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.scope.sketch_ids and sketch_id not in self.scope.sketch_ids:
            raise PermissionError("View does not belong to this investigation")
        return {
            **kwargs,
            "scope": self.scope.key,
            "sketch": sketch_id,
            "project": self.scope.project_id,
            "investigation": self.scope.investigation_id,
        }

    def _write(
        self,
        sketch_id: str,
        operation: Callable[[Any], T],
        *,
        allow_deleted_scope: bool = False,
        allow_deleted_view: bool = False,
    ) -> T:
        def locked(tx: Any) -> T:
            # Constraints are installed by the graph migration/bootstrap command.
            state = tx.run(
                """MERGE (g:GraphScope {key: $scope})
                ON CREATE SET g.project_id = $project, g.investigation_id = $investigation
                SET g.revision = coalesce(g.revision, 0) + 1 RETURN g.deleted_at AS deleted_at""",
                self._params(sketch_id),
            ).single()
            if state and state.get("deleted_at") and not allow_deleted_scope:
                raise PermissionError("Investigation graph has been deleted")
            view = tx.run(
                """OPTIONAL MATCH (v:GraphView {scope_key: $scope, sketch_id: $sketch})
                RETURN v.deleted_at AS deleted_at""",
                self._params(sketch_id),
            ).single()
            if view and view.get("deleted_at") and not allow_deleted_view:
                raise PermissionError("Graph view has been deleted")
            # Refuse to mix legacy sketch-owned records with the new graph.
            legacy = tx.run(
                """MATCH (n) WHERE n.sketch_id IN $sketches
                AND NOT n:GraphView AND NOT n:GraphEntity
                RETURN count(n) AS total""",
                sketches=list(self.scope.sketch_ids) or [sketch_id],
            ).single()
            if legacy and legacy["total"]:
                raise RuntimeError("Investigation graph migration is required")
            return operation(tx)

        return self._connection.run_transaction(locked)

    def _view(self, tx: Any, sketch_id: str) -> None:
        tx.run(
            """MERGE (v:GraphView {scope_key: $scope, sketch_id: $sketch})
            ON CREATE SET v.project_id = $project, v.investigation_id = $investigation""",
            self._params(sketch_id),
        ).consume()

    def _find(
        self,
        tx: Any,
        node_id: str,
        *,
        sketch_id: str | None = None,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        rows = tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope})
            WHERE (n.uid = $id OR $id IN coalesce(n.legacy_ids, [])) AND ($include_deleted OR n.deleted_at IS NULL)
            AND ($sketch IS NULL OR EXISTS {
                MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[:SHOWS]->(n) })
            RETURN properties(n) AS data""",
            scope=self.scope.key,
            id=node_id,
            sketch=sketch_id,
            include_deleted=include_deleted,
        ).data()
        return rows[0]["data"] if rows else None

    def _show(
        self, tx: Any, sketch_id: str, uid: str, presentation: GraphDict | None = None
    ) -> None:
        self._view(tx, sketch_id)
        tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope, uid: $uid})
            MATCH (v:GraphView {scope_key: $scope, sketch_id: $sketch})
            MERGE (v)-[m:SHOWS]->(n)
            ON CREATE SET m += $presentation
            ON MATCH SET m.migration_layouts = coalesce(m.migration_layouts, []) + coalesce($presentation.migration_layouts, [])""",
            self._params(sketch_id, uid=uid, presentation=presentation or {}),
        ).consume()

    def _upsert_node(
        self, tx: Any, node_obj: GraphDict, sketch_id: str, *, trusted: bool = False
    ) -> str:
        kind = str(node_obj.get("nodeType", "")).lower()
        _identifier(kind)
        if kind == "avl4_card" and not trusted:
            existing = self._find(tx, str(node_obj.get("id") or ""))
            if existing and existing["nodeType"] == "avl4_card":
                # A view import can reuse a checked snapshot, never replace it.
                _, presentation = split_properties(node_obj)
                self._show(tx, sketch_id, existing["uid"], presentation)
                return str(existing["uid"])
            raise ValueError("AVL4 snapshots can only be changed through card import")
        entity, presentation = split_properties(node_obj)
        entity["nodeType"] = kind
        keys = identity_keys(entity)
        if trusted and node_obj.get("avl4_import_key"):
            keys = [f"avl4_card:{node_obj['avl4_import_key']}"]
            entity.update({k: v for k, v in node_obj.items() if k.startswith("avl4_")})
        candidates = tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope})
            WHERE (size($keys) > 0 AND any(k IN $keys WHERE k IN n.identity_keys))
                OR ((n.uid = $id OR $id IN coalesce(n.legacy_ids, [])) AND n.deleted_at IS NULL)
            RETURN properties(n) AS data ORDER BY n.uid""",
            scope=self.scope.key,
            keys=keys,
            id=node_obj.get("id"),
        ).data()
        # A supplied ID is only a hint within this investigation, never an authority
        # to change the type or the authoritative identity of an existing object.
        candidates = [r["data"] for r in candidates]
        if any(c["nodeType"] != kind for c in candidates):
            raise IdentityConflict("Cannot change an entity type")
        all_keys = sorted(
            set(keys).union(*(set(c.get("identity_keys", [])) for c in candidates))
        )
        check_identity_compatibility(all_keys)
        old = candidates[0] if candidates else {}
        uid = old.get("uid") or str(uuid4())
        for duplicate in candidates[1:]:
            self._coalesce(tx, old["uid"], duplicate["uid"], sketch_id)
        if candidates:
            old = self._find(tx, uid, include_deleted=True) or old
        if kind == "avl4_card" and old:
            previous = (
                _snapshot_time(old, "source_updated_at"),
                _snapshot_time(old, "captured_at"),
            )
            incoming = (
                _snapshot_time(entity, "source_updated_at"),
                _snapshot_time(entity, "captured_at"),
            )
            if incoming < previous:
                ignored = merge_properties(
                    old,
                    entity,
                    source=f"ignored stale card observation from sketch:{sketch_id}",
                )
                if ignored.get("graph_history"):
                    tx.run(
                        """MATCH (n:GraphEntity {scope_key: $scope, uid: $uid}) SET n.graph_history = $history""",
                        scope=self.scope.key,
                        uid=uid,
                        history=ignored["graph_history"],
                    ).consume()
                self._show(tx, sketch_id, uid, presentation)
                return uid
        if old.get("nodeMetadata.created_at"):
            entity.pop("nodeMetadata.created_at", None)
        props = merge_properties(old, entity, source=f"sketch:{sketch_id}")
        props.update(
            {
                "uid": uid,
                "scope_key": self.scope.key,
                "identity_keys": all_keys,
                "project_id": self.scope.project_id,
                "investigation_id": self.scope.investigation_id,
            }
        )
        tx.run(
            f"""MERGE (n:GraphEntity {{scope_key: $scope, uid: $uid}})
            SET n:{_identifier(kind)}, n += $props, n.deleted_at = null""",
            scope=self.scope.key,
            uid=uid,
            props=props,
        ).consume()
        self._show(tx, sketch_id, uid, presentation)
        return uid

    def create_node(self, node_obj: GraphDict, sketch_id: str) -> str:
        if str(node_obj.get("nodeType", "")).lower() == "avl4_card":
            raise ValueError("AVL4 snapshots can only be changed through card import")
        return self._write(
            sketch_id, lambda tx: self._upsert_node(tx, node_obj, sketch_id)
        )

    def project_material(self, node_obj: GraphDict, sketch_id: str) -> str:
        return self._write(
            sketch_id,
            lambda tx: self._upsert_node(tx, node_obj, sketch_id, trusted=True),
        )

    def _edge(
        self,
        tx: Any,
        source: str,
        target: str,
        label: str,
        props: GraphDict,
        view_ids: list[str],
        *,
        discriminator: str = "",
        deleted_at: str | None = None,
        preferred_uid: str | None = None,
    ) -> dict[str, Any]:
        label_quoted = _identifier(label)
        # Different observations of a relation share one edge. Parallel events
        # (e.g. blockchain transactions) carry their own discriminator.
        key = json.dumps([source, target, label, discriminator], separators=(",", ":"))
        old_row = tx.run(
            f"""MATCH (a:GraphEntity {{scope_key: $scope, uid: $source}})
            -[r:{label_quoted} {{graph_edge_key: $key}}]->(b:GraphEntity {{scope_key: $scope, uid: $target}})
            RETURN properties(r) AS data""",
            scope=self.scope.key,
            source=source,
            target=target,
            key=key,
        ).single()
        old = old_row["data"] if old_row else {}
        entity, _ = split_properties(props)
        entity.pop("graph_edge_key", None)
        merged = merge_properties(old, entity, source="edge observation")
        merged.update(
            {
                "uid": old.get("uid") or preferred_uid or str(uuid4()),
                "scope_key": self.scope.key,
                "graph_edge_key": key,
                "view_ids": sorted(set(old.get("view_ids", []) + view_ids)),
                "deleted_at": (
                    None
                    if (old_row and old.get("deleted_at") is None) or deleted_at is None
                    else deleted_at
                ),
            }
        )
        tx.run(
            f"""MATCH (a:GraphEntity {{scope_key: $scope, uid: $source}})
            MATCH (b:GraphEntity {{scope_key: $scope, uid: $target}})
            MERGE (a)-[r:{label_quoted} {{graph_edge_key: $key}}]->(b)
            SET r += $props""",
            scope=self.scope.key,
            source=source,
            target=target,
            key=key,
            props=merged,
        ).consume()
        return {
            "id": merged["uid"],
            "source": source,
            "target": target,
            "type": label,
            "data": merged,
        }

    def create_relationship_by_element_id(
        self,
        from_element_id: str,
        to_element_id: str,
        rel_label: str,
        sketch_id: str,
        properties: GraphDict | None = None,
    ) -> dict[str, Any] | None:
        def operation(tx: Any) -> dict[str, Any] | None:
            a = self._find(tx, from_element_id, sketch_id=sketch_id)
            b = self._find(tx, to_element_id, sketch_id=sketch_id)
            if not a or not b:
                return None
            props = properties or {}
            return self._edge(
                tx,
                a["uid"],
                b["uid"],
                rel_label,
                props,
                [sketch_id],
                discriminator=str(props.get("event_key", "")),
            )

        return self._write(sketch_id, operation)

    def create_relationship(self, rel_obj: GraphDict, sketch_id: str) -> None:
        def operation(tx: Any) -> None:
            ids = []
            for side in ("from", "to"):
                if rel_obj.get(f"{side}_id"):
                    node = self._find(tx, rel_obj[f"{side}_id"], sketch_id=sketch_id)
                    if not node:
                        raise ValueError("Unknown view relationship endpoint")
                    ids.append(node["uid"])
                    continue
                # Descriptors carry domain properties, so matching no longer
                # depends on a mutable display label.
                obj = rel_obj.get(f"{side}_properties", {})
                keys = identity_keys({**obj, "nodeType": rel_obj[f"{side}_type"]})
                rows = tx.run(
                    """MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[:SHOWS]->(n:GraphEntity)
                    WHERE n.deleted_at IS NULL AND n.nodeType = $kind AND
                    ((size($keys) > 0 AND any(k IN $keys WHERE k IN n.identity_keys)) OR
                     (size($keys) = 0 AND n.nodeLabel = $label))
                    RETURN n.uid AS id""",
                    self._params(
                        sketch_id,
                        keys=keys,
                        kind=rel_obj[f"{side}_type"],
                        label=rel_obj[f"{side}_label"],
                    ),
                ).data()
                if len(rows) != 1:
                    raise IdentityConflict(
                        "Relationship endpoint is missing or ambiguous; use its entity ID"
                    )
                ids.append(rows[0]["id"])
            self._edge(tx, ids[0], ids[1], rel_obj["rel_label"], {}, [sketch_id])

        self._write(sketch_id, operation)

    def update_node(
        self, element_id: str, updates: GraphDict, sketch_id: str
    ) -> str | None:
        def operation(tx: Any) -> str | None:
            old = self._find(tx, element_id, sketch_id=sketch_id)
            if not old:
                return None
            entity, presentation = split_properties(updates)
            if old["nodeType"] == "avl4_card":
                if entity:
                    raise ValueError(
                        "AVL4 snapshots can only be changed through card import"
                    )
                uid = str(old["uid"])
            else:
                uid = self._upsert_node(
                    tx, {**old, **entity, "id": old["uid"]}, sketch_id
                )
            tx.run(
                """MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->
                (:GraphEntity {scope_key: $scope, uid: $uid}) SET m += $presentation""",
                self._params(sketch_id, uid=uid, presentation=presentation),
            ).consume()
            return uid

        return self._write(sketch_id, operation)

    def _graph(
        self, sketch_id: str | None, limit: int = 100000
    ) -> dict[str, list[GraphDict]]:
        if sketch_id is not None:
            self._params(sketch_id)
        self._require_migrated()
        nodes = self._connection.query(
            """MATCH (n:GraphEntity {scope_key: $scope})
            WHERE n.deleted_at IS NULL
            OPTIONAL MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(n)
            WITH n, m WHERE $sketch IS NULL OR m IS NOT NULL
            RETURN n.uid AS id, labels(n) AS labels, properties(n) AS data, properties(m) AS presentation
            ORDER BY n.uid LIMIT $limit""",
            {"scope": self.scope.key, "sketch": sketch_id, "limit": limit},
        )
        for node in nodes:
            node["data"] = {**node["data"], **(node.pop("presentation", None) or {})}
        edges = self._connection.query(
            """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
            WHERE r.scope_key = $scope AND r.deleted_at IS NULL AND a.uid IN $ids AND b.uid IN $ids
                AND ($sketch IS NULL OR $sketch IN r.view_ids)
            RETURN r.uid AS id, type(r) AS type, a.uid AS source, b.uid AS target, properties(r) AS data
            ORDER BY r.uid""",
            {
                "scope": self.scope.key,
                "sketch": sketch_id,
                "ids": [n["id"] for n in nodes],
            },
        )
        return {"nodes": nodes, "edges": edges}

    def get_sketch_graph(
        self, sketch_id: str, limit: int = 100000
    ) -> dict[str, list[GraphDict]]:
        return self._graph(sketch_id, limit)

    def _require_migrated(self) -> None:
        # Detect un-migrated data on reads too: an empty graph must not hide it.
        legacy = self._connection.query(
            """MATCH (n) WHERE n.sketch_id IN $sketches
            AND NOT n:GraphView AND NOT n:GraphEntity RETURN count(n) AS total""",
            {"sketches": list(self.scope.sketch_ids)},
        )
        if legacy and legacy[0]["total"]:
            raise RuntimeError("Investigation graph migration is required")

    def get_investigation_graph(
        self, limit: int = 100000
    ) -> dict[str, list[GraphDict]]:
        return self._graph(None, limit)

    def get_nodes_by_ids(self, node_ids: list[str], sketch_id: str) -> list[GraphDict]:
        self._params(sketch_id)
        self._require_migrated()
        nodes = self._connection.query(
            """MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(n:GraphEntity {scope_key: $scope})
            WHERE n.deleted_at IS NULL AND (n.uid IN $ids OR any(id IN coalesce(n.legacy_ids, []) WHERE id IN $ids))
            RETURN n.uid AS id, labels(n) AS labels, properties(n) AS data, properties(m) AS presentation
            ORDER BY n.uid""",
            {"scope": self.scope.key, "sketch": sketch_id, "ids": node_ids},
        )
        for node in nodes:
            node["data"] = {**node["data"], **(node.pop("presentation", None) or {})}
        return nodes

    def get_neighbors(self, node_id: str, sketch_id: str) -> dict[str, Any]:
        graph = self.get_sketch_graph(sketch_id)
        center = next(
            (
                n["id"]
                for n in graph["nodes"]
                if n["id"] == node_id or node_id in n["data"].get("legacy_ids", [])
            ),
            None,
        )
        edges = (
            [e for e in graph["edges"] if center in (e["source"], e["target"])]
            if center
            else []
        )
        ids = {center} | {e[s] for e in edges for s in ("source", "target")}
        return {"nodes": [n for n in graph["nodes"] if n["id"] in ids], "edges": edges}

    def attach_subgraph(
        self, node_ids: list[str], edge_ids: list[str], sketch_id: str
    ) -> None:
        """Attach only explicitly selected edges, including their endpoints."""

        def operation(tx: Any) -> None:
            edges = tx.run(
                """UNWIND $ids AS requested
                MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
                WHERE (r.uid = requested OR requested IN coalesce(r.legacy_ids, [])) AND r.scope_key = $scope AND r.deleted_at IS NULL
                    AND a.deleted_at IS NULL AND b.deleted_at IS NULL
                RETURN a.uid AS source, b.uid AS target, r.uid AS id, collect(requested) AS requested""",
                scope=self.scope.key,
                ids=edge_ids,
            ).data()
            if {uid for e in edges for uid in e["requested"]} != set(edge_ids):
                raise ValueError("Unknown investigation edge")
            ids = set(node_ids) | {e[s] for e in edges for s in ("source", "target")}
            entities = [self._find(tx, uid) for uid in ids]
            if any(n is None for n in entities):
                raise ValueError("Unknown investigation entity")
            for node in entities:
                if node is None:
                    raise ValueError("Unknown investigation entity")
                self._show(tx, sketch_id, node["uid"])
            tx.run(
                """MATCH ()-[r]->() WHERE r.scope_key = $scope AND (r.uid IN $ids OR any(id IN $ids WHERE id IN coalesce(r.legacy_ids, [])))
                SET r.view_ids = reduce(views = coalesce(r.view_ids, []), v IN [$sketch] |
                    CASE WHEN v IN views THEN views ELSE views + v END)""",
                self._params(sketch_id, ids=edge_ids),
            ).consume()

        self._write(sketch_id, operation)

    def delete_nodes(self, node_ids: list[str], sketch_id: str) -> int:
        """Detach from this view; the canonical entity remains in the investigation."""

        def operation(tx: Any) -> int:
            rows = tx.run(
                """MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(n:GraphEntity)
                WHERE n.uid IN $ids OR any(id IN $ids WHERE id IN coalesce(n.legacy_ids, []))
                WITH m, n DELETE m RETURN n.uid AS id""",
                self._params(sketch_id, ids=node_ids),
            ).data()
            tx.run(
                """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
                WHERE r.scope_key = $scope AND (a.uid IN $ids OR b.uid IN $ids)
                SET r.view_ids = [v IN coalesce(r.view_ids, []) WHERE v <> $sketch]""",
                self._params(sketch_id, ids=[r["id"] for r in rows]),
            ).consume()
            return len(rows)

        return self._write(sketch_id, operation)

    def delete_relationships(self, relationship_ids: list[str], sketch_id: str) -> int:
        def operation(tx: Any) -> int:
            row = tx.run(
                """MATCH ()-[r]->() WHERE r.scope_key = $scope AND (r.uid IN $ids OR any(id IN $ids WHERE id IN coalesce(r.legacy_ids, []))) AND $sketch IN r.view_ids
                SET r.view_ids = [v IN r.view_ids WHERE v <> $sketch] RETURN count(r) AS total""",
                self._params(sketch_id, ids=relationship_ids),
            ).single()
            return row["total"] if row else 0

        return self._write(sketch_id, operation)

    def delete_all_sketch_nodes(self, sketch_id: str) -> int:
        def operation(tx: Any) -> int:
            count = tx.run(
                """MATCH (v:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->()
                RETURN count(m) AS total""",
                self._params(sketch_id),
            ).single()
            tx.run(
                """MERGE (v:GraphView {scope_key: $scope, sketch_id: $sketch})
                SET v.deleted_at = $now
                WITH v OPTIONAL MATCH (v)-[m:SHOWS]->() DELETE m""",
                self._params(sketch_id, now=datetime.now(timezone.utc).isoformat()),
            ).consume()
            tx.run(
                """MATCH ()-[r]->() WHERE r.scope_key = $scope AND $sketch IN r.view_ids
                SET r.view_ids = [v IN r.view_ids WHERE v <> $sketch]""",
                self._params(sketch_id),
            ).consume()
            return count["total"] if count else 0

        return self._write(sketch_id, operation, allow_deleted_view=True)

    def delete_from_investigation(
        self, node_ids: list[str], edge_ids: list[str], sketch_id: str
    ) -> None:
        def operation(tx: Any) -> None:
            tx.run(
                """MATCH (n:GraphEntity {scope_key: $scope}) WHERE (n.uid IN $ids OR any(id IN $ids WHERE id IN coalesce(n.legacy_ids, [])))
                SET n.deleted_at = $now
                WITH n OPTIONAL MATCH (n)-[r]-(:GraphEntity {scope_key: $scope})
                SET r.deleted_at = $now, r.view_ids = []""",
                scope=self.scope.key,
                ids=node_ids,
                now=datetime.now(timezone.utc).isoformat(),
            ).consume()
            tx.run(
                """MATCH (:GraphView {scope_key: $scope})-[m:SHOWS]->(n:GraphEntity {scope_key: $scope})
                WHERE (n.uid IN $ids OR any(id IN $ids WHERE id IN coalesce(n.legacy_ids, []))) DELETE m""",
                scope=self.scope.key,
                ids=node_ids,
            ).consume()
            tx.run(
                """MATCH ()-[r]->() WHERE r.scope_key = $scope AND (r.uid IN $ids OR any(id IN $ids WHERE id IN coalesce(r.legacy_ids, [])))
                SET r.deleted_at = $now, r.view_ids = []""",
                scope=self.scope.key,
                ids=edge_ids,
                now=datetime.now(timezone.utc).isoformat(),
            ).consume()

        self._write(sketch_id, operation)

    def delete_investigation_graph(self, sketch_id: str) -> None:
        def operation(tx: Any) -> None:
            now = datetime.now(timezone.utc).isoformat()
            tx.run(
                """MATCH (g:GraphScope {key: $scope}) SET g.deleted_at = $now""",
                scope=self.scope.key,
                now=now,
            ).consume()
            tx.run(
                """MATCH (n:GraphEntity {scope_key: $scope}) SET n.deleted_at = $now""",
                scope=self.scope.key,
                now=now,
            ).consume()
            tx.run(
                """MATCH ()-[r]->() WHERE r.scope_key = $scope SET r.deleted_at = $now, r.view_ids = []""",
                scope=self.scope.key,
                now=now,
            ).consume()
            tx.run(
                """MATCH (v:GraphView {scope_key: $scope}) SET v.deleted_at = $now
                WITH v OPTIONAL MATCH (v)-[m:SHOWS]->() DELETE m""",
                scope=self.scope.key,
                now=now,
            ).consume()

        self._write(
            sketch_id, operation, allow_deleted_scope=True, allow_deleted_view=True
        )

    def update_nodes_positions(self, positions: list[GraphDict], sketch_id: str) -> int:
        def operation(tx: Any) -> int:
            row = tx.run(
                """UNWIND $positions AS pos
                MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(n:GraphEntity)
                WHERE (n.uid = pos.nodeId OR pos.nodeId IN coalesce(n.legacy_ids, [])) AND n.deleted_at IS NULL
                SET m.x = pos.x, m.y = pos.y RETURN count(m) AS total""",
                self._params(sketch_id, positions=positions),
            ).single()
            return row["total"] if row else 0

        return self._write(sketch_id, operation)

    def _retain_edge_data(self, tx: Any, uid: str, previous: GraphDict) -> None:
        row = tx.run(
            """MATCH ()-[r]->() WHERE r.scope_key = $scope AND r.uid = $uid
            RETURN properties(r) AS data""",
            scope=self.scope.key,
            uid=uid,
        ).single()
        current = row["data"]
        events = json.loads(previous.get("graph_history") or "[]") + json.loads(
            current.get("graph_history") or "[]"
        )
        unique_events = {json.dumps(e, sort_keys=True): e for e in events}
        tx.run(
            """MATCH ()-[r]->() WHERE r.scope_key = $scope AND r.uid = $uid
            SET r.graph_history = $history, r.legacy_ids = $aliases, r.migration_records = $records""",
            scope=self.scope.key,
            uid=uid,
            history=json.dumps(list(unique_events.values()), ensure_ascii=False),
            aliases=sorted(
                (
                    set(current.get("legacy_ids", []))
                    | set(previous.get("legacy_ids", []))
                    | {previous["uid"]}
                )
                - {uid}
            ),
            records=list(
                dict.fromkeys(
                    current.get("migration_records", [])
                    + previous.get("migration_records", [])
                )
            ),
        ).consume()

    def update_relationship(
        self, element_id: str, rel_obj: GraphDict, sketch_id: str
    ) -> dict[str, Any] | None:
        def operation(tx: Any) -> dict[str, Any] | None:
            row = tx.run(
                """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
                WHERE (r.uid = $id OR $id IN coalesce(r.legacy_ids, [])) AND r.scope_key = $scope AND r.deleted_at IS NULL AND $sketch IN r.view_ids
                RETURN a.uid AS source, b.uid AS target, type(r) AS type, properties(r) AS data""",
                self._params(sketch_id, id=element_id),
            ).single()
            if not row:
                return None
            props = {
                k: v
                for k, v in rel_obj.items()
                if k not in RESERVED | {"label", "graph_edge_key"}
            }
            merged = merge_properties(row["data"], props, source=f"sketch:{sketch_id}")
            # Types are immutable in Neo4j; replacing the relationship inside
            # this transaction keeps its UUID unless another canonical edge wins.
            tx.run(
                """MATCH ()-[r]->() WHERE r.uid = $uid AND r.scope_key = $scope DELETE r""",
                uid=row["data"]["uid"],
                scope=self.scope.key,
            ).consume()
            result = self._edge(
                tx,
                row["source"],
                row["target"],
                rel_obj.get("label") or row["type"],
                merged,
                row["data"]["view_ids"],
                discriminator=str(merged.get("event_key", "")),
                preferred_uid=row["data"]["uid"],
            )
            self._retain_edge_data(tx, result["id"], merged)
            return result

        return self._write(sketch_id, operation)

    def _coalesce(self, tx: Any, target_id: str, old_id: str, sketch_id: str) -> None:
        """Transfer all appearances and typed edges without losing observations."""
        target = self._find(tx, target_id, include_deleted=True)
        old = self._find(tx, old_id, include_deleted=True)
        if not target or not old or target_id == old_id:
            return
        if target["nodeType"] != old["nodeType"]:
            raise IdentityConflict("Cannot merge different entity types")
        keys = sorted(
            set(target.get("identity_keys", []) + old.get("identity_keys", []))
        )
        check_identity_compatibility(keys)
        data = merge_properties(target, old, source=f"merge:{old_id}")
        # Both entities' histories are retained; one does not replace the other.
        data["graph_history"] = json.dumps(
            json.loads(old.get("graph_history") or "[]")
            + json.loads(data.get("graph_history") or "[]"),
            ensure_ascii=False,
        )
        data.update(
            {
                "uid": target_id,
                "identity_keys": keys,
                "migration_records": target.get("migration_records", [])
                + old.get("migration_records", []),
                "legacy_ids": sorted(
                    set(
                        target.get("legacy_ids", [])
                        + old.get("legacy_ids", [])
                        + [old_id]
                    )
                ),
            }
        )
        tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope, uid: $uid}) SET n += $props""",
            scope=self.scope.key,
            uid=target_id,
            props=data,
        ).consume()
        views = tx.run(
            """MATCH (v:GraphView {scope_key: $scope})-[m:SHOWS]->(:GraphEntity {scope_key: $scope, uid: $old})
            RETURN v.sketch_id AS sketch, properties(m) AS presentation""",
            scope=self.scope.key,
            old=old_id,
        ).data()
        for view in views:
            self._show(tx, view["sketch"], target_id, view["presentation"])
        edges = tx.run(
            """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
            WHERE r.scope_key = $scope AND (a.uid = $old OR b.uid = $old)
            RETURN a.uid AS source, b.uid AS target, type(r) AS type, properties(r) AS data""",
            scope=self.scope.key,
            old=old_id,
        ).data()
        tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope, uid: $old})-[r]-(:GraphEntity {scope_key: $scope})
            WHERE r.scope_key = $scope WITH DISTINCT r DELETE r""",
            scope=self.scope.key,
            old=old_id,
        ).consume()
        for edge in edges:
            transferred = self._edge(
                tx,
                target_id if edge["source"] == old_id else edge["source"],
                target_id if edge["target"] == old_id else edge["target"],
                edge["type"],
                edge["data"],
                edge["data"].get("view_ids", []),
                discriminator=str(edge["data"].get("event_key", "")),
                deleted_at=edge["data"].get("deleted_at"),
                preferred_uid=edge["data"]["uid"],
            )
            self._retain_edge_data(tx, transferred["id"], edge["data"])
        tx.run(
            """MATCH (n:GraphEntity {scope_key: $scope, uid: $old}) DETACH DELETE n""",
            scope=self.scope.key,
            old=old_id,
        ).consume()

    def merge_nodes(
        self,
        old_node_ids: list[str],
        new_node_data: GraphDict,
        new_node_id: str | None,
        sketch_id: str,
    ) -> str | None:
        def operation(tx: Any) -> str | None:
            nodes: list[GraphDict] = []
            for uid in old_node_ids:
                node = self._find(tx, uid, sketch_id=sketch_id)
                if node is None:
                    raise ValueError("Unknown view entity")
                nodes.append(node)
            if not nodes:
                raise ValueError("Unknown view entity")
            if any(n["nodeType"] == "avl4_card" for n in nodes):
                raise ValueError("AVL4 snapshots cannot be merged manually")
            target = next((n for n in nodes if n["uid"] == new_node_id), nodes[0])
            for old in nodes:
                self._coalesce(tx, target["uid"], old["uid"], sketch_id)
            return self._upsert_node(
                tx, {**target, **new_node_data, "id": target["uid"]}, sketch_id
            )

        return self._write(sketch_id, operation)

    def add_to_batch(self, operation_type: str, **kwargs: Any) -> None:
        if operation_type not in {"node", "relationship"}:
            raise ValueError("Unknown graph operation")
        self._batch_operations.append((operation_type, kwargs))
        if len(self._batch_operations) >= self._batch_size:
            self.flush_batch()

    def flush_batch(self) -> None:
        # Batches retain the original ordering: relationships can follow nodes.
        operations, self._batch_operations = self._batch_operations, []
        for kind, kwargs in operations:
            if kind == "node":
                self.create_node(**kwargs)
            else:
                self.create_relationship(**kwargs)

    def clear_batch(self) -> None:
        self._batch_operations.clear()

    def set_batch_size(self, size: int) -> None:
        if size < 1:
            raise ValueError("Batch size must be positive")
        self._batch_size = size

    def batch_create_nodes(self, nodes: list[GraphDict], sketch_id: str) -> GraphDict:
        # Atomic batch: errors cannot shift the import index -> entity ID mapping.
        ids = self._write(
            sketch_id, lambda tx: [self._upsert_node(tx, n, sketch_id) for n in nodes]
        )
        return {"nodes_created": len(ids), "node_ids": ids, "errors": []}

    def batch_create_edges(self, edges: list[GraphDict], sketch_id: str) -> GraphDict:
        for edge in edges:
            self.create_relationship(edge, sketch_id)
        return {"edges_created": len(edges), "errors": []}

    def batch_create_edges_by_element_id(
        self, edges: list[GraphDict], sketch_id: str
    ) -> GraphDict:
        def operation(tx: Any) -> None:
            for edge in edges:
                a = self._find(tx, edge["from_element_id"], sketch_id=sketch_id)
                b = self._find(tx, edge["to_element_id"], sketch_id=sketch_id)
                if not a or not b:
                    raise ValueError("Unknown view relationship endpoint")
                props = edge.get("properties", {})
                self._edge(
                    tx,
                    a["uid"],
                    b["uid"],
                    edge.get("rel_label", "RELATED_TO"),
                    props,
                    [sketch_id],
                    discriminator=str(props.get("event_key", "")),
                )

        self._write(sketch_id, operation)
        return {"edges_created": len(edges), "errors": []}

    def count_nodes_by_sketch(self, sketch_id: str) -> int:
        return len(self.get_sketch_graph(sketch_id)["nodes"])

    def count_edges_by_sketch(self, sketch_id: str) -> int:
        return len(self.get_sketch_graph(sketch_id)["edges"])

    def query(
        self, cypher: str, parameters: GraphDict | None = None
    ) -> list[GraphDict]:
        raise PermissionError(
            "Raw Cypher bypasses investigation isolation; use graph operations"
        )

    def __enter__(self) -> Neo4jGraphRepository:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            self.flush_batch()
        else:
            self.clear_batch()
