"""Cross-page selection and complete application independent of preview size."""

from uuid import uuid4

import fakeredis
import pytest

from flowsint_core.core.graph.exploration_results import ExplorationResults


@pytest.fixture
def result():
    client = fakeredis.FakeRedis(decode_responses=True)
    snapshot = ExplorationResults(str(uuid4()), client)
    # Redis lock's Lua implementation belongs to redis-py. Use the same Python
    # mutex across test calls so selection/freeze still exercise exclusion.
    from threading import Lock

    lock = Lock()
    snapshot.lock = lambda: lock
    snapshot.create(
        owner="alice",
        sketch="view",
        project="project",
        options={"mode": "neighborhood"},
    )
    snapshot.state("running")
    nodes = [
        {"id": f"n{i:05}", "nodeLabel": f"Person {i}", "nodeType": "individual"}
        for i in range(12051)
    ]
    edges = [
        {"id": f"e{i:05}", "source": nodes[0]["id"], "target": node["id"]}
        for i, node in enumerate(nodes[1:])
    ]
    for offset in range(0, len(nodes), 500):
        snapshot.append("nodes", nodes[offset : offset + 500])
        snapshot.append("edges", edges[offset : offset + 500])
    snapshot.state("completed")
    return snapshot


def test_large_result_and_cross_page_selection(result):
    assert result.summary()["totals"] == {"nodes": 12051, "edges": 12050, "paths": 0}
    page = result.page("nodes", 240, 50)
    assert len(page["items"]) == 50
    assert page["items"][0]["id"] == "n12000"
    result.select("nodes", False, ["n12000"], revision=0)
    assert not result.page("nodes", 240, 50)["items"][0]["selected"]
    assert result.page("nodes", 0, 50)["items"][0]["selected"]
    assert result.summary()["selected"]["edges"] == 12049
    assert not result.page("edges", 239, 50)["items"][-1]["selected"]
    result.freeze(1)
    result.prepare_apply()
    batches = list(result.apply_batches())
    assert max(len(rows) for _, rows in batches) <= 500
    nodes = {row["id"] for kind, rows in batches if kind == "nodes" for row in rows}
    edges = {row["id"] for kind, rows in batches if kind == "edges" for row in rows}
    assert len(nodes) == 12050 and "n12000" not in nodes
    assert len(edges) == 12049 and "e11999" not in edges


def test_groups_do_not_only_select_loaded_page(result):
    result.select("all", False, None, 0)
    assert all(count == 0 for count in result.summary()["selected"].values())
    result.select("nodes", True, ["n00001", "n12000"], 1)
    assert result.summary()["selected"]["nodes"] == 2
    result.select("all", True, None, 2)
    assert result.summary()["selected"]["nodes"] == 12051
    assert result.summary()["selected"]["edges"] == 12050
    result.select("nodes", False, None, 3)
    result.select("edges", True, ["e11999"], 4)
    assert result.summary()["selected"] == {"nodes": 2, "edges": 1, "paths": 0}


def test_ownership_revision_and_expiry_fail_closed(result):
    with pytest.raises(ValueError, match="not found"):
        result.authorize("bob", "view", "project")
    with pytest.raises(ValueError, match="not found"):
        result.authorize("alice", "view", "other-project")
    result.select("nodes", False, ["n00001"], 0)
    with pytest.raises(ValueError, match="changed"):
        result.freeze(0)
    with pytest.raises(ValueError, match="belong"):
        result.select("nodes", True, ["foreign-id"], 1)
    result.freeze(1)
    with pytest.raises(ValueError, match="changed"):
        result.select("all", False, None, 1)
    assert result.redis.ttl(result.key("nodes:data")) > 0
    result.redis.delete(result.key("meta"))
    with pytest.raises(ValueError, match="expired"):
        result.summary()


def test_paths_apply_union_of_all_selected_pages(result):
    result.redis.hset(result.key("meta"), "options", '{"mode":"path"}')
    result.state("running")
    result.append(
        "paths",
        [
            {
                "id": f"path{i}",
                "node_ids": ["n00000", f"n{i + 1:05}"],
                "edge_ids": [f"e{i:05}"],
            }
            for i in range(151)
        ],
    )
    # Repeated rows must not change page order, selection or totals.
    result.append("nodes", [{"id": "n00000"}, {"id": "extra"}, {"id": "n00000"}])
    result.append("nodes", [{"id": "last"}])
    assert [r["id"] for r in result.page("nodes", 241, 50)["items"]][-2:] == [
        "extra",
        "last",
    ]
    result.redis.hdel(result.key("meta"), "total_nodes")
    result.state("completed")
    result.select("paths", False, ["path150"], 0)
    result.freeze(1)
    result.prepare_apply()
    rows = list(result.apply_batches())
    assert sum(len(batch) for kind, batch in rows if kind == "nodes") == 151
    assert sum(len(batch) for kind, batch in rows if kind == "edges") == 150


def test_evicted_snapshot_cannot_be_applied_as_a_partial_success(result):
    result.redis.delete(result.key("edges:data"))
    with pytest.raises(ValueError, match="lost data"):
        result.freeze(0)


def test_evicted_apply_index_cannot_silently_create_an_empty_view(result):
    result.freeze(0)
    result.prepare_apply()
    result.redis.delete(result.key("nodes:apply"))
    with pytest.raises(ValueError, match="lost data"):
        list(result.apply_batches())


def test_cancelled_or_failed_snapshots_release_large_rows_immediately(result):
    result.state("cancelled")
    assert result.summary()["status"] == "cancelled"
    assert result.summary()["totals"] == {"nodes": 0, "edges": 0, "paths": 0}
    assert not result.redis.exists(result.key("nodes:data"))
    with pytest.raises(ValueError, match="changed"):
        result.freeze(0)
