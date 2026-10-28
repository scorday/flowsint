from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_enrichers.vk._base import VKEnricher
from flowsint_enrichers.vk._client import VKClient, VKError, VKStopped, vk_http_client
from flowsint_enrichers.vk._mapping import account_from_profile, profile_identifier
from flowsint_types import SocialAccount, Website


@flowsint_enricher
class WebsiteToVKProfileEnricher(VKEnricher):
    """[VK] Retrieve a VK profile and its explicitly reported privacy state."""

    metadata = EnricherMetadata(
        description="Retrieves a VK user profile from a vk.ru or vk.com URL and creates a SocialAccount with the numeric VK ID, available name, avatar, location and privacy state. Missing privacy information remains unknown; closed and deactivated profiles are reported explicitly.",
        providers=("VK",),
        api_key_requirement="conditional",
        api_key_notes="Requires a VK service token in Vault (VK_SERVICE_TOKEN) or the server environment. Privacy restrictions still apply. The token is sent only to api.vk.ru.",
    )
    InputType = Website
    OutputType = SocialAccount

    @classmethod
    def name(cls) -> str:
        return "website_to_vk_profile"

    @classmethod
    def category(cls) -> str:
        return "Website"

    @classmethod
    def key(cls) -> str:
        return "url"

    async def scan(self, data: list[Website]) -> list[SocialAccount]:
        self._matches: list[tuple[Website, SocialAccount]] = []
        results = {}
        async with vk_http_client() as http:
            client = VKClient(http, self.token())
            for original in data:
                try:
                    result = account_from_profile(
                        await client.profile(profile_identifier(original))
                    )
                    results[result.id] = result
                    self._matches.append((original, result))
                except VKStopped as exc:
                    self.error(str(exc))
                    break
                except VKError as exc:
                    self.error(str(exc))
        return list(results.values())

    def postprocess(
        self, results: list[SocialAccount], input_data: list[Website] | None = None
    ) -> list[SocialAccount]:
        self.store_profiles(results)
        for original, account in getattr(self, "_matches", []):
            self.create_node(original)
            self.create_relationship(original, account, "HAS_SOCIAL_ACCOUNT")
        return results


InputType = WebsiteToVKProfileEnricher.InputType
OutputType = WebsiteToVKProfileEnricher.OutputType
