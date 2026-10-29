"""Cards → Flowsint v1 wire contract. Vendored unchanged by Flowsint."""

import hashlib
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_BODY_BYTES = 1_048_576
IMPORT_PATH = "/internal/avl4/card-imports"
Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f]+$")
]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardSnapshot(WireModel):
    card_type: Literal["shared", "project"]
    card_id: Identifier
    source_project_id: Identifier | None = None
    shared_id: Identifier | None = None
    title: str = Field(max_length=4096)
    markdown: str = Field(max_length=524288)
    source_url: str | None = Field(default=None, max_length=8192)
    monitoring_url: str = Field(min_length=1, max_length=8192)
    published_at: AwareDatetime
    source_updated_at: AwareDatetime
    captured_at: AwareDatetime

    @field_validator("source_url", "monitoring_url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(char.isspace() or char == "\\" for char in value)
        ):
            raise ValueError("Expected a public HTTP URL")
        return value

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            canonical_bytes(self.model_dump(mode="json", exclude={"captured_at"}))
        ).hexdigest()


class CardImportCommand(WireModel):
    version: Literal[1] = 1
    operation_id: UUID
    actor_id: Identifier
    private_project_id: Identifier | None = None
    project_id: Identifier
    investigation_id: UUID
    sketch_id: UUID
    snapshot: CardSnapshot
    refresh: bool = False
    expected_snapshot_hash: Digest | None = None

    @model_validator(mode="after")
    def check_context(self) -> "CardImportCommand":
        if (
            self.snapshot.card_type == "project"
            and self.snapshot.source_project_id != self.project_id
        ):
            raise ValueError("Card project mismatch")
        if (
            self.snapshot.card_type == "shared"
            and self.snapshot.source_project_id is not None
        ):
            raise ValueError("Shared cards have no source project")
        if self.refresh != (self.expected_snapshot_hash is not None):
            raise ValueError("Refresh requires an expected snapshot hash")
        return self

    @property
    def fingerprint(self) -> str:
        # Retries re-read Cards. The first persisted snapshot wins for this operation.
        intent = self.model_dump(mode="json", exclude={"snapshot"})
        intent["card_type"] = self.snapshot.card_type
        intent["card_id"] = self.snapshot.card_id
        return hashlib.sha256(canonical_bytes(intent)).hexdigest()

    @property
    def material_key(self) -> str:
        return hashlib.sha256(
            canonical_bytes(
                [
                    self.project_id,
                    str(self.sketch_id),
                    self.snapshot.card_type,
                    self.snapshot.card_id,
                ]
            )
        ).hexdigest()


class CardImportResult(WireModel):
    version: Literal[1] = 1
    operation_id: UUID
    material_id: UUID
    project_id: Identifier
    investigation_id: UUID
    sketch_id: UUID
    node_id: str = Field(min_length=1, max_length=512)
    snapshot_hash: Digest
    action: Literal["created", "existing", "updated"]
    url: str = Field(min_length=1, max_length=8192)

    @field_validator("url")
    @classmethod
    def safe_result_url(cls, value: str) -> str:
        CardSnapshot.safe_url(value)
        return value
