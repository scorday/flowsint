"""Shared catalog policy for administration, flow materials and launch menus."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..enricher_metadata import ApiKeyRequirement, template_metadata
from ..models import EnricherTemplate, EnricherVisibility, Profile
from ..project_scope import ProjectScope
from ..repositories.enricher_template_repository import EnricherTemplateRepository
from ..repositories.enricher_visibility_repository import EnricherVisibilityRepository
from .base import BaseService
from .exceptions import NotFoundError, PermissionDeniedError

EnricherKind = Literal["builtin", "template"]


def can_manage_enrichers(actor: Profile | ProjectScope) -> bool:
    if isinstance(actor, ProjectScope):
        return actor.is_platform_admin
    admins = {
        user_id.strip()
        for user_id in os.getenv("FLOWSINT_ADMIN_USER_IDS", "").split(",")
        if user_id.strip()
    }
    return actor.is_active and str(actor.id) in admins


@dataclass(frozen=True)
class CatalogEnricher:
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


class EnricherCatalogService(BaseService):
    def __init__(self, db: Session) -> None:
        super().__init__(db)
        self._visibility = EnricherVisibilityRepository(db)
        self._templates = EnricherTemplateRepository(db)

    @staticmethod
    def _visible(key: str, overrides: dict[str, bool]) -> bool:
        # Preserve the legacy default while making it configurable in the table.
        return overrides.get(key, key != "builtin:n8n_connector")

    def visible_builtins(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        overrides = self._visibility.overrides()
        return [
            item
            for item in items
            if self._visible(f"builtin:{item['name']}", overrides)
        ]

    def visible_templates(
        self, items: list[EnricherTemplate]
    ) -> list[EnricherTemplate]:
        overrides = self._visibility.overrides()
        return [
            item for item in items if self._visible(f"template:{item.id}", overrides)
        ]

    @staticmethod
    def _require_admin(actor: Profile | ProjectScope) -> None:
        if not can_manage_enrichers(actor):
            raise PermissionDeniedError(
                "Enricher administration requires an administrator"
            )

    def list_all(
        self, actor: Profile | ProjectScope, registry: Any
    ) -> list[CatalogEnricher]:
        self._require_admin(actor)
        overrides = self._visibility.overrides()
        items = [
            CatalogEnricher(
                id=item["name"],
                kind="builtin",
                name=item["name"],
                description=item.get("description"),
                category=item["category"],
                input_type=item["inputs"]["type"],
                output_type=item["outputs"]["type"],
                is_visible=self._visible(f"builtin:{item['name']}", overrides),
                providers=item.get("providers", []),
                api_key_requirement=item.get("api_key_requirement", "unknown"),
                api_key_notes=item.get("api_key_notes"),
            )
            for item in registry.list()
        ]
        for template in self._templates.get_all():
            content = template.content if isinstance(template.content, dict) else {}
            metadata = template_metadata(content, template.description)

            def io_type(key: str) -> str:
                value = content.get(key)
                return str(value.get("type", "")) if isinstance(value, dict) else ""

            items.append(
                CatalogEnricher(
                    id=str(template.id),
                    kind="template",
                    name=template.name,
                    description=metadata.description,
                    category=template.category,
                    input_type=io_type("input"),
                    output_type=io_type("output"),
                    is_visible=self._visible(f"template:{template.id}", overrides),
                    providers=list(metadata.providers),
                    api_key_requirement=metadata.api_key_requirement,
                    api_key_notes=metadata.api_key_notes,
                )
            )
        return sorted(
            items, key=lambda item: (item.name.casefold(), item.kind, item.id)
        )

    def set_visibility(
        self,
        actor: Profile | ProjectScope,
        registry: Any,
        kind: EnricherKind,
        identifier: str,
        is_visible: bool,
    ) -> CatalogEnricher:
        self._require_admin(actor)
        if kind == "template":
            try:
                identifier = str(UUID(identifier))
            except ValueError:
                raise NotFoundError("Enricher not found") from None
        item = next(
            (
                item
                for item in self.list_all(actor, registry)
                if item.kind == kind and item.id == identifier
            ),
            None,
        )
        if item is None:
            raise NotFoundError("Enricher not found")
        key = f"{kind}:{identifier}"
        row = self._visibility.get_by_key(key)
        if row is None:
            row = self._visibility.add(
                EnricherVisibility(enricher_key=key, is_visible=is_visible)
            )
            try:
                self._db.flush()
            except IntegrityError:
                # Two administrators may create the first override concurrently.
                self._db.rollback()
                row = self._visibility.get_by_key(key)
                if row is None:
                    raise
        row.is_visible = is_visible
        row.updated_by = str(actor.id)
        self._commit()
        return replace(item, is_visible=is_visible)
