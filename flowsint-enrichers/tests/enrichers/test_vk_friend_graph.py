from collections import Counter
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs

import httpx
import pytest

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_enrichers import ENRICHER_REGISTRY
from flowsint_enrichers.socialaccount import to_vk_friend_graph as module
from flowsint_enrichers.vk import _base, _client
from flowsint_enrichers.vk._client import VKClient
from flowsint_types import SocialAccount


def account(user_id=1, **values):
    return SocialAccount(username=f"id{user_id}", platform="vk.ru", **values)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("VK_SERVICE_TOKEN", "graph-test-token")
    monkeypatch.setattr(_base, "Logger", MagicMock())
    monkeypatch.setattr(VKClient, "_pace", AsyncMock())
    _client._gates.clear()
    requests = []
    original_client = httpx.AsyncClient

    def install(lists, overrides=None):
        requests.clear()

        def handler(request):
            method = request.url.path.rsplit("/", 1)[-1]
            params = parse_qs(request.content.decode())
            requests.append((method, params))
            if overrides:
                result = overrides(method, params)
                if result is not None:
                    return result
            if method == "users.get":
                payload = [
                    {
                        "id": int(params["user_ids"][0]),
                        "is_closed": False,
                        "first_name": "Example",
                    }
                ]
            else:
                user_id = int(params["user_id"][0])
                offset, count = int(params["offset"][0]), int(params["count"][0])
                friends = lists.get(user_id, [])
                payload = {
                    "count": len(friends),
                    "items": friends[offset : offset + count],
                }
            return httpx.Response(200, json={"response": payload})

        monkeypatch.setattr(
            module,
            "vk_http_client",
            lambda: original_client(transport=httpx.MockTransport(handler)),
        )
        return requests

    yield install
    _client._gates.clear()


async def run(roots=None, **params):
    graph = MagicMock()
    job = module.SocialAccountToVKFriendGraphEnricher(
        sketch_id="test", graph_service=graph, params=params
    )
    await job.async_init()
    results = await job.scan(roots or [account()])
    job.postprocess(results)
    return job, results, graph


def nodes(results):
    return {item.vk_user_id: item for item in results if hasattr(item, "vk_user_id")}


def queried(requests):
    return [int(p["user_id"][0]) for name, p in requests if name == "friends.get"]


def links(graph):
    return {
        (c.kwargs["from_obj"].vk_user_id, c.kwargs["to_obj"].vk_user_id)
        for c in graph.create_relationship.call_args_list
    }


def error(code):
    return httpx.Response(
        200,
        json={"error": {"error_code": code, "error_msg": "sensitive provider message"}},
    )


def test_discovery_and_limits():
    info = next(
        item
        for item in ENRICHER_REGISTRY.list_by_input_type("SocialAccount")
        if item["name"] == "socialaccount_to_vk_friend_graph"
    )
    assert info["outputs"]["type"] == "SocialAccount"
    assert info["providers"] == ["VK"]
    params = {p["name"]: p for p in info["params_schema"]}
    assert params["VK_SERVICE_TOKEN"]["type"] == "vaultSecret"
    assert params["max_requests"]["default"] == "1000"
    assert "graph-test-token" not in str(info)


@pytest.mark.asyncio
async def test_two_hops_preserves_shared_nodes_input_identity_and_pairs(api):
    requests = api({1: [2, 3], 2: [1, 3, 4], 3: [1, 2, 4, 5], 4: [99], 5: [99]})
    original = account(nodeLabel="My existing account", bio="User annotation")
    _, results, graph = await run([original])
    result = nodes(results)
    assert set(result) == {1, 2, 3, 4, 5}
    assert queried(requests) == [1, 2, 3]
    assert len([r for r in requests if r[0] == "users.get"]) == 1
    assert links(graph) == {(1, 2), (1, 3), (2, 3), (2, 4), (3, 4), (3, 5)}
    assert graph.create_relationship.call_count == 6
    assert graph.create_node_from_flowsint_type.call_count == 5
    assert result[1].nodeLabel == original.nodeLabel
    assert original.bio == "User annotation" and not hasattr(
        original, "vk_graph_status"
    )
    assert result[1].vk_graph_complete
    assert result[1].vk_graph_depth == 2
    assert result[1].vk_graph_nodes_collected_count == 5
    assert result[1].vk_graph_edges_collected_count == 6
    assert not hasattr(result[4], "vk_friends_complete")


@pytest.mark.asyncio
async def test_overlapping_roots_expand_each_account_once(api):
    requests = api({1: [2, 3], 2: [1, 3], 3: [1, 2, 4]})
    _, results, graph = await run(
        [account(1), account(2, nodeLabel="Second original", extra_note="preserve")]
    )
    result = nodes(results)
    assert Counter(queried(requests)) == {1: 1, 2: 1, 3: 1}
    assert result[2].nodeLabel == "Second original"
    assert result[2].extra_note == "preserve"
    assert result[2].vk_friends_status == "complete"
    assert links(graph) == {(1, 2), (1, 3), (2, 3), (3, 4)}
    assert all(result[uid].vk_graph_scope == "batch" for uid in (1, 2))
    assert all(result[uid].vk_graph_nodes_collected_count == 4 for uid in (1, 2))


@pytest.mark.asyncio
async def test_graph_can_expand_more_than_the_old_100_request_budget(api):
    requests = api({1: list(range(2, 112))})
    _, results, _ = await run()
    assert len(requests) == 112
    assert nodes(results)[1].vk_graph_requests_count == 112
    assert nodes(results)[1].vk_graph_complete


@pytest.mark.parametrize(
    "name,value",
    [
        ("max_friends", "0"),
        ("max_friends", "10001"),
        ("max_requests", "5001"),
        ("max_requests", True),
        ("max_nodes", "100001"),
        ("max_edges", "500001"),
        ("max_seconds", "1801"),
        ("max_seconds", "-1"),
        ("max_nodes", " 2"),
        ("max_edges", "２"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_limits_never_call_vk(api, name, value):
    requests = api({})
    with pytest.raises(InvalidEnricherParams):
        await run(**{name: value})
    assert not requests


@pytest.mark.parametrize(
    "params,reason,expected_nodes,expected_edges",
    [
        ({"max_requests": "2"}, "request_limit", 3, 2),
        ({"max_nodes": "2"}, "node_limit", 2, 1),
        ({"max_edges": "1"}, "edge_limit", 2, 1),
    ],
)
@pytest.mark.asyncio
async def test_global_limits_preserve_partial_graph(
    api, params, reason, expected_nodes, expected_edges
):
    requests = api({1: [2, 3], 2: [4], 3: [5]})
    _, results, graph = await run(**params)
    root = nodes(results)[1]
    assert root.vk_graph_status == "truncated"
    assert root.vk_graph_stop_reason == reason
    assert not root.vk_graph_complete
    assert root.vk_graph_nodes_collected_count == expected_nodes
    assert len(results) == expected_nodes
    assert len(links(graph)) == expected_edges
    assert queried(requests) == [1]
    assert root.vk_graph_accounts_pending_count > 0


@pytest.mark.asyncio
async def test_time_budget_stops_before_the_next_account(api, monkeypatch):
    clock = [0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])

    def change_clock(method, params):
        if method == "friends.get":
            clock[0] = 2

    requests = api({1: [2]}, change_clock)
    _, results, _ = await run(max_seconds="1")
    assert nodes(results)[1].vk_graph_stop_reason == "time_limit"
    assert queried(requests) == [1]


@pytest.mark.parametrize(
    "code,status,complete",
    [(30, "private", False), (113, "error", False), (6, "stopped", False)],
)
@pytest.mark.asyncio
async def test_private_errors_and_restrictions_are_distinct(
    api, code, status, complete
):
    def override(method, params):
        if method == "friends.get" and params["user_id"] == ["2"]:
            return error(code)

    requests = api({1: [2, 3], 3: [4]}, override)
    _, results, graph = await run()
    result = nodes(results)
    assert result[2].vk_friends_status == status
    assert result[1].vk_graph_complete is complete
    assert {(1, 2), (1, 3)} <= links(graph)
    if code == 6:
        assert queried(requests) == [1, 2]
        assert result[1].vk_graph_status == "stopped"
        assert result[1].vk_graph_stop_reason == "provider_restriction"
        assert result[3].vk_friends_status == "pending"
    else:
        assert queried(requests) == [1, 2, 3]
        assert (3, 4) in links(graph)
        assert result[1].vk_graph_status == "partial"
    if code == 30:
        assert result[2].is_private is True
        assert result[1].vk_graph_private_accounts_count == 1


@pytest.mark.asyncio
async def test_per_account_limit_is_not_a_complete_graph(api):
    requests = api({1: [2, 3, 4]})
    _, results, _ = await run(max_friends="2")
    root = nodes(results)[1]
    assert root.vk_friends_status == "truncated"
    assert root.vk_friends_collected_count == 2
    assert root.vk_friends_reported_count == 3
    assert root.vk_graph_status == "partial"
    assert root.vk_graph_truncated_accounts_count == 1
    assert queried(requests) == [1, 2, 3]


@pytest.mark.asyncio
async def test_duplicate_pages_are_incomplete_and_do_not_loop(api):
    def override(method, params):
        if method == "friends.get" and params["user_id"] == ["1"]:
            return httpx.Response(200, json={"response": {"count": 4, "items": [2, 2]}})

    requests = api({}, override)
    _, results, graph = await run()
    root = nodes(results)[1]
    assert root.vk_friends_status == "incomplete"
    assert not root.vk_graph_complete
    assert len(links(graph)) == 1
    assert queried(requests) == [1, 1, 2]


@pytest.mark.asyncio
async def test_failed_root_does_not_shift_relationships_to_another_root(api):
    def override(method, params):
        if method == "users.get" and params["user_ids"] == ["1"]:
            return error(113)

    api({2: [3]}, override)
    _, results, graph = await run([account(1), account(2)])
    assert links(graph) == {(2, 3)}
    failed = next(item for item in results if item.id == "id1@vk.ru")
    assert failed.vk_graph_input_status == "error"
    assert failed.vk_graph_roots_unresolved_count == 1
    assert not failed.vk_graph_complete


@pytest.mark.asyncio
async def test_empty_lists_are_complete_and_deactivated_sources_are_not(api):
    api({})
    _, results, graph = await run()
    assert nodes(results)[1].vk_graph_complete
    assert not links(graph)
    requests = api({1: [{"id": 2, "deactivated": "deleted"}]})
    _, results, _ = await run()
    assert queried(requests) == [1]
    assert nodes(results)[2].vk_friends_status == "unavailable"
    assert not nodes(results)[1].vk_graph_complete


@pytest.mark.parametrize("budget", [0, 5001, True, "1000"])
def test_client_rejects_invalid_request_budget(budget):
    with pytest.raises(ValueError):
        VKClient(MagicMock(), "test-token", max_requests=budget)


@pytest.mark.asyncio
async def test_duplicate_inputs_keep_the_expanded_snapshot(api):
    api({1: [2]})
    _, results, _ = await run([account(), account()])
    root = nodes(results)[1]
    assert root.vk_friends_status == "complete"
    assert root.vk_friends_collected_count == 1
    assert root.vk_graph_complete


@pytest.mark.asyncio
async def test_self_friend_and_changing_counts_are_incomplete(api):
    def override(method, params):
        if method == "friends.get" and params["user_id"] == ["1"]:
            if params["offset"] == ["0"]:
                value = {"count": 4, "items": [1, 2]}
            else:
                value = {"count": 3, "items": [3]}
            return httpx.Response(200, json={"response": value})

    requests = api({}, override)
    _, results, graph = await run()
    assert (1, 1) not in links(graph)
    assert nodes(results)[1].vk_friends_status == "incomplete"
    assert not nodes(results)[1].vk_graph_complete
    assert queried(requests).count(1) == 2


@pytest.mark.asyncio
async def test_changing_count_is_incomplete_even_when_unique_total_matches(api):
    def override(method, params):
        if method == "friends.get" and params["user_id"] == ["1"]:
            page = (
                {"count": 4, "items": [2, 3]}
                if params["offset"] == ["0"]
                else {"count": 3, "items": [4]}
            )
            return httpx.Response(200, json={"response": page})

    api({}, override)
    _, results, _ = await run()
    root = nodes(results)[1]
    assert root.vk_friends_collected_count == root.vk_friends_reported_count == 3
    assert root.vk_friends_status == "incomplete"
    assert not root.vk_graph_complete


@pytest.mark.asyncio
async def test_pagination_retains_completed_root_pages_when_request_budget_ends(api):
    requests = api({1: list(range(2, 5003))})
    _, results, graph = await run(max_friends="6000", max_requests="3")
    root = nodes(results)[1]
    assert root.vk_friends_status == "complete"
    assert root.vk_friends_collected_count == 5001
    assert root.vk_graph_stop_reason == "request_limit"
    assert root.vk_graph_accounts_pending_count == 5001
    assert len(links(graph)) == 5001
    pages = [params for method, params in requests if method == "friends.get"]
    assert [p["offset"] for p in pages] == [["0"], ["5000"]]
    assert [p["count"] for p in pages] == [["5000"], ["1000"]]
