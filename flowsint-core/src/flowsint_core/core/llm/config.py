"""Server-side connection settings shared by chat, templates, and readiness."""

import os
from dataclasses import dataclass

ROUTERAI_BASE_URL = "https://routerai.ru/api/v1"
_KEY_NAMES = {
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "router-ai": "ROUTERAI_API_KEY",
}


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key_name: str
    model: str | None
    base_url: str | None

    def environment_api_key(self) -> str | None:
        return os.environ.get("LLM_API_KEY") or os.environ.get(self.api_key_name)


def get_llm_settings(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> LLMSettings:
    provider = (provider or os.environ.get("LLM_PROVIDER", "mistral")).strip()
    if provider not in _KEY_NAMES:
        raise ValueError("Unsupported LLM_PROVIDER. Use mistral, openai, or router-ai.")

    model = (model or os.environ.get("LLM_MODEL", "")).strip() or None
    if provider == "router-ai" and not model:
        raise ValueError("Set LLM_MODEL to a RouterAI model ID.")

    if provider == "mistral":
        base_url = None
    else:
        base_url = base_url or os.environ.get("LLM_BASE_URL")
        if not base_url:
            base_url = (
                ROUTERAI_BASE_URL
                if provider == "router-ai"
                else os.environ.get("OPENAI_BASE_URL")
            )

    return LLMSettings(
        provider=provider,
        api_key_name=os.environ.get("LLM_API_KEY_NAME", "").strip()
        or _KEY_NAMES[provider],
        model=model,
        base_url=base_url,
    )
