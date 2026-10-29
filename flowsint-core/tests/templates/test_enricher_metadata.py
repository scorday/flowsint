"""Public declarations must not be guessed from private request configuration."""

import pytest
from pydantic import ValidationError

from flowsint_core.core.enricher_metadata import EnricherMetadata, template_metadata
from flowsint_core.templates.types import Template


@pytest.mark.parametrize(
    "content",
    [None, [], {"metadata": None}, {"metadata": {"api_key_requirement": "yes"}}],
)
def test_legacy_or_invalid_template_metadata_has_an_explicit_unknown_state(content):
    metadata = template_metadata(content, "Legacy description")
    assert metadata.description == "Legacy description"
    assert metadata.providers == ()
    assert metadata.api_key_requirement == "unknown"


def test_request_secrets_and_url_are_not_used_as_public_metadata():
    metadata = template_metadata(
        {
            "request": {
                "url": "https://private.example/?key=secret",
                "headers": {"Authorization": "secret"},
            },
            "secrets": [{"name": "NOT_NECESSARILY_AN_API_KEY", "required": True}],
        },
        None,
    )
    assert "secret" not in metadata.model_dump_json()
    assert "private.example" not in metadata.model_dump_json()
    assert metadata.api_key_requirement == "unknown"


def test_explicit_template_metadata_survives_template_validation():
    template = Template.model_validate(
        {
            "name": "declared-template",
            "category": "Ip",
            "version": 1.0,
            "input": {"type": "Ip"},
            "output": {"type": "Ip"},
            "request": {"url": "https://example.test"},
            "response": {},
            "metadata": {
                "description": "Looks up public IP information.",
                "providers": ["Example"],
                "api_key_requirement": "optional",
                "api_key_notes": "An optional account key increases the quota.",
            },
        }
    )
    assert template_metadata(template.model_dump(), None) == template.metadata
    assert template.metadata.providers == ("Example",)


def test_metadata_rejects_unknown_requirement_and_private_extra_fields():
    with pytest.raises(ValidationError):
        EnricherMetadata(description="Lookup", api_key_requirement="yes")
    with pytest.raises(ValidationError):
        EnricherMetadata(description="Lookup", api_key="private")
