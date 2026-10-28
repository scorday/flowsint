from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.models import Profile
from flowsint_core.core.postgre_db import get_db
from flowsint_core.core.services import (
    NotFoundError,
    PermissionDeniedError,
    create_enricher_service,
    create_type_registry_service,
    create_vault_service,
)
from flowsint_enrichers.vk._client import VKError, VKStopped
from flowsint_enrichers.vk.profile import resolve_vk_profile

router = APIRouter()


@router.get("")
async def get_types_list(
    flat: bool = False,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Get the complete types list for sketches.

    By default, types are nested under their category. Pass `flat=true`
    to get a single flat list of unique leaf types (custom types included).
    """
    service = create_type_registry_service(db)
    types: list[dict[str, Any]] = service.get_types_list(current_user.id)
    if flat:
        # A type can belong to several categories. Keep the first occurrence
        # and its metadata when building the category-free insertion palette.
        unique_types: dict[str, dict[str, Any]] = {}
        for category in types:
            for child in category["children"]:
                unique_types.setdefault(child["key"], child)
        return list(unique_types.values())
    return types


class DetectRequest(BaseModel):
    text: str


class SocialAccountResolveRequest(BaseModel):
    sketch_id: UUID
    profile_url: str = Field(min_length=1, max_length=512)


@router.post("/social-account/resolve")
async def resolve_social_account(
    body: SocialAccountResolveRequest,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
) -> dict[str, Any]:
    """Preview a VK account in an editable sketch without persisting it."""
    try:
        create_enricher_service(db).get_sketch_for_launch(
            str(body.sketch_id), current_user.id
        )
        vault = create_vault_service(db).for_user(current_user.id)
        profile = await resolve_vk_profile(body.profile_url.strip(), vault)
        return dict(profile.model_dump(mode="json", exclude_unset=True))
    except PermissionDeniedError:
        raise HTTPException(status_code=403, detail="Forbidden") from None
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Sketch not found") from None
    except InvalidEnricherParams:
        raise HTTPException(
            status_code=503, detail="VK credentials unavailable"
        ) from None
    except VKStopped:
        raise HTTPException(
            status_code=503, detail="VK temporarily unavailable"
        ) from None
    except VKError:
        raise HTTPException(
            status_code=502, detail="VK profile lookup failed"
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Expected a direct VK profile URL"
        ) from None


@router.post("/detect")
async def detect_type(
    body: DetectRequest,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
) -> dict[str, Any]:
    """Detect the type of a given text input.

    Returns the detected type and its fields with the primary field pre-filled.
    Falls back to Phrase if no type matches.
    """
    service = create_type_registry_service(db)
    result: dict[str, Any] = service.detect_type(body.text)
    return result
