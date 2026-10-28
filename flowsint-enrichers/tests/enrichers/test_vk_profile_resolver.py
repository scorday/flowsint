import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from flowsint_enrichers.vk import profile
from flowsint_enrichers.vk._client import VKClient, VKError


def test_resolves_alias_to_numeric_account_with_project_vault(monkeypatch):
    vault = Mock()
    vault.get_secret.return_value = "project-test-token"
    original_client = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"response": [{"id": 515596, "is_closed": True}]}
        )

    monkeypatch.setattr(
        profile,
        "vk_http_client",
        lambda: original_client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(VKClient, "_pace", AsyncMock())
    account = asyncio.run(profile.resolve_vk_profile("https://vk.com/alias", vault))
    assert account.id == account.nodeLabel == "id515596@vk.ru"
    assert account.username.value == "id515596"
    assert account.vk_profile_status == "closed"
    assert len(requests) == 1
    assert requests[0].url.host == "api.vk.ru"
    assert requests[0].headers["Authorization"] == "Bearer project-test-token"
    assert b"user_ids=alias" in requests[0].content
    assert "project-test-token" not in account.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/alias",
        "https://vk.ru.evil.test/alias",
        "https://vk.ru/alias?key=secret",
        "https://vk.ru/alias/more",
        "https://vk.ru/id0",
        "not a link",
    ],
)
def test_invalid_links_do_not_access_credentials_or_network(monkeypatch, url):
    vault = Mock()
    client = Mock()
    monkeypatch.setattr(profile, "vk_http_client", client)
    with pytest.raises(ValueError, match="direct VK profile URL"):
        asyncio.run(profile.resolve_vk_profile(url, vault))
    vault.get_secret.assert_not_called()
    client.assert_not_called()


def test_failure_is_propagated_without_an_empty_success(monkeypatch):
    monkeypatch.setenv("VK_SERVICE_TOKEN", "server-test-token")
    original_client = httpx.AsyncClient

    def client():
        return original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"response": []})
            )
        )

    monkeypatch.setattr(profile, "vk_http_client", client)
    monkeypatch.setattr(VKClient, "_pace", AsyncMock())
    with pytest.raises(VKError):
        asyncio.run(profile.resolve_vk_profile("https://vk.ru/id515596"))
