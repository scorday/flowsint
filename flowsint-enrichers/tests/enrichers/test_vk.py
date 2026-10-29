import asyncio
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs

import httpx
import pytest

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_enrichers import ENRICHER_REGISTRY
from flowsint_enrichers.socialaccount.to_vk_friends import (
    SocialAccountToVKFriendsEnricher,
)
from flowsint_enrichers.socialaccount.to_vk_profile import (
    SocialAccountToVKProfileEnricher,
)
from flowsint_enrichers.vk import _base, _client
from flowsint_enrichers.vk._client import VKClient, VKError, VKStopped
from flowsint_enrichers.vk._mapping import account_from_profile, profile_identifier
from flowsint_enrichers.website.to_vk_profile import WebsiteToVKProfileEnricher
from flowsint_types import SocialAccount, Website


@pytest.fixture(autouse=True)
def vk_environment(monkeypatch):
    _client._gates.clear()
    monkeypatch.setenv("VK_SERVICE_TOKEN", "server-test-secret")
    logger = MagicMock()
    monkeypatch.setattr(_base, "Logger", logger)
    monkeypatch.setattr("flowsint_core.core.enricher_base.Logger", logger)
    yield logger
    _client._gates.clear()


@pytest.fixture
def api(monkeypatch):
    original_client = httpx.AsyncClient
    requests = []

    def install(handler):
        def dispatch(request):
            requests.append(request)
            return handler(
                request.url.path.rsplit("/", 1)[-1], parse_qs(request.content.decode())
            )

        def factory():
            return original_client(
                transport=httpx.MockTransport(dispatch), follow_redirects=False
            )

        for name in (
            "website.to_vk_profile",
            "socialaccount.to_vk_profile",
            "socialaccount.to_vk_friends",
        ):
            monkeypatch.setattr(f"flowsint_enrichers.{name}.vk_http_client", factory)
        monkeypatch.setattr(VKClient, "_pace", AsyncMock())
        return requests

    return install


def job(cls, **kwargs):
    return cls(sketch_id="sketch", graph_service=MagicMock(), **kwargs)


def profile(user_id=1, **fields):
    return {
        "id": user_id,
        "first_name": "Example",
        "last_name": "User",
        "is_closed": False,
        "can_access_closed": True,
        **fields,
    }


def account(user_id=1, **fields):
    return SocialAccount(username=f"id{user_id}", platform="vk.ru", **fields)


def response(value):
    return httpx.Response(200, json={"response": value})


def test_catalog_discovery():
    for name, input_type in [
        ("website_to_vk_profile", "Website"),
        ("socialaccount_to_vk_profile", "SocialAccount"),
        ("socialaccount_to_vk_friends", "SocialAccount"),
    ]:
        metadata = next(
            item
            for item in ENRICHER_REGISTRY.list_by_input_type(input_type)
            if item["name"] == name
        )
        assert metadata["providers"] == ["VK"]
        assert metadata["outputs"]["type"] == "SocialAccount"
        assert metadata["api_key_requirement"] == "conditional"
        token_param = next(
            param
            for param in metadata["params_schema"]
            if param["name"] == "VK_SERVICE_TOKEN"
        )
        assert token_param["type"] == "vaultSecret"
        assert not token_param[
            "required"
        ]  # A server-configured key needs no UI selection.
        assert "server-test-secret" not in str(metadata)


@pytest.mark.parametrize(
    ("closed", "status"), [(False, "open"), (True, "closed"), (None, "unknown")]
)
@pytest.mark.asyncio
async def test_website_profile_privacy_and_safe_transport(api, closed, status):
    raw = profile(
        515596,
        is_closed=closed,
        photo_200="https://example.test/avatar.png",
        screen_name="example",
        city={"title": "City"},
        country={"title": "Country"},
    )
    requests = api(lambda *_: response([raw]))
    enricher = job(WebsiteToVKProfileEnricher)
    [result] = await enricher.execute(["https://vk.ru/id515596"])
    assert result.id == "id515596@vk.ru"
    assert result.profile_url == "https://vk.ru/id515596"
    assert result.is_private is closed
    assert result.vk_profile_status == status
    assert result.location == "City, Country"
    assert result.vk_user_id == 515596
    request = requests[0]
    assert request.url.host == "api.vk.ru" and request.method == "POST"
    assert request.headers["Authorization"] == "Bearer server-test-secret"
    assert b"server-test-secret" not in request.content
    assert "server-test-secret" not in str(request.url)
    assert "server-test-secret" not in result.model_dump_json()
    relationship = enricher.graph_service.create_relationship.call_args.kwargs
    assert relationship["from_obj"].url == Website(url="https://vk.ru/id515596").url
    assert relationship["to_obj"] == result


@pytest.mark.asyncio
async def test_refresh_preserves_identity_and_annotations(api):
    api(lambda *_: response([profile(7, is_closed=True)]))
    original = SocialAccount(
        username="alias",
        platform="vk.com",
        notes="Keep",
        profile_url="https://vk.com/id7",
    )
    enricher = job(SocialAccountToVKProfileEnricher)
    [result] = await enricher.execute([original])
    assert result.id == original.id and result.nodeLabel == original.nodeLabel
    assert result.username == original.username and result.notes == "Keep"
    assert result.is_private is True and result.vk_user_id == 7
    enricher.graph_service.create_relationship.assert_not_called()


@pytest.mark.asyncio
async def test_vault_selected_key_takes_precedence(api):
    vault = MagicMock()
    vault.get_secret.return_value = "project-test-secret"
    requests = api(lambda *_: response([profile()]))
    enricher = job(
        WebsiteToVKProfileEnricher, vault=vault, params={"VK_SERVICE_TOKEN": "vault-id"}
    )
    await enricher.execute(["https://vk.ru/id1"])
    vault.get_secret.assert_called_once_with("vault-id")
    assert requests[0].headers["Authorization"] == "Bearer project-test-secret"


@pytest.mark.asyncio
async def test_missing_key_fails_before_network(api, monkeypatch):
    monkeypatch.delenv("VK_SERVICE_TOKEN")
    requests = api(lambda *_: pytest.fail("No API call expected"))
    enricher = job(WebsiteToVKProfileEnricher)
    with pytest.raises(InvalidEnricherParams, match="Configure VK_SERVICE_TOKEN"):
        await enricher.async_init()
    assert requests == []


@pytest.mark.asyncio
async def test_friends_paginate_and_preserve_exact_source_associations(api):
    def handler(method, params):
        if method == "users.get":
            return response([profile(int(params["user_ids"][0]))])
        if params["user_id"] == ["1"]:
            if params["offset"] == ["0"]:
                return response({"count": 3, "items": [profile(2), profile(3)]})
            return response({"count": 3, "items": [profile(4)]})
        return response({"count": 1, "items": [profile(9)]})

    requests = api(handler)
    enricher = job(SocialAccountToVKFriendsEnricher)
    results = await enricher.execute([account(1), account(5)])
    assert {result.vk_user_id for result in results} == {2, 3, 4, 9}
    links = {
        (call.kwargs["from_obj"].vk_user_id, call.kwargs["to_obj"].vk_user_id)
        for call in enricher.graph_service.create_relationship.call_args_list
    }
    assert links == {(1, 2), (1, 3), (1, 4), (5, 9)}
    assert all(
        call.kwargs["rel_label"] == "FRIEND_OF"
        for call in enricher.graph_service.create_relationship.call_args_list
    )
    assert len(requests) == 5
    assert all(source.vk_friends_complete for source in enricher._sources)


@pytest.mark.parametrize(
    "page", [{"count": 0, "items": []}, {"count": 1, "items": [2]}]
)
@pytest.mark.asyncio
async def test_empty_list_and_id_only_friends_are_supported(api, page):
    api(
        lambda method, _: (
            response([profile()]) if method == "users.get" else response(page)
        )
    )
    enricher = job(SocialAccountToVKFriendsEnricher)
    results = await enricher.execute([account()])
    assert enricher._sources[0].vk_friends_complete is True
    if results:
        assert results[0].is_private is None
        assert "vk_profile_status" not in results[0].model_dump(exclude_unset=True)


@pytest.mark.asyncio
async def test_private_friends_are_not_reported_as_empty_complete_list(api):
    api(
        lambda method, _: (
            response([profile(is_closed=True)])
            if method == "users.get"
            else httpx.Response(200, json={"error": {"error_code": 30}})
        )
    )
    enricher = job(SocialAccountToVKFriendsEnricher)
    assert await enricher.execute([account()]) == []
    source = enricher._sources[0]
    assert source.is_private is True
    assert source.vk_friends_status == "private"
    assert source.vk_friends_complete is False
    assert source.vk_friends_reported_count is None
    enricher.graph_service.create_relationship.assert_not_called()


@pytest.mark.asyncio
async def test_result_limit_is_marked_truncated(api):
    requests = api(
        lambda method, _: (
            response([profile()])
            if method == "users.get"
            else response({"count": 100, "items": [profile(2), profile(3)]})
        )
    )
    enricher = job(SocialAccountToVKFriendsEnricher, params={"max_friends": "2"})
    assert len(await enricher.execute([account()])) == 2
    assert len(requests) == 2
    assert enricher._sources[0].vk_friends_status == "truncated"
    assert enricher._sources[0].vk_friends_complete is False


@pytest.mark.asyncio
async def test_repeated_pages_are_not_complete(api):
    api(
        lambda method, _: (
            response([profile()])
            if method == "users.get"
            else response({"count": 4, "items": [profile(2), profile(3)]})
        )
    )
    enricher = job(SocialAccountToVKFriendsEnricher)
    assert len(await enricher.execute([account()])) == 2
    assert enricher._sources[0].vk_friends_status == "incomplete"
    assert enricher._sources[0].vk_friends_complete is False


@pytest.mark.parametrize("code", [6, 9, 14, 17, 29, 5])
@pytest.mark.asyncio
async def test_restriction_stops_batch_and_keeps_completed_pages(
    api, code, vk_environment
):
    def handler(method, params):
        if method == "users.get":
            return response([profile()])
        if params["offset"] == ["0"]:
            return response({"count": 3, "items": [profile(2)]})
        return httpx.Response(
            200,
            json={
                "error": {
                    "error_code": code,
                    "error_msg": "server-test-secret",
                    "request_params": [{"access_token": "server-test-secret"}],
                }
            },
        )

    requests = api(handler)
    enricher = job(SocialAccountToVKFriendsEnricher)
    [result] = await enricher.execute([account(1), account(9)])
    assert result.vk_user_id == 2
    assert len(requests) == 3
    assert len(enricher._sources) == 1
    assert enricher._sources[0].vk_friends_status == "stopped"
    assert not enricher._sources[0].vk_friends_complete
    assert "server-test-secret" not in str(vk_environment.mock_calls)


@pytest.mark.parametrize("value", ["0", "10001", "NaN", "1.1", "", "-1"])
@pytest.mark.asyncio
async def test_invalid_limit_fails_before_network(api, value):
    requests = api(lambda *_: pytest.fail("No API call expected"))
    enricher = job(SocialAccountToVKFriendsEnricher, params={"max_friends": value})
    assert await enricher.execute([account()]) == []
    assert requests == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/id1",
        "https://vk.ru/id1?token=x",
        "https://vk.ru/id1#token",
        "https://vk.ru/a/b",
        "https://vk.ru@evil.test/id1",
    ],
)
@pytest.mark.asyncio
async def test_invalid_url_never_sent_to_api(api, url):
    requests = api(lambda *_: pytest.fail("No API call expected"))
    assert await job(WebsiteToVKProfileEnricher).execute([url]) == []
    assert requests == []


def test_mapping_deactivated_and_unknown_flags():
    result = account_from_profile(
        {"id": 1, "is_closed": "false", "deactivated": "deleted"}
    )
    assert result.is_private is None
    assert result.vk_profile_status == "deactivated"
    assert result.vk_deactivated == "deleted"
    assert account_from_profile({"id": 1}).is_private is None
    assert (
        account_from_profile(profile(1, first_name="Changed name")).nodeLabel
        == "Changed name User (@id1)"
    )
    partial = account_from_profile({"id": 1}, partial=True).model_dump(
        exclude_unset=True
    )
    assert "bio" not in partial and "is_private" not in partial
    assert profile_identifier(Website(url="https://vk.com/vertman")) == "vertman"
    with pytest.raises(VKError):
        profile_identifier(SocialAccount(username="someone", platform="twitter.com"))


@pytest.mark.parametrize("partial", [False, True])
def test_profile_label_uses_name_without_changing_account_identity(partial):
    named = account_from_profile(profile(7), partial=partial)
    renamed = account_from_profile(profile(7, first_name="Updated"), partial=partial)
    unnamed = account_from_profile({"id": 7}, partial=partial)

    assert named.nodeLabel == "Example User (@id7)"
    assert renamed.nodeLabel == "Updated User (@id7)"
    assert unnamed.nodeLabel == "id7@vk.ru"
    assert named.id == renamed.id == unnamed.id == "id7@vk.ru"


@pytest.mark.asyncio
async def test_selected_input_also_seen_as_friend_keeps_its_label_and_rich_fields(api):
    def handler(method, params):
        if method == "users.get":
            return response(
                [profile(int(params["user_ids"][0]), status="Rich biography")]
            )
        other = 2 if params["user_id"] == ["1"] else 1
        return response({"count": 1, "items": [other]})

    api(handler)
    first = SocialAccount(
        username="alias",
        platform="vk.ru",
        profile_url="https://vk.ru/id1",
        notes="Keep",
    )
    enricher = job(SocialAccountToVKFriendsEnricher)
    results = await enricher.execute([first, account(2)])
    by_user = {result.vk_user_id: result for result in results}
    assert by_user[1].id == first.id and by_user[1].nodeLabel == first.nodeLabel
    assert by_user[1].notes == "Keep" and by_user[1].bio == "Rich biography"
    assert by_user[2].bio == "Rich biography" and by_user[2].is_private is False
    links = enricher.graph_service.create_relationship.call_args_list
    assert links[1].kwargs["to_obj"].nodeLabel == first.nodeLabel


@pytest.mark.asyncio
async def test_http_429_sets_shared_cooldown_and_does_not_retry():
    requests = []

    def dispatch(request):
        requests.append(request)
        return httpx.Response(429, text="server-test-secret")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
        first = VKClient(http, "server-test-secret")
        with pytest.raises(VKStopped, match="HTTP 429"):
            await first.profile("1")
        with pytest.raises(VKStopped, match="cooldown"):
            await VKClient(http, "server-test-secret").profile("2")
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_redirect_is_not_followed():
    requests = []

    def dispatch(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.test/collect"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(dispatch), follow_redirects=False
    ) as http:
        with pytest.raises(VKError, match="HTTP 302"):
            await VKClient(http, "server-test-secret").profile("1")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_budget_prevents_additional_calls():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("No call"))
    ) as http:
        client = VKClient(http, "server-test-secret")
        client.requests = 100
        with pytest.raises(VKStopped, match="budget"):
            await client.profile("1")


def test_pacing_survives_separate_event_loops():
    async def reserve():
        async with httpx.AsyncClient() as http:
            client = VKClient(http, "loop-test-secret")
            await client._pace()
            return client._gate

    first = asyncio.run(reserve())
    second = asyncio.run(reserve())
    assert first is second
