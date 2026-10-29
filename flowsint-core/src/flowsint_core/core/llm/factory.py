from typing import Optional

from .config import get_llm_settings
from .protocol import LLMProvider


def create_llm_provider(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> LLMProvider:
    settings = get_llm_settings(provider=provider, model=model, base_url=base_url)
    api_key = api_key or settings.environment_api_key()
    if not api_key:
        raise ValueError(
            f"API key not configured. Add {settings.api_key_name} to the Vault "
            "or configure it on the server."
        )

    kwargs: dict = {"api_key": api_key}
    if settings.model:
        kwargs["model"] = settings.model

    if settings.provider == "mistral":
        from .providers.mistral import MistralProvider

        return MistralProvider(**kwargs)

    from .providers.openai import OpenAIProvider

    return OpenAIProvider(**kwargs, base_url=settings.base_url)
