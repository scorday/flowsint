"""Public, declarative descriptions of integrations, never credential values."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ApiKeyRequirement = Literal[
    "required", "optional", "conditional", "not_required", "unknown"
]


class EnricherMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1)
    providers: tuple[str, ...] = ()
    api_key_requirement: ApiKeyRequirement = "unknown"
    api_key_notes: str | None = None


def template_metadata(content: Any, description: str | None) -> EnricherMetadata:
    """Use explicit public annotations; never infer from URLs, headers or secrets."""
    raw = content.get("metadata") if isinstance(content, dict) else None
    if isinstance(raw, dict):
        try:
            return EnricherMetadata.model_validate(raw)
        except ValidationError:
            pass
    return EnricherMetadata(
        description=description
        or "Runs a custom HTTP enricher template with its configured input and output mappings.",
        api_key_notes="Provider and API-key requirements have not been declared in this template's metadata.",
    )
