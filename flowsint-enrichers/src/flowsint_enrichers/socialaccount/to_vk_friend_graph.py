"""Build the observed VK friendship graph within two hops of the inputs."""

import heapq
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_enrichers.vk._base import VKEnricher
from flowsint_enrichers.vk._client import (
    VKClient,
    VKError,
    VKPrivateProfile,
    VKStopped,
    vk_http_client,
)
from flowsint_enrichers.vk._mapping import (
    account_from_profile,
    enrich_original,
    profile_identifier,
)
from flowsint_types import SocialAccount


class _GraphLimit(Exception):
    pass


@flowsint_enricher
class SocialAccountToVKFriendGraphEnricher(VKEnricher):
    """[VK] Build a two-hop graph of friends and friends of friends."""

    metadata = EnricherMetadata(
        description="Builds a VK friendship graph two hops from the selected accounts: friends and friends of friends, with shared SocialAccount nodes and observed FRIEND_OF links. Expands each account once, preserves input identity, and marks partial results, private lists and request, time, node or edge limits explicitly. Does not expand the second-hop accounts further.",
        providers=("VK",),
        api_key_requirement="conditional",
        api_key_notes="Requires a VK service token in Vault (VK_SERVICE_TOKEN) or the server environment. Privacy restrictions still apply. The token is sent only to api.vk.ru.",
    )
    InputType = SocialAccount
    OutputType = SocialAccount

    @classmethod
    def name(cls) -> str:
        return "socialaccount_to_vk_friend_graph"

    @classmethod
    def category(cls) -> str:
        return "SocialAccount"

    @classmethod
    def key(cls) -> str:
        return "id"

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        return super().get_params_schema() + [
            {
                "name": "max_friends",
                "type": "string",
                "default": "1000",
                "description": "Maximum friends per expanded account (1–10000); applies to both levels",
            },
            {
                "name": "max_requests",
                "type": "string",
                "default": "1000",
                "description": "Maximum VK requests for the entire graph batch (1–5000), including profile lookups",
            },
            {
                "name": "max_nodes",
                "type": "string",
                "default": "50000",
                "description": "Maximum unique VK accounts in the graph batch (1–100000), including inputs",
            },
            {
                "name": "max_edges",
                "type": "string",
                "default": "100000",
                "description": "Maximum unique friendship pairs in the graph batch (1–500000)",
            },
            {
                "name": "max_seconds",
                "type": "string",
                "default": "600",
                "description": "Maximum collection time in seconds (1–1800); an in-flight HTTP request may take up to 20 more seconds",
            },
        ]

    def _limits(self) -> dict[str, int]:
        limits = {}
        for name, default, maximum in (
            ("max_friends", "1000", 10000),
            ("max_requests", "1000", 5000),
            ("max_nodes", "50000", 100000),
            ("max_edges", "100000", 500000),
            ("max_seconds", "600", 1800),
        ):
            raw = self.params.get(name, default)
            if (
                not isinstance(raw, str)
                or not raw.isascii()
                or not raw.isdecimal()
                or not 1 <= int(raw) <= maximum
            ):
                raise InvalidEnricherParams(
                    f"{name} must be an integer between 1 and {maximum}"
                )
            limits[name] = int(raw)
        return limits

    def _check_budget(self, client: VKClient) -> None:
        if client.requests >= self._budget["max_requests"]:
            raise _GraphLimit("request_limit")
        if monotonic() - self._started >= self._budget["max_seconds"]:
            raise _GraphLimit("time_limit")

    def _schedule(self, user_id: int, depth: int) -> None:
        if depth < 2 and user_id not in self._scheduled:
            self._scheduled.add(user_id)
            heapq.heappush(self._queue, (depth, user_id))
            source = self._nodes[user_id]
            source.vk_friends_status = "pending"
            source.vk_friends_complete = False
            source.vk_friends_collected_count = 0
            source.vk_friends_reported_count = None
            source.vk_friends_retrieved_at = None

    def _add_friend(self, source_id: int, raw: dict[str, Any], depth: int) -> None:
        user_id = raw["id"]
        pair = tuple(sorted((source_id, user_id)))
        if user_id not in self._nodes and len(self._nodes) >= self._budget["max_nodes"]:
            raise _GraphLimit("node_limit")
        if pair not in self._edges and len(self._edges) >= self._budget["max_edges"]:
            raise _GraphLimit("edge_limit")
        if user_id not in self._nodes:
            self._nodes[user_id] = account_from_profile(raw, partial=True)
        # Keep rich inputs and previously collected status when a shared friend
        # occurs in another partial friends.get page.
        self._edges.setdefault(pair, (source_id, user_id))
        self._schedule(user_id, depth + 1)

    async def _collect(self, client: VKClient, user_id: int, depth: int) -> None:
        source = self._nodes[user_id]
        source.vk_friends_retrieved_at = datetime.now(UTC).isoformat()
        if getattr(source, "vk_deactivated", None):
            source.vk_friends_status = "unavailable"
            return
        source.vk_friends_status = "truncated"
        seen: set[int] = set()
        offset = 0
        first_count = None
        changed_count = False
        try:
            while len(seen) < self._budget["max_friends"]:
                self._check_budget(client)
                page = await client.friends_page(
                    user_id, offset, min(5000, self._budget["max_friends"] - len(seen))
                )
                count = page["count"]
                if first_count is None:
                    first_count = count
                changed_count |= count != first_count
                source.vk_friends_reported_count = count
                fresh = 0
                for raw in page["items"]:
                    friend_id = raw["id"]
                    if friend_id in seen or friend_id == user_id:
                        continue
                    self._add_friend(user_id, raw, depth)
                    seen.add(friend_id)
                    fresh += 1
                    source.vk_friends_collected_count = len(seen)
                offset += len(page["items"])
                if offset >= count:
                    source.vk_friends_complete = (
                        len(seen) >= count and not changed_count
                    )
                    source.vk_friends_status = (
                        "complete" if source.vk_friends_complete else "incomplete"
                    )
                    break
                if not fresh:
                    source.vk_friends_status = "incomplete"
                    break
        except VKPrivateProfile as exc:
            source.is_private = True
            source.vk_can_access_closed = False
            source.vk_profile_status = "closed"
            source.vk_friends_status = "private"
            self.warn(str(exc))
        except VKStopped:
            source.vk_friends_status = "stopped"
            raise
        except VKError as exc:
            source.vk_friends_status = "error"
            self.error(str(exc))

    async def scan(self, data: list[SocialAccount]) -> list[SocialAccount]:
        self._budget = self._limits()
        if len(data) > self._budget["max_nodes"]:
            raise InvalidEnricherParams("Selected accounts exceed max_nodes")
        self._started = monotonic()
        self._nodes: dict[int, SocialAccount] = {}
        self._edges: dict[tuple[int, ...], tuple[int, int]] = {}
        self._queue: list[tuple[int, int]] = []
        self._scheduled: set[int] = set()
        self._attempted: set[int] = set()
        roots = [item.model_copy(deep=True) for item in data]
        root_states = ["pending"] * len(roots)
        stop_reason = None
        stop_status = None
        self.log_graph_message("VK depth-2 graph collection started")
        async with vk_http_client() as http:
            client = VKClient(
                http, self.token(), max_requests=self._budget["max_requests"]
            )
            try:
                # Resolve selected identities before partial friend records can
                # appear, so existing graph labels and annotations always win.
                for index, original in enumerate(roots):
                    self._check_budget(client)
                    try:
                        profile = account_from_profile(
                            await client.profile(profile_identifier(original))
                        )
                    except VKStopped:
                        raise
                    except VKError as exc:
                        root_states[index] = "error"
                        self.error(str(exc))
                        continue
                    source = enrich_original(original, profile)
                    roots[index] = source
                    self._nodes.setdefault(profile.vk_user_id, source)
                    root_states[index] = "resolved"
                    self._schedule(profile.vk_user_id, 0)
                while self._queue:
                    self._check_budget(client)
                    depth, user_id = heapq.heappop(self._queue)
                    self._attempted.add(user_id)
                    await self._collect(client, user_id, depth)
                    if len(self._attempted) % 10 == 0:
                        self.log_graph_message(
                            f"VK depth-2: {len(self._attempted)} accounts scanned, {len(self._nodes)} nodes, {len(self._edges)} links"
                        )
            except _GraphLimit as exc:
                stop_reason = str(exc)
                stop_status = "truncated"
                self.warn(
                    f"VK graph stopped at {stop_reason}; partial results retained"
                )
            except VKStopped as exc:
                stop_reason = "provider_restriction"
                stop_status = "stopped"
                self.error(str(exc))
        statuses = [
            getattr(self._nodes[uid], "vk_friends_status", "pending")
            for uid in self._scheduled
        ]
        complete = (
            bool(roots)
            and all(state == "resolved" for state in root_states)
            and all(status == "complete" for status in statuses)
        )
        summary = {
            "vk_graph_depth": 2,
            "vk_graph_scope": "batch",
            "vk_graph_status": stop_status or ("complete" if complete else "partial"),
            "vk_graph_complete": complete and stop_status is None,
            "vk_graph_stop_reason": stop_reason,
            "vk_graph_nodes_collected_count": len(self._nodes),
            "vk_graph_edges_collected_count": len(self._edges),
            "vk_graph_accounts_scanned_count": len(self._attempted),
            "vk_graph_accounts_pending_count": len(self._scheduled - self._attempted),
            "vk_graph_roots_unresolved_count": root_states.count("error")
            + root_states.count("pending"),
            "vk_graph_private_accounts_count": statuses.count("private"),
            "vk_graph_failed_accounts_count": statuses.count("error"),
            "vk_graph_truncated_accounts_count": statuses.count("truncated"),
            "vk_graph_requests_count": client.requests,
            "vk_graph_retrieved_at": datetime.now(UTC).isoformat(),
        }
        for root, state in zip(roots, root_states):
            for name, value in summary.items():
                setattr(root, name, value)
            root.vk_graph_input_status = state
        # Include failed input snapshots as well: their explicit graph status is
        # useful, even when no VK identity could be resolved.
        results = {item.nodeLabel or item.id: item for item in self._nodes.values()}
        for root in roots:
            results.setdefault(root.nodeLabel or root.id, root)
        self.log_graph_message(
            f"VK depth-2 graph {summary['vk_graph_status']}: {len(self._nodes)} nodes, {len(self._edges)} links, {client.requests} requests"
        )
        return list(results.values())

    def postprocess(
        self,
        results: list[SocialAccount],
        input_data: list[SocialAccount] | None = None,
    ) -> list[SocialAccount]:
        self.store_profiles(results)
        for source_id, friend_id in self._edges.values():
            self.create_relationship(
                self._nodes[source_id], self._nodes[friend_id], "FRIEND_OF"
            )
        return results


InputType = SocialAccountToVKFriendGraphEnricher.InputType
OutputType = SocialAccountToVKFriendGraphEnricher.OutputType
