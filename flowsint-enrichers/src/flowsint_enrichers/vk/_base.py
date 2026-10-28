import os
from typing import Any

from pydantic import ValidationError

from flowsint_core.core.enricher_base import Enricher, InvalidEnricherParams
from flowsint_core.core.logger import Logger
from flowsint_types import SocialAccount

from ._client import VKError
from ._mapping import profile_identifier

SECRET = "VK_SERVICE_TOKEN"
TOKEN_DESCRIPTION = "VK service token from Vault; falls back to server VK_SERVICE_TOKEN"
KEY_NOTES = "Requires a VK service token in Vault (VK_SERVICE_TOKEN) or the server environment. Privacy restrictions still apply. The token is sent only to api.vk.ru."


class VKEnricher(Enricher):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("params_schema", self.get_params_schema())
        super().__init__(**kwargs)

    @classmethod
    def icon(cls) -> str:
        return "Users"

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": SECRET,
                "type": "vaultSecret",
                "required": False,
                "description": TOKEN_DESCRIPTION,
            }
        ]

    def resolve_params(self) -> dict[str, Any]:
        # Resolve the selected project Vault entry first. Never use a literal key
        # provided through public launch parameters as a credential.
        secret = None
        if self.vault is not None:
            reference = self.params.get(SECRET)
            if reference:
                secret = self.vault.get_secret(reference)
            if secret is None:
                secret = self.vault.get_secret(SECRET)
        if secret is None:
            secret = os.getenv(SECRET)
        if (
            not isinstance(secret, str)
            or not secret.strip()
            or any(c.isspace() for c in secret)
        ):
            raise InvalidEnricherParams(
                "Configure VK_SERVICE_TOKEN in Vault or the server environment"
            )
        resolved = {
            param["name"]: self.params.get(param["name"], param.get("default"))
            for param in self.params_schema
            if param["type"] != "vaultSecret"
        }
        resolved[SECRET] = secret
        return resolved

    def token(self) -> str:
        value = self.get_secret(SECRET, os.getenv(SECRET))
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(c.isspace() for c in value)
        ):
            raise InvalidEnricherParams(
                "Configure VK_SERVICE_TOKEN in Vault or the server environment"
            )
        return value

    def preprocess(self, values: list[Any]) -> list[Any]:
        valid = []
        for value in values:
            try:
                if isinstance(value, str):
                    value = {self.key(): value}
                item = self.InputType.model_validate(value)
                profile_identifier(item)
                valid.append(item)
            except (ValidationError, ValueError, TypeError, VKError):
                self.warn("Skipped invalid VK input")
        return valid

    def warn(self, message: str) -> None:
        Logger.warn(self.sketch_id, {"message": f"[{self.name()}] {message}"})

    def error(self, message: str) -> None:
        Logger.error(self.sketch_id, {"message": f"[{self.name()}] {message}"})

    def friend_limit(self) -> int:
        raw = self.params.get("max_friends", "1000")
        if (
            not isinstance(raw, str)
            or not raw.isascii()
            or not raw.isdecimal()
            or not 1 <= int(raw) <= 10000
        ):
            raise InvalidEnricherParams(
                "max_friends must be an integer between 1 and 10000"
            )
        return int(raw)

    def store_profiles(self, results: list[SocialAccount]) -> list[SocialAccount]:
        for account in results:
            self.create_node(account)
        return results
