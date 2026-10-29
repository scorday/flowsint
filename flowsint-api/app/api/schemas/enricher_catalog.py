"""Public administration DTOs; never expose template content or credentials."""

from pydantic import BaseModel, ConfigDict, StrictBool

from flowsint_core.core.enricher_metadata import ApiKeyRequirement
from flowsint_core.core.services.enricher_catalog_service import EnricherKind


class EnricherCatalogAccess(BaseModel):
    can_manage: bool


class EnricherVisibilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_visible: StrictBool


class EnricherCatalogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: EnricherKind
    name: str
    description: str | None
    category: str
    input_type: str
    output_type: str
    is_visible: bool
    providers: list[str]
    api_key_requirement: ApiKeyRequirement
    api_key_notes: str | None
