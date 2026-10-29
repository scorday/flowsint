"""Provider selection and key readiness must agree across assistant features."""

from unittest.mock import MagicMock, patch

import pytest

from flowsint_core.core.llm.config import get_llm_settings
from flowsint_core.core.llm.factory import create_llm_provider
from flowsint_core.core.project_scope import ProjectScope, project_scope
from flowsint_core.core.services.chat_service import ChatService
from flowsint_core.core.services.key_service import create_key_service
from flowsint_core.core.services.template_generator_service import (
    TemplateGeneratorService,
)
from flowsint_core.core.vault import Vault


@pytest.fixture(autouse=True)
def clean_llm_environment(monkeypatch):
    for name in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_BASE_URL",
        "LLM_API_KEY_NAME",
        "LLM_API_KEY",
        "MISTRAL_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "ROUTERAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_mistral_connection_is_preserved():
    settings = get_llm_settings()
    assert settings.provider == "mistral"
    assert settings.api_key_name == "MISTRAL_API_KEY"
    with patch("flowsint_core.core.llm.providers.mistral.MistralProvider") as provider:
        create_llm_provider(api_key="vault-test-key")
    provider.assert_called_once_with(api_key="vault-test-key")


@pytest.mark.parametrize("model", ["openai/gpt-6-luna", "deepseek/deepseek-v4.1-flash"])
def test_routerai_uses_openai_transport_with_explicit_model(monkeypatch, model):
    monkeypatch.setenv("LLM_PROVIDER", "router-ai")
    monkeypatch.setenv("LLM_MODEL", model)
    monkeypatch.setenv("ROUTERAI_API_KEY", "environment-test-key")
    # OpenAI-specific environment settings must not redirect RouterAI calls.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://other.example/v1")
    with patch("flowsint_core.core.llm.providers.openai.OpenAIProvider") as provider:
        create_llm_provider(api_key="vault-test-key")
    provider.assert_called_once_with(
        api_key="vault-test-key", model=model, base_url="https://routerai.ru/api/v1"
    )


def test_routerai_requires_model_and_its_own_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "router-ai")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        create_llm_provider()
    monkeypatch.setenv("LLM_MODEL", "deepseek/test")
    monkeypatch.setenv("MISTRAL_API_KEY", "wrong-provider-key")
    with pytest.raises(ValueError, match="ROUTERAI_API_KEY"):
        create_llm_provider()


def test_generic_endpoint_model_and_key_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://compatible.example/v1")
    monkeypatch.setenv("LLM_MODEL", "configured-model")
    monkeypatch.setenv("LLM_API_KEY_NAME", "CUSTOM_LLM_KEY")
    monkeypatch.setenv("CUSTOM_LLM_KEY", "custom-test-key")
    with patch("flowsint_core.core.llm.providers.openai.OpenAIProvider") as provider:
        create_llm_provider(model="explicit-model")
    provider.assert_called_once_with(
        api_key="custom-test-key",
        model="explicit-model",
        base_url="https://compatible.example/v1",
    )


def test_openai_base_url_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compatible.example/v1")
    assert (
        get_llm_settings(provider="openai").base_url == "https://compatible.example/v1"
    )


def test_invalid_provider_does_not_echo_configuration():
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER") as error:
        get_llm_settings(provider="invalid-private-value")
    assert "invalid-private-value" not in str(error.value)


@pytest.mark.parametrize("feature", ["chat", "template"])
def test_chat_and_template_resolve_the_same_vault_key(monkeypatch, feature):
    monkeypatch.setenv("LLM_PROVIDER", "router-ai")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-6-luna")
    vault = MagicMock()
    vault.get_secret.return_value = "project-test-key"
    if feature == "chat":
        service = ChatService(
            db=MagicMock(), chat_repo=MagicMock(), vault_service=vault
        )
        module = "chat_service"
        call = service.get_llm_provider
    else:
        service = TemplateGeneratorService(db=MagicMock(), vault_service=vault)
        module = "template_generator_service"
        call = service._get_llm_provider
    with patch(f"flowsint_core.core.services.{module}.create_llm_provider") as factory:
        call("alice")
    vault.get_secret.assert_called_once_with("alice", "ROUTERAI_API_KEY")
    factory.assert_called_once_with(provider="router-ai", api_key="project-test-key")


def test_key_readiness_matches_provider_and_project(monkeypatch, db_session):
    monkeypatch.setenv("LLM_PROVIDER", "router-ai")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-6-luna")
    service = create_key_service(db_session)
    with project_scope(ProjectScope(user_id="alice", project_id="project-a")):
        Vault(db_session, "alice").set_secret("MISTRAL_API_KEY", "mistral-test-key")
        assert not service.chat_key_exist("alice")
        Vault(db_session, "alice").set_secret("ROUTERAI_API_KEY", "router-test-key")
        assert service.chat_key_exist("alice")
        assert service.chat_key_name() == "ROUTERAI_API_KEY"
    with project_scope(ProjectScope(user_id="bob", project_id="project-a")):
        assert service.chat_key_exist("bob")
    with project_scope(ProjectScope(user_id="alice", project_id="project-b")):
        assert not service.chat_key_exist("alice")


@pytest.mark.parametrize("key_name", ["ROUTERAI_API_KEY", "LLM_API_KEY"])
def test_server_key_enables_chat_without_vault_key(monkeypatch, db_session, key_name):
    monkeypatch.setenv("LLM_PROVIDER", "router-ai")
    monkeypatch.setenv("LLM_MODEL", "deepseek/test")
    monkeypatch.setenv(key_name, "server-test-key")
    service = create_key_service(db_session)
    with project_scope(ProjectScope(user_id="alice", project_id="project-a")):
        assert service.chat_key_exist("alice")
    with patch("flowsint_core.core.llm.providers.openai.OpenAIProvider") as provider:
        create_llm_provider()
    assert provider.call_args.kwargs["api_key"] == "server-test-key"
