"""Expiring server-side exploration snapshots and cross-page selection.

Redis holds compact preview rows, never credentials or full graph properties.
Only completed snapshots can be selected or applied. All keys share a fixed
expiry; running jobs refresh it after each bounded batch.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

from redis import Redis

KINDS = ("nodes", "edges", "paths")
TTL = 24 * 60 * 60
BATCH = 500


class ExplorationCancelled(Exception):
    pass


class ExplorationResults:
    def __init__(self, result_id: str, client: Any = None) -> None:
        self.id = str(uuid4()) if result_id == "new" else result_id
        # IDs become Redis key fragments only after UUID validation.
        UUID(self.id)
        # redis-py does not specialize its return types for decode_responses.
        self.redis: Any = (
            client
            if client is not None
            else Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        )
        self.prefix = f"flowsint:exploration:{self.id}:"

    def key(self, suffix: str) -> str:
        return self.prefix + suffix

    def touch(self) -> None:
        keys = ["meta", "sources", "targets", "nodes:apply", "edges:apply"] + [
            f"{k}:{s}" for k in KINDS for s in ("data", "order", "selected")
        ]
        if not self.redis.hexists(self.key("meta"), "options"):
            raise ValueError("Search expired. Run the search again.")
        pipe = self.redis.pipeline()
        pipe.hset(self.key("meta"), "updated_at", str(time.time()))
        for suffix in keys:
            pipe.expire(self.key(suffix), TTL)
        pipe.execute()

    def create(self, *, owner: str, sketch: str, project: str, options: dict) -> dict:
        self.redis.hset(
            self.key("meta"),
            mapping={
                "owner": owner,
                "sketch": sketch,
                "project": project,
                "options": json.dumps(options),
                "status": "queued",
                "revision": "0",
                "updated_at": str(time.time()),
            },
        )
        self.touch()
        return self.summary()

    def authorize(self, owner: str, sketch: str, project: str) -> dict:
        meta: dict = self.redis.hgetall(self.key("meta"))
        if not meta or any(
            meta.get(k) != v
            for k, v in (("owner", owner), ("sketch", sketch), ("project", project))
        ):
            raise ValueError("Search not found or expired. Run the search again.")
        return meta

    def check_running(self) -> None:
        if self.redis.hget(self.key("meta"), "status") != "running":
            raise ExplorationCancelled()

    def append(self, kind: str, rows: list[dict]) -> None:
        if not rows:
            return
        self.check_running()
        pipe = self.redis.pipeline()
        for row in rows:
            pipe.hsetnx(self.key(f"{kind}:data"), str(row["id"]), json.dumps(row))
        added = pipe.execute()
        offset = self.redis.zcard(self.key(f"{kind}:order"))
        fresh = [row for row, new in zip(rows, added) if new]
        members = {str(row["id"]): offset + i for i, row in enumerate(fresh)}
        if members:
            pipe = self.redis.pipeline()
            pipe.hincrby(self.key("meta"), f"produced_{kind}", len(members))
            pipe.zadd(self.key(f"{kind}:order"), members)
            pipe.zadd(self.key(f"{kind}:selected"), members)
            if kind == "edges":
                for side, index in (("source", "sources"), ("target", "targets")):
                    pipe.zadd(
                        self.key(index),
                        {f"{row[side]}:{row['id']}": 0 for row in fresh},
                    )
            pipe.execute()
        self.touch()

    def summary(self) -> dict:
        meta = self.redis.hgetall(self.key("meta"))
        if not meta or not all(
            key in meta for key in ("status", "revision", "options", "updated_at")
        ):
            raise ValueError("Search expired. Run the search again.")
        totals = {kind: self.redis.zcard(self.key(f"{kind}:order")) for kind in KINDS}
        selected = {
            kind: self.redis.zcard(self.key(f"{kind}:selected")) for kind in KINDS
        }
        if meta["status"] in {"completed", "applying", "applied"}:
            for kind in KINDS:
                if (
                    totals[kind] != int(meta[f"total_{kind}"])
                    or self.redis.hlen(self.key(f"{kind}:data")) != totals[kind]
                    or selected[kind] != int(meta[f"selected_{kind}"])
                ):
                    raise ValueError(
                        "Search expired or lost data. Run the search again."
                    )
            if any(
                self.redis.zcard(self.key(index)) != totals["edges"]
                for index in ("sources", "targets")
            ):
                raise ValueError("Search expired or lost data. Run the search again.")
        return {
            "id": self.id,
            "status": meta["status"],
            "revision": int(meta["revision"]),
            "totals": totals,
            "selected": selected,
            "options": json.loads(meta["options"]),
            "sketch_id": meta.get("created_sketch_id"),
            "error": meta.get("error"),
            "updated_at": float(meta["updated_at"]),
            "stalled": time.time() - float(meta["updated_at"]) > 300,
        }

    def page(self, kind: str, page: int, size: int) -> dict:
        ids = self.redis.zrange(
            self.key(f"{kind}:order"), page * size, (page + 1) * size - 1
        )
        rows = self.redis.hmget(self.key(f"{kind}:data"), ids) if ids else []
        selected = self.redis.zmscore(self.key(f"{kind}:selected"), ids) if ids else []
        return {
            "items": [
                {**json.loads(row), "selected": score is not None}
                for row, score in zip(rows, selected)
                if row
            ],
            "page": page,
            "size": size,
            **self.summary(),
        }

    def batches(
        self, kind: str, selected: bool = False, *, applying: bool = False
    ) -> Iterator[list[dict]]:
        suffix = "apply" if applying else "selected" if selected else "order"
        offset = 0
        while ids := self.redis.zrange(
            self.key(f"{kind}:{suffix}"), offset, offset + BATCH - 1
        ):
            yield [
                json.loads(row)
                for row in self.redis.hmget(self.key(f"{kind}:data"), ids)
                if row
            ]
            offset += len(ids)

    def state(self, status: str, **values: str) -> None:
        if status == "completed" and not self.redis.hexists(
            self.key("meta"), "total_nodes"
        ):
            for kind in KINDS:
                produced = int(
                    self.redis.hget(self.key("meta"), f"produced_{kind}") or 0
                )
                if produced != self.redis.zcard(self.key(f"{kind}:order")):
                    raise ValueError("Search lost data. Run the search again.")
                values[f"total_{kind}"] = str(produced)
                values[f"selected_{kind}"] = str(
                    self.redis.zcard(self.key(f"{kind}:selected"))
                )
        self.redis.hset(self.key("meta"), mapping={"status": status, **values})
        if status in {"cancelled", "failed"}:
            self.clear_rows()
        self.touch()

    def clear_rows(self) -> None:
        # UNLINK releases large snapshots without blocking the shared Redis.
        keys = ["sources", "targets", "nodes:apply", "edges:apply"] + [
            f"{kind}:{suffix}"
            for kind in KINDS
            for suffix in ("data", "order", "selected")
        ]
        self.redis.unlink(*[self.key(suffix) for suffix in keys])

    def lock(self) -> Any:
        return self.redis.lock(self.key("lock"), timeout=120, blocking_timeout=5)

    def select(
        self, kind: str, checked: bool, ids: list[str] | None, revision: int
    ) -> dict:
        if kind == "all" and ids is not None:
            raise ValueError("Whole-result operations cannot contain page IDs")
        with self.lock():
            self.summary()
            meta = self.redis.hgetall(self.key("meta"))
            if meta["status"] != "completed" or int(meta["revision"]) != revision:
                raise ValueError("Search or selection changed. Refresh the result.")
            kinds = KINDS if kind == "all" else (kind,)
            pipe = self.redis.pipeline()
            for resource in kinds:
                source, dest = (
                    self.key(f"{resource}:order"),
                    self.key(f"{resource}:selected"),
                )
                if ids is None:
                    if checked:
                        pipe.zunionstore(dest, [source])
                    else:
                        pipe.delete(dest)
                elif ids:
                    scores = self.redis.zmscore(source, ids)
                    valid = {
                        uid: score
                        for uid, score in zip(ids, scores)
                        if score is not None
                    }
                    if len(valid) != len(set(ids)):
                        raise ValueError("Object does not belong to this search")
                    if checked:
                        pipe.zadd(dest, valid)
                    else:
                        pipe.zrem(dest, *valid)
            # Removing all nodes also removes every relation; selecting relations
            # explicitly reselects their endpoints below.
            if kind == "nodes" and not checked and ids is None:
                pipe.delete(self.key("edges:selected"))
            if kind == "edges" and checked:
                if ids is None:
                    if self.redis.zcard(self.key("edges:order")):
                        pipe.zunionstore(
                            self.key("nodes:selected"), [self.key("nodes:order")]
                        )
                elif ids:
                    for row in self.redis.hmget(self.key("edges:data"), ids):
                        edge = json.loads(row)
                        for uid in (edge["source"], edge["target"]):
                            score = self.redis.zscore(self.key("nodes:order"), uid)
                            pipe.zadd(self.key("nodes:selected"), {uid: score})
            if kind == "nodes" and not checked and ids:
                for uid in ids:
                    for index in ("sources", "targets"):
                        cursor = f"[{uid}:"
                        while related := self.redis.zrangebylex(
                            self.key(index), cursor, f"[{uid}:\xff", start=0, num=BATCH
                        ):
                            pipe.zrem(
                                self.key("edges:selected"),
                                *[key[len(uid) + 1 :] for key in related],
                            )
                            cursor = "(" + related[-1]
            pipe.hincrby(self.key("meta"), "revision", 1)
            pipe.execute()
            self.redis.hset(
                self.key("meta"),
                mapping={
                    f"selected_{kind}": str(
                        self.redis.zcard(self.key(f"{kind}:selected"))
                    )
                    for kind in KINDS
                },
            )
            self.touch()
        return self.summary()

    def freeze(self, revision: int) -> None:
        with self.lock():
            self.summary()
            meta = self.redis.hgetall(self.key("meta"))
            if meta["status"] != "completed" or int(meta["revision"]) != revision:
                raise ValueError("Search or selection changed. Refresh the result.")
            selected_kind = (
                "paths" if json.loads(meta["options"])["mode"] == "path" else "nodes"
            )
            if not self.redis.zcard(self.key(f"{selected_kind}:selected")):
                raise ValueError("Select at least one result")
            self.state("applying", error="")

    def prepare_apply(self) -> None:
        self.summary()
        if json.loads(self.redis.hget(self.key("meta"), "options"))["mode"] != "path":
            for kind in ("nodes", "edges"):
                self.redis.zunionstore(
                    self.key(f"{kind}:apply"), [self.key(f"{kind}:selected")]
                )
        else:
            self.redis.delete(self.key("nodes:apply"), self.key("edges:apply"))
            processed_paths = 0
            for paths in self.batches("paths", selected=True):
                processed_paths += len(paths)
                for kind, field in (("nodes", "node_ids"), ("edges", "edge_ids")):
                    ids = {uid for path in paths for uid in path[field]}
                    if ids:
                        self.redis.zadd(
                            self.key(f"{kind}:apply"), {uid: 0 for uid in ids}
                        )
                self.touch()
            if processed_paths != self.summary()["selected"]["paths"]:
                raise ValueError("Search expired or lost data. Run the search again.")
        self.redis.hset(
            self.key("meta"),
            mapping={
                f"apply_{kind}": str(self.redis.zcard(self.key(f"{kind}:apply")))
                for kind in ("nodes", "edges")
            },
        )
        self.touch()

    def apply_batches(self) -> Iterator[tuple[str, list[dict]]]:
        # A factory is used so Neo4j can safely replay a transient transaction.
        self.summary()
        for kind in ("nodes", "edges"):
            expected = int(self.redis.hget(self.key("meta"), f"apply_{kind}"))
            if expected != self.redis.zcard(self.key(f"{kind}:apply")):
                raise ValueError("Search expired or lost data. Run the search again.")
            processed = 0
            for rows in self.batches(kind, applying=True):
                self.touch()
                processed += len(rows)
                yield kind, rows
            if processed != expected:
                raise ValueError("Search expired or lost data. Run the search again.")
