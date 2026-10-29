"""Complete, read-only exploration of an investigation's canonical graph."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from .connection import GraphConnectionProtocol
from .identity import GraphScope
from .types import GraphDict


@dataclass
class ExplorationOptions:
    root_id: str
    mode: str = "neighborhood"
    target_id: str | None = None
    depth: int = 2
    node_types: list[str] = field(default_factory=list)
    edge_types: list[str] = field(default_factory=list)
    directed: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"path", "neighborhood"} or not 1 <= self.depth <= 5:
            raise ValueError("Choose a mode and a depth between 1 and 5")
        if not self.root_id or (
            self.mode == "path"
            and (not self.target_id or self.root_id == self.target_id)
        ):
            raise ValueError("Choose distinct path endpoints")
        if len(self.node_types) > 50 or len(self.edge_types) > 50:
            raise ValueError("Too many type filters")


class InvestigationExplorer:
    def __init__(self, connection: GraphConnectionProtocol, scope: GraphScope) -> None:
        self.connection = connection
        self.scope = scope

    def search(self, query: str, ids: list[str], sketch_id: str) -> GraphDict:
        rows = self.connection.query(
            """MATCH (n:GraphEntity {scope_key: $scope}) WHERE n.deleted_at IS NULL
            AND (CASE WHEN size($ids) > 0 THEN n.uid IN $ids ELSE
                toLower(coalesce(n.nodeLabel, '')) CONTAINS $query END)
            OPTIONAL MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(n)
            RETURN n.uid AS id, n.nodeLabel AS nodeLabel, n.nodeType AS nodeType,
                m IS NOT NULL AS on_sketch ORDER BY n.nodeLabel, n.uid LIMIT 51""",
            {
                "scope": self.scope.key,
                "sketch": sketch_id,
                "query": query.strip().lower(),
                "ids": ids,
            },
        )
        return {"nodes": rows[:50], "has_more": len(rows) > 50}

    def catalog(self) -> GraphDict:
        nodes = self.connection.query(
            """MATCH (n:GraphEntity {scope_key: $scope}) WHERE n.deleted_at IS NULL
            RETURN DISTINCT n.nodeType AS kind ORDER BY kind LIMIT 101""",
            {"scope": self.scope.key},
        )
        edges = self.connection.query(
            """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
            WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL AND r.deleted_at IS NULL AND r.scope_key = $scope
            RETURN DISTINCT type(r) AS kind ORDER BY kind LIMIT 101""",
            {"scope": self.scope.key},
        )
        return {
            "node_types": [r["kind"] for r in nodes[:100]],
            "edge_types": [r["kind"] for r in edges[:100]],
            "truncated": len(nodes) > 100 or len(edges) > 100,
        }

    BATCH_SIZE = 500

    def revision(self) -> int:
        rows = self.connection.query(
            "MATCH (g:GraphScope {key: $scope}) RETURN coalesce(g.revision, 0) AS revision",
            {"scope": self.scope.key},
        )
        return rows[0]["revision"] if rows else 0

    def _neighbors(
        self,
        origins: list[str],
        options: ExplorationOptions,
        sketch_id: str,
        *,
        outgoing: bool = False,
    ) -> Iterator[list[GraphDict]]:
        """Keyset batches bound each query, without limiting the overall result."""
        cursor_origin, cursor_edge = "", ""
        while True:
            rows = self.connection.query(
                """MATCH (a:GraphEntity {scope_key: $scope})-[r]-(b:GraphEntity {scope_key: $scope})
                WHERE a.uid IN $origins AND a.deleted_at IS NULL AND b.deleted_at IS NULL
                  AND r.scope_key = $scope AND r.deleted_at IS NULL
                  AND (NOT $directed OR startNode(r) = a)
                  AND (size($node_types) = 0 OR b.nodeType IN $node_types OR b.uid IN $endpoints)
                  AND (size($edge_types) = 0 OR type(r) IN $edge_types)
                  AND (a.uid > $cursor_origin OR (a.uid = $cursor_origin AND r.uid > $cursor_edge))
                OPTIONAL MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(b)
                RETURN DISTINCT a.uid AS origin, b.uid AS neighbor,
                  b.nodeLabel AS nodeLabel, b.nodeType AS nodeType, m IS NOT NULL AS on_sketch,
                  r.uid AS id, type(r) AS label, startNode(r).uid AS source, endNode(r).uid AS target,
                  startNode(r).nodeLabel AS sourceLabel, endNode(r).nodeLabel AS targetLabel,
                  [v IN coalesce(r.view_ids, []) WHERE v IN $views] AS views
                ORDER BY origin, id LIMIT $batch""",
                {
                    "scope": self.scope.key,
                    "sketch": sketch_id,
                    "views": list(self.scope.sketch_ids),
                    "origins": origins,
                    "directed": outgoing or options.directed,
                    "node_types": options.node_types,
                    "edge_types": options.edge_types,
                    "endpoints": [options.root_id, options.target_id],
                    "cursor_origin": cursor_origin,
                    "cursor_edge": cursor_edge,
                    "batch": self.BATCH_SIZE,
                },
            )
            if not rows:
                return
            yield rows
            cursor_origin, cursor_edge = rows[-1]["origin"], rows[-1]["id"]

    @staticmethod
    def _node(row: GraphDict, distance: int) -> GraphDict:
        return {
            "id": row.get("neighbor", row.get("id")),
            "nodeLabel": row["nodeLabel"],
            "nodeType": row["nodeType"],
            "on_sketch": row["on_sketch"],
            "distance": distance,
        }

    @staticmethod
    def _edge(row: GraphDict) -> GraphDict:
        return {
            key: row[key]
            for key in (
                "id",
                "source",
                "target",
                "label",
                "sourceLabel",
                "targetLabel",
                "views",
            )
        }

    def iter_results(
        self, options: ExplorationOptions, sketch_id: str
    ) -> Iterator[tuple[str, list[GraphDict]]]:
        """Stream every match. The caller persists batches and checks cancellation."""
        endpoints = [options.root_id] + (
            [options.target_id] if options.mode == "path" and options.target_id else []
        )
        known = self.search("", endpoints, sketch_id)["nodes"]
        if {n["id"] for n in known} != set(endpoints):
            raise ValueError("Object not found in this investigation")
        root = next(n for n in known if n["id"] == options.root_id)
        if options.mode == "path":
            # Depth-first iteration keeps only depth <= 5 cursors in memory;
            # parallel edges are separate paths, cycles never repeat a node.
            def visit(
                ids: list[str], edges: list[GraphDict], nodes: list[GraphDict]
            ) -> Iterator[tuple[str, list[GraphDict]]]:
                for rows in self._neighbors([ids[-1]], options, sketch_id):
                    yield "checkpoint", []
                    for row in rows:
                        neighbor = row["neighbor"]
                        if neighbor in ids:
                            continue
                        next_ids = [*ids, neighbor]
                        next_edges = [*edges, self._edge(row)]
                        next_nodes = [*nodes, self._node(row, len(edges) + 1)]
                        if neighbor == options.target_id:
                            yield "nodes", next_nodes
                            yield "edges", next_edges
                            yield (
                                "paths",
                                [
                                    {
                                        "id": ":".join(e["id"] for e in next_edges),
                                        "node_ids": next_ids,
                                        "edge_ids": [e["id"] for e in next_edges],
                                        "nodes": next_nodes,
                                        "edges": next_edges,
                                    }
                                ],
                            )
                        elif len(next_edges) < options.depth:
                            yield from visit(next_ids, next_edges, next_nodes)

            yield from visit([options.root_id], [], [self._node(root, 0)])
            return
        distances = {options.root_id: 0}
        frontier = [options.root_id]
        yield "nodes", [self._node(root, 0)]
        for step in range(1, options.depth + 1):
            following = []
            for offset in range(0, len(frontier), self.BATCH_SIZE):
                for rows in self._neighbors(
                    frontier[offset : offset + self.BATCH_SIZE], options, sketch_id
                ):
                    nodes = []
                    for row in rows:
                        if row["neighbor"] not in distances:
                            distances[row["neighbor"]] = step
                            following.append(row["neighbor"])
                            nodes.append(self._node(row, step))
                    yield "nodes", nodes
            frontier = following
            if not frontier:
                break
        # Include every recorded relation between the discovered objects,
        # including relations connecting two boundary objects.
        ids = list(distances)
        for offset in range(0, len(ids), self.BATCH_SIZE):
            for rows in self._neighbors(
                ids[offset : offset + self.BATCH_SIZE],
                options,
                sketch_id,
                outgoing=True,
            ):
                yield (
                    "edges",
                    [self._edge(row) for row in rows if row["neighbor"] in distances],
                )

    def explore(self, options: ExplorationOptions, sketch_id: str) -> GraphDict:
        """Compatibility adapter. Interactive callers use persisted paged jobs."""
        revision = self.revision()
        resources: dict[str, dict[str, GraphDict]] = {
            kind: {} for kind in ("nodes", "edges", "paths")
        }
        for kind, rows in self.iter_results(options, sketch_id):
            if kind in resources:
                resources[kind].update({row["id"]: row for row in rows})
        node_ids = list(resources["nodes"])
        edge_ids = list(resources["edges"])
        nodes = self.connection.query(
            """MATCH (n:GraphEntity {scope_key: $scope}) WHERE n.uid IN $ids AND n.deleted_at IS NULL
            RETURN n.uid AS id, labels(n) AS labels, properties(n) AS data ORDER BY n.nodeLabel, n.uid""",
            {"scope": self.scope.key, "ids": node_ids},
        )
        edges = self.connection.query(
            """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
            WHERE r.scope_key = $scope AND r.uid IN $ids AND r.deleted_at IS NULL
              AND a.deleted_at IS NULL AND b.deleted_at IS NULL
            RETURN r.uid AS id, type(r) AS type, a.uid AS source, b.uid AS target, properties(r) AS data""",
            {"scope": self.scope.key, "ids": edge_ids},
        )
        if (
            self.revision() != revision
            or len(nodes) != len(node_ids)
            or len(edges) != len(edge_ids)
        ):
            raise ValueError("Investigation changed during search. Retry.")
        return {
            "nodes": nodes,
            "edges": edges,
            "paths": [
                {k: p[k] for k in ("node_ids", "edge_ids")}
                for p in resources["paths"].values()
            ],
            "distances": {uid: n["distance"] for uid, n in resources["nodes"].items()},
            "on_sketch": [
                uid for uid, n in resources["nodes"].items() if n["on_sketch"]
            ],
            "edge_views": {uid: e["views"] for uid, e in resources["edges"].items()},
            "truncated": False,
            "depth": options.depth,
            "limits": {},
        }
