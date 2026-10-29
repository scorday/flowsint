import json

import pytest

from flowsint_core.core.graph.identity import (
    GraphScope,
    IdentityConflict,
    check_identity_compatibility,
    identity_keys,
    merge_properties,
    split_properties,
)


def account(**properties):
    return {
        "nodeType": "socialaccount",
        **{f"nodeProperties.{k}": v for k, v in properties.items()},
    }


@pytest.mark.parametrize(
    "url", ["https://vk.com/id123", "https://vk.ru/id123", "https://m.vk.com/id123/"]
)
def test_vk_hosts_share_a_numeric_identity(url):
    assert identity_keys(account(profile_url=url)) == ["socialaccount:vk:id123"]


def test_vk_resolved_profile_bridges_numeric_id_and_short_address():
    keys = identity_keys(
        account(
            platform="vk.ru",
            username="id123",
            vk_user_id=123,
            vk_screen_name="Alice",
            profile_url="https://vk.ru/alice",
        )
    )
    assert keys == ["socialaccount:vk:alice", "socialaccount:vk:id123"]
    assert identity_keys(account(profile_url="https://vk.com/alice")) == [
        "socialaccount:vk:alice"
    ]


def test_vk_alias_cannot_join_different_authoritative_ids():
    with pytest.raises(IdentityConflict):
        check_identity_compatibility(
            [
                "socialaccount:vk:alice",
                "socialaccount:vk:id123",
                "socialaccount:vk:id456",
            ]
        )


@pytest.mark.parametrize(
    "kind,props",
    [
        ("individual", {"full_name": "Same Person"}),
        ("organization", {"name": "Same Company"}),
        ("socialaccount", {"display_name": "Same Person"}),
    ],
)
def test_display_names_never_establish_identity(kind, props):
    assert (
        identity_keys(
            {
                "nodeType": kind,
                "nodeLabel": "Same",
                **{f"nodeProperties.{k}": v for k, v in props.items()},
            }
        )
        == []
    )


def test_entity_types_cannot_collide():
    assert (
        identity_keys(
            {"nodeType": "individual", "nodeProperties.full_name": "id123@vk.ru"}
        )
        == []
    )
    assert identity_keys(account(platform="vk.ru", username="id123")) == [
        "socialaccount:vk:id123"
    ]


def test_namespaced_organisation_registration_number():
    assert identity_keys(
        {"nodeType": "organization", "nodeProperties.siren": "123456789"}
    ) == ["organization:fr:siren:123456789"]


def test_domain_and_ip_normalise_but_phone_needs_country():
    assert identity_keys(
        {"nodeType": "domain", "nodeProperties.domain": "EXAMPLE.COM."}
    ) == ["domain:example.com"]
    assert identity_keys(
        {"nodeType": "ip", "nodeProperties.address": "2001:0db8::1"}
    ) == ["ip:2001:db8::1"]
    assert (
        identity_keys({"nodeType": "phone", "nodeProperties.number": "8001234567"})
        == []
    )
    assert identity_keys(
        {"nodeType": "phone", "nodeProperties.number": "+7 (800) 123-45-67"}
    ) == ["phone:+78001234567"]


def test_properties_cannot_override_graph_scope_or_membership():
    entity, view = split_properties(
        {
            "project_id": "another",
            "investigation_id": "another",
            "uid": "forged",
            "identity_keys": ["forged"],
            "view_ids": ["another"],
            "avl4_import_key": "forged",
            "x": 12,
            "nodeFlag": None,
            "nodeProperties.display_name": "Alice",
        }
    )
    assert entity == {"nodeProperties.display_name": "Alice"}
    assert view == {"x": 12, "nodeFlag": None}


def test_conflicting_observations_are_kept_and_null_does_not_erase():
    old = {"nodeProperties.bio": "first", "nodeProperties.display_name": "Alice"}
    merged = merge_properties(
        old,
        {"nodeProperties.bio": "second", "nodeProperties.display_name": None},
        source="VK",
    )
    assert merged["nodeProperties.bio"] == "second"
    assert merged["nodeProperties.display_name"] == "Alice"
    event = json.loads(merged["graph_history"])[0]
    assert (event["previous"], event["value"], event["source"]) == (
        "first",
        "second",
        "VK",
    )
    assert (
        merge_properties(merged, {"nodeProperties.bio": "second"}, source="VK")
        == merged
    )


def test_scope_key_has_no_delimiter_collisions():
    assert GraphScope("a:b", "c").key != GraphScope("a", "b:c").key


def test_account_platforms_and_distinct_registration_ids_are_not_aliases():
    with pytest.raises(IdentityConflict):
        check_identity_compatibility(
            ["socialaccount:vk:id123", "socialaccount:twitter:id123"]
        )
    with pytest.raises(IdentityConflict):
        check_identity_compatibility(
            ["organization:fr:siren:123456789", "organization:fr:siren:987654321"]
        )


def test_task_round_trip_preserves_graph_uid_separately_from_social_id():
    from flowsint_types import SocialAccount

    account = SocialAccount(username="id123", platform="vk.ru")
    account._graph_uid = "canonical-uuid"
    task_payload = account.task_dump()
    assert task_payload["id"] == "id123@vk.ru"
    assert task_payload["_graph_uid"] == "canonical-uuid"
    restored = SocialAccount.model_validate(task_payload)
    assert restored._graph_uid == "canonical-uuid"
    assert restored.id == account.id
    assert "_graph_uid" not in restored.model_dump()
