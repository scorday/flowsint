"""The assistant readiness endpoint exposes the configured key name, never its value."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.api.deps import get_current_user
from app.main import app


@pytest.mark.parametrize("exists", [True, False])
def test_chat_key_status_includes_configured_key_name(client, exists):
    service = MagicMock()
    service.chat_key_exist.return_value = exists
    service.chat_key_name.return_value = "ROUTERAI_API_KEY"
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="alice")
    with patch("app.api.routes.keys.create_key_service", return_value=service):
        response = client.get("/api/keys/chat-key-exists")
    assert response.status_code == 200
    assert response.json() == {"exists": exists, "key_name": "ROUTERAI_API_KEY"}
    service.chat_key_exist.assert_called_once_with("alice")
