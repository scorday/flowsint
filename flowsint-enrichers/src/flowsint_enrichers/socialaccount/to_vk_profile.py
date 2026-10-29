from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_enrichers.vk._base import VKEnricher
from flowsint_enrichers.vk._client import VKClient, VKError, VKStopped, vk_http_client
from flowsint_enrichers.vk._mapping import (
    account_from_profile,
    enrich_original,
    profile_identifier,
)
from flowsint_types import SocialAccount


@flowsint_enricher
class SocialAccountToVKProfileEnricher(VKEnricher):
    """[VK] Refresh a VK account and check whether the profile is open or closed."""

    metadata = EnricherMetadata(
        description="Refreshes an existing VK SocialAccount with available profile information and the explicit open, closed, deactivated or unknown state. Preserves the original graph identifier and user annotations; an API failure is never treated as proof of an open profile.",
        providers=("VK",),
        api_key_requirement="conditional",
        api_key_notes="Requires a VK service token in Vault (VK_SERVICE_TOKEN) or the server environment. Privacy restrictions still apply. The token is sent only to api.vk.ru.",
    )
    InputType = SocialAccount
    OutputType = SocialAccount

    @classmethod
    def name(cls) -> str:
        return "socialaccount_to_vk_profile"

    @classmethod
    def category(cls) -> str:
        return "SocialAccount"

    @classmethod
    def key(cls) -> str:
        return "id"

    async def scan(self, data: list[SocialAccount]) -> list[SocialAccount]:
        results = {}
        async with vk_http_client() as http:
            client = VKClient(http, self.token())
            for original in data:
                try:
                    profile = account_from_profile(
                        await client.profile(profile_identifier(original))
                    )
                    result = enrich_original(original, profile)
                    results[result.id] = result
                except VKStopped as exc:
                    self.error(str(exc))
                    break
                except VKError as exc:
                    self.error(str(exc))
        return list(results.values())

    def postprocess(
        self,
        results: list[SocialAccount],
        input_data: list[SocialAccount] | None = None,
    ) -> list[SocialAccount]:
        return self.store_profiles(results)


InputType = SocialAccountToVKProfileEnricher.InputType
OutputType = SocialAccountToVKProfileEnricher.OutputType
