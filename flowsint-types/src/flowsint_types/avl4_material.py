"""A source snapshot owned by the authenticated Cards import workflow."""

from typing import Literal, Self

from pydantic import Field, model_validator

from .flowsint_base import FlowsintType
from .registry import flowsint_type


@flowsint_type
class Avl4Material(FlowsintType):
    card_id: str = Field(json_schema_extra={"primary": True})
    card_type: Literal["shared", "project"]
    title: str
    markdown: str = ""
    source_url: str | None = None
    monitoring_url: str
    source_project_id: str | None = None
    shared_id: str | None = None
    published_at: str
    source_updated_at: str
    captured_at: str
    snapshot_hash: str

    @model_validator(mode="after")
    def display_title(self) -> Self:
        self.nodeLabel = self.title
        return self
