import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flowsint_core.avl4_import.contracts import CardImportCommand
from flowsint_core.avl4_import.signing import signature


def test_cards_v1_golden_wire_and_signature():
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures/avl4_card_import_v1.json").read_text()
    )
    command = CardImportCommand.model_validate(fixture["command"])
    assert command.model_dump_json() == fixture["body"]
    assert (
        signature(fixture["test_key"], fixture["body"].encode(), fixture["timestamp"])
        == fixture["signature"]
    )
    assert command.snapshot.content_hash == fixture["content_hash"]
    assert command.material_key == fixture["material_key"]
    assert command.fingerprint == fixture["fingerprint"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("monitoring_url", "javascript:alert(1)"),
        ("source_url", "https://user:password@host.test"),
    ],
)
def test_snapshot_rejects_executable_or_credentialed_links(field, value):
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures/avl4_card_import_v1.json").read_text()
    )
    fixture["command"]["snapshot"][field] = value
    with pytest.raises(ValidationError):
        CardImportCommand.model_validate(fixture["command"])
