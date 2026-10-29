"""Types shared by categories must appear once in the insertion palette."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.api.routes import types as routes
from flowsint_core.core.services.type_registry_service import TypeRegistryService


def test_flat_catalog_deduplicates_real_types_but_keeps_categories(monkeypatch):
    repository = Mock()
    repository.get_by_owner.return_value = []
    service = TypeRegistryService(db=Mock(), custom_type_repo=repository)
    monkeypatch.setattr(routes, "create_type_registry_service", lambda db: service)
    user = SimpleNamespace(id=uuid4())

    nested = asyncio.run(routes.get_types_list(False, Mock(), user))
    children = [child for category in nested for child in category["children"]]
    assert sum(child["key"] == "username" for child in children) == 2
    assert sum(child["key"] == "organization" for child in children) == 2

    flat = asyncio.run(routes.get_types_list(True, Mock(), user))
    keys = [child["key"] for child in flat]
    assert len(keys) == len(set(keys))
    assert set(keys) == {child["key"] for child in children}
    assert keys.count("username") == keys.count("organization") == 1
    assert "socialaccount" in keys
    first_username = next(child for child in children if child["key"] == "username")
    assert (
        next(child for child in flat if child["key"] == "username")["icon"]
        == (first_username["icon"])
    )


def test_flat_catalog_preserves_distinct_types_with_same_label(monkeypatch):
    first = {"key": "username", "label": "Username", "fields": ["value"]}
    custom = {"key": "custom_handle", "label": "Username", "custom": True}
    service = Mock()
    service.get_types_list.return_value = [
        {"children": [first]},
        {"children": [dict(first), custom]},
    ]
    monkeypatch.setattr(routes, "create_type_registry_service", lambda db: service)

    flat = asyncio.run(routes.get_types_list(True, Mock(), SimpleNamespace(id=uuid4())))
    assert flat == [first, custom]
    assert flat[0] is first
