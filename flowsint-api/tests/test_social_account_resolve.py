"""Profile previews authorize the sketch before accessing VK or project keys."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import types as routes
from app.main import app
from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.services import NotFoundError, PermissionDeniedError
from flowsint_enrichers.vk._client import VKError, VKStopped
from flowsint_enrichers.vk._mapping import account_from_profile


@pytest.fixture
def preview(monkeypatch):
    access = Mock()
    vault = Mock()
    resolve = AsyncMock(
        return_value=account_from_profile(
            {"id": 515596, "first_name": "Test", "is_closed": False}
        )
    )
    monkeypatch.setattr(routes, "create_enricher_service", lambda db: access)
    vault_service = Mock()
    vault_service.for_user.return_value = vault
    monkeypatch.setattr(routes, "create_vault_service", lambda db: vault_service)
    monkeypatch.setattr(routes, "resolve_vk_profile", resolve)
    user = SimpleNamespace(id=uuid4())
    request = routes.SocialAccountResolveRequest(
        sketch_id=uuid4(), profile_url=" https://vk.ru/test "
    )
    return access, vault_service, vault, resolve, user, request


def test_preview_returns_canonical_profile_without_graph_writes(preview):
    access, vault_service, vault, resolve, user, request = preview
    result = asyncio.run(routes.resolve_social_account(request, Mock(), user))
    access.get_sketch_for_launch.assert_called_once_with(
        str(request.sketch_id), user.id
    )
    vault_service.for_user.assert_called_once_with(user.id)
    resolve.assert_awaited_once_with("https://vk.ru/test", vault)
    assert result["nodeLabel"] == "id515596@vk.ru"
    assert result["id"] == "id515596@vk.ru"
    assert result["username"]["value"] == "id515596"
    assert result["vk_profile_status"] == "open"


@pytest.mark.parametrize(
    "error,code",
    [(PermissionDeniedError("Forbidden"), 403), (NotFoundError("missing"), 404)],
)
def test_preview_denies_before_vault_or_provider_access(preview, error, code):
    access, vault_service, _, resolve, user, request = preview
    access.get_sketch_for_launch.side_effect = error
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.resolve_social_account(request, Mock(), user))
    assert exc.value.status_code == code
    vault_service.for_user.assert_not_called()
    resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("sensitive"), 422),
        (InvalidEnricherParams("sensitive"), 503),
        (VKStopped("sensitive"), 503),
        (VKError("sensitive"), 502),
    ],
)
def test_preview_sanitizes_errors(preview, error, code):
    _, _, _, resolve, user, request = preview
    resolve.side_effect = error
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.resolve_social_account(request, Mock(), user))
    assert exc.value.status_code == code
    assert "sensitive" not in exc.value.detail


def test_preview_http_contract(client, preview, monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "standalone")
    _, _, _, _, user, request = preview
    app.dependency_overrides[routes.get_current_user] = lambda: user
    response = client.post(
        "/api/types/social-account/resolve", json=request.model_dump(mode="json")
    )
    assert response.status_code == 200
    assert response.json()["id"] == "id515596@vk.ru"
    assert "token" not in response.text.lower()


def test_preview_requires_authentication(client, monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "standalone")
    response = client.post(
        "/api/types/social-account/resolve",
        json={"sketch_id": str(uuid4()), "profile_url": "https://vk.ru/id515596"},
    )
    assert response.status_code == 401
