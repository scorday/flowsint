"""Bounded, read-only exploration of an investigation's canonical graph."""

from __future__ import annotations

from collections import deque
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
    NODE_LIMIT = 200
    EDGE_LIMIT = 500
    SCAN_LIMIT = 5000
    PATH_LIMIT = 20
    PATH_STATE_LIMIT = 10000

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

    def explore(self, options: ExplorationOptions, sketch_id: str) -> GraphDict:
        endpoints = [options.root_id] + (
            [options.target_id] if options.mode == "path" and options.target_id else []
        )
        known = self.search("", endpoints, sketch_id)["nodes"]
        if {n["id"] for n in known} != set(endpoints):
            raise ValueError("Object not found in this investigation")
        distances = {options.root_id: 0}
        frontier = [options.root_id]
        edges: dict[str, GraphDict] = {}
        scanned = 0
        truncated = False
        node_budget = 2000 if options.mode == "path" else self.NODE_LIMIT
        for step in range(1, options.depth + 1):
            if not frontier:
                break
            remaining = self.SCAN_LIMIT - scanned
            rows = self.connection.query(
                """MATCH (a:GraphEntity {scope_key: $scope})-[r]-(b:GraphEntity {scope_key: $scope})
                WHERE a.uid IN $frontier AND a.deleted_at IS NULL AND b.deleted_at IS NULL
                    AND r.scope_key = $scope AND r.deleted_at IS NULL
                    AND (NOT $directed OR startNode(r) = a)
                    AND (size($node_types) = 0 OR b.nodeType IN $node_types OR b.uid IN $endpoints)
                    AND (size($edge_types) = 0 OR type(r) IN $edge_types)
                RETURN a.uid AS origin, b.uid AS neighbor, r.uid AS id, type(r) AS type,
                    startNode(r).uid AS source, endNode(r).uid AS target, properties(r) AS data
                ORDER BY r.uid, a.uid LIMIT $limit""",
                {
                    "scope": self.scope.key,
                    "frontier": frontier,
                    "directed": options.directed,
                    "node_types": options.node_types,
                    "edge_types": options.edge_types,
                    "endpoints": endpoints,
                    "limit": remaining + 1,
                },
            )
            if len(rows) > remaining:
                truncated = True
            frontier = []
            for row in rows[:remaining]:
                neighbor = row["neighbor"]
                if neighbor not in distances:
                    if len(distances) >= node_budget:
                        truncated = True
                        continue
                    distances[neighbor] = step
                    frontier.append(neighbor)
                edges[row["id"]] = row
            scanned += min(len(rows), remaining)
            if scanned >= self.SCAN_LIMIT:
                truncated = True
                break

        paths: list[GraphDict] = []
        if options.mode == "path":
            adjacency: dict[str, list[tuple[str, str]]] = {}
            for edge in edges.values():
                adjacency.setdefault(edge["source"], []).append(
                    (edge["target"], edge["id"])
                )
                if not options.directed:
                    adjacency.setdefault(edge["target"], []).append(
                        (edge["source"], edge["id"])
                    )
            queue: deque[tuple[list[str], list[str]]] = deque([([options.root_id], [])])
            states = 0
            while queue:
                path_nodes, links = queue.popleft()
                states += 1
                if path_nodes[-1] == options.target_id:
                    if len(paths) == self.PATH_LIMIT:
                        truncated = True
                        break
                    paths.append({"node_ids": path_nodes, "edge_ids": links})
                    continue
                if states >= self.PATH_STATE_LIMIT:
                    truncated = True
                    break
                if len(links) >= options.depth:
                    continue
                for neighbor, edge_id in adjacency.get(path_nodes[-1], []):
                    if neighbor not in path_nodes:
                        if states + len(queue) >= self.PATH_STATE_LIMIT:
                            truncated = True
                            break
                        queue.append(([*path_nodes, neighbor], [*links, edge_id]))
            node_ids = {uid for path in paths for uid in path["node_ids"]}
            edge_ids = {uid for path in paths for uid in path["edge_ids"]}
            edges = {uid: edge for uid, edge in edges.items() if uid in edge_ids}
        else:
            node_ids = set(distances)
            # Include relations between boundary nodes, not only discovery edges.
            rows = self.connection.query(
                """MATCH (a:GraphEntity {scope_key: $scope})-[r]->(b:GraphEntity {scope_key: $scope})
                WHERE a.uid IN $ids AND b.uid IN $ids AND a.deleted_at IS NULL AND b.deleted_at IS NULL
                    AND r.scope_key = $scope AND r.deleted_at IS NULL
                    AND (size($edge_types) = 0 OR type(r) IN $edge_types)
                RETURN r.uid AS id, type(r) AS type, a.uid AS source, b.uid AS target, properties(r) AS data
                ORDER BY r.uid LIMIT $limit""",
                {
                    "scope": self.scope.key,
                    "ids": sorted(node_ids),
                    "edge_types": options.edge_types,
                    "limit": self.EDGE_LIMIT + 1,
                },
            )
            truncated |= len(rows) > self.EDGE_LIMIT
            edges = {row["id"]: row for row in rows[: self.EDGE_LIMIT]}
        nodes = self.connection.query(
            """MATCH (n:GraphEntity {scope_key: $scope}) WHERE n.uid IN $ids AND n.deleted_at IS NULL
            OPTIONAL MATCH (:GraphView {scope_key: $scope, sketch_id: $sketch})-[m:SHOWS]->(n)
            RETURN n.uid AS id, labels(n) AS labels, properties(n) AS data,
                m IS NOT NULL AS on_sketch ORDER BY n.nodeLabel, n.uid""",
            {"scope": self.scope.key, "sketch": sketch_id, "ids": sorted(node_ids)},
        )
        live_ids = {node["id"] for node in nodes}
        if live_ids != node_ids:
            # Concurrent deletion: never present a stale path as a complete result.
            truncated = True
            paths = [p for p in paths if set(p["node_ids"]) <= live_ids]
        edges = {
            uid: e
            for uid, e in edges.items()
            if e["source"] in live_ids and e["target"] in live_ids
        }
        return {
            "nodes": nodes,
            "edges": list(edges.values()),
            "paths": paths,
            "distances": {
                uid: distance for uid, distance in distances.items() if uid in live_ids
            },
            "on_sketch": [n["id"] for n in nodes if n["on_sketch"]],
            "edge_views": {
                uid: [
                    view
                    for view in e["data"].get("view_ids", [])
                    if view in self.scope.sketch_ids
                ]
                for uid, e in edges.items()
            },
            "truncated": truncated,
            "depth": options.depth,
            "scanned": scanned,
            "limits": {
                "nodes": self.NODE_LIMIT,
                "edges": self.EDGE_LIMIT,
                "paths": self.PATH_LIMIT,
                "scanned": self.SCAN_LIMIT,
            },
        }
