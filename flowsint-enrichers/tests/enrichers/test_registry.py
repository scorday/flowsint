import pytest

from flowsint_enrichers import ENRICHER_REGISTRY


def test_enricher_registry_enricher_found():
    enricher = ENRICHER_REGISTRY.get_enricher("domain_to_ip", "123", "123")
    assert enricher.name() == "domain_to_ip"


def test_enricher_registry_enricher_not_found():
    with pytest.raises(Exception) as error:
        ENRICHER_REGISTRY.get_enricher("enricher_does_not_exist", "123", "123")
        assert "not found" in str(error.value)


def test_every_builtin_has_audited_public_metadata_in_every_registry_view():
    items = ENRICHER_REGISTRY.list()
    assert len(items) == 56
    categorized = {
        item["name"]: item
        for category in ENRICHER_REGISTRY.list_by_categories().values()
        for item in category
    }
    by_input = {
        item["name"]: item for item in ENRICHER_REGISTRY.list_by_input_type("any")
    }
    fields = ("description", "providers", "api_key_requirement", "api_key_notes")
    for item in items:
        assert len(item["description"].split()) >= 15, item["name"]
        assert item["api_key_requirement"] in {
            "required",
            "optional",
            "conditional",
            "not_required",
        }
        assert all(provider.strip() for provider in item["providers"])
        for field in fields:
            assert (
                item[field]
                == categorized[item["name"]][field]
                == by_input[item["name"]][field]
            )
        secret_params = [
            param for param in item["params_schema"] if param["type"] == "vaultSecret"
        ]
        if item["api_key_requirement"] == "required":
            assert any(param.get("required") for param in secret_params), item["name"]
            assert item["providers"] and item["api_key_notes"], item["name"]
        if item["api_key_requirement"] == "not_required":
            assert not any(param.get("required") for param in secret_params), item[
                "name"
            ]


def test_conditional_and_optional_keys_are_not_mistaken_for_required_keys():
    items = {item["name"]: item for item in ENRICHER_REGISTRY.list()}
    ports = items["ip_to_ports"]
    assert ports["api_key_requirement"] == "conditional"
    assert "passive" in ports["api_key_notes"] and "Active" in ports["api_key_notes"]
    assert {
        name
        for name, item in items.items()
        if item["api_key_requirement"] == "optional"
    } == {"cidr_to_ips", "domain_to_dns", "n8n_connector"}
    assert items["domain_to_dummy"]["providers"] == []
    assert "synthetic" in items["domain_to_dummy"]["description"]
    assert items["domain_to_subdomains"]["providers"] == ["ProjectDiscovery", "crt.sh"]
    assert "search-by-username" in items["phone_to_device_hudsonrock"]["description"]
