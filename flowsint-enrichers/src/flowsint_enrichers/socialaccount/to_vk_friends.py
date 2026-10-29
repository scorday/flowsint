from datetime import UTC, datetime
from typing import Any

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


@flowsint_enricher
class SocialAccountToVKFriendsEnricher(VKEnricher):
    """[VK] Retrieve available friends and add observed friendship relationships."""

    metadata = EnricherMetadata(
        description="Retrieves a paginated, bounded list of available VK friends and creates SocialAccount nodes linked to the correct source account by FRIEND_OF relationships. Marks complete, truncated, private, failed and interrupted collections explicitly. Does not recursively collect friends of friends.",
        providers=("VK",),
        api_key_requirement="conditional",
        api_key_notes="Requires a VK service token in Vault (VK_SERVICE_TOKEN) or the server environment. Privacy restrictions still apply. The token is sent only to api.vk.ru.",
    )
    InputType = SocialAccount
    OutputType = SocialAccount

    @classmethod
    def name(cls) -> str:
        return "socialaccount_to_vk_friends"

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
                "required": False,
                "default": "1000",
                "description": "Maximum friends per input account (1–10000); truncated lists are marked explicitly",
            }
        ]

    async def scan(self, data: list[SocialAccount]) -> list[SocialAccount]:
        limit = self.friend_limit()
        self._sources: list[SocialAccount] = []
        self._links: list[tuple[SocialAccount, SocialAccount]] = []
        self._resolved_sources: dict[int, SocialAccount] = {}
        results = {}
        async with vk_http_client() as http:
            client = VKClient(http, self.token())
            for original in data:
                source = original.model_copy(deep=True)
                self._sources.append(source)
                source.vk_friends_complete = False
                source.vk_friends_status = "unknown"
                source.vk_friends_collected_count = 0
                source.vk_friends_reported_count = None
                source.vk_friends_retrieved_at = datetime.now(UTC).isoformat()
                seen: set[int] = set()
                stop_batch = False
                try:
                    profile = account_from_profile(
                        await client.profile(profile_identifier(original))
                    )
                    source = enrich_original(source, profile)
                    self._sources[-1] = source
                    self._resolved_sources.setdefault(profile.vk_user_id, source)
                    if profile.vk_deactivated:
                        source.vk_friends_status = "unavailable"
                    else:
                        offset = 0
                        source.vk_friends_status = "truncated"
                        while len(seen) < limit:
                            page = await client.friends_page(
                                profile.vk_user_id, offset, min(5000, limit - len(seen))
                            )
                            source.vk_friends_reported_count = page["count"]
                            fresh = 0
                            for raw in page["items"]:
                                if raw["id"] in seen:
                                    continue
                                friend = account_from_profile(raw, partial=True)
                                seen.add(raw["id"])
                                fresh += 1
                                results[friend.id] = friend
                                self._links.append((source, friend))
                            offset += len(page["items"])
                            source.vk_friends_collected_count = len(seen)
                            if offset >= page["count"]:
                                source.vk_friends_complete = len(seen) >= page["count"]
                                source.vk_friends_status = (
                                    "complete"
                                    if source.vk_friends_complete
                                    else "incomplete"
                                )
                                if not source.vk_friends_complete:
                                    self.warn(
                                        "VK pagination contained duplicate IDs; collection is incomplete"
                                    )
                                break
                            if not fresh:
                                source.vk_friends_status = "incomplete"
                                self.warn(
                                    "VK returned an incomplete or repeated friends page"
                                )
                                break
                except VKPrivateProfile as exc:
                    source.is_private = True
                    source.vk_can_access_closed = False
                    source.vk_profile_status = "closed"
                    source.vk_friends_status = "private"
                    self.warn(str(exc))
                except VKStopped as exc:
                    source.vk_friends_status = "stopped"
                    self.error(str(exc))
                    stop_batch = True
                except VKError as exc:
                    source.vk_friends_status = "error"
                    self.error(str(exc))
                if stop_batch:
                    break
        return list(results.values())

    def postprocess(
        self,
        results: list[SocialAccount],
        input_data: list[SocialAccount] | None = None,
    ) -> list[SocialAccount]:
        sources = getattr(self, "_resolved_sources", {})
        # A selected input may also appear as somebody else's friend. Reuse its
        # original graph label and rich snapshot instead of creating an alias.
        canonical = {
            friend.id: sources.get(friend.vk_user_id, friend) for friend in results
        }
        results = list({friend.id: friend for friend in canonical.values()}.values())
        self.store_profiles(getattr(self, "_sources", []))
        self.store_profiles(results)
        for source, friend in getattr(self, "_links", []):
            friend = canonical.get(friend.id, friend)
            if source.id != friend.id:
                self.create_relationship(source, friend, "FRIEND_OF")
        return results


InputType = SocialAccountToVKFriendsEnricher.InputType
OutputType = SocialAccountToVKFriendsEnricher.OutputType
