"""Resolve a profile for the insertion preview without creating graph nodes."""

from flowsint_core.core.vault import VaultProtocol
from flowsint_types import SocialAccount, Website

from ._base import resolve_vk_token
from ._client import VKClient, VKError, vk_http_client
from ._mapping import account_from_profile, profile_identifier


async def resolve_vk_profile(
    profile_url: str, vault: VaultProtocol | None = None
) -> SocialAccount:
    """Validate a direct VK URL and return a canonical numeric-ID account."""
    try:
        identifier = profile_identifier(Website(url=profile_url))
    except (ValueError, VKError):
        raise ValueError("Expected a direct VK profile URL") from None
    token = resolve_vk_token(vault)
    async with vk_http_client() as http:
        profile = await VKClient(http, token).profile(identifier)
    return account_from_profile(profile)
