"""Bounded VK API client; credentials and raw error bodies never leave this adapter."""

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

API = "https://api.vk.ru/method/"
VERSION = "5.199"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
PROFILE_FIELDS = "screen_name,photo_200,city,country,verified,counters,status"
FRIEND_FIELDS = "screen_name,photo_200,city,country"


class VKError(Exception):
    """Sanitized provider failure, safe for the normal enricher logger."""


class VKStopped(VKError):
    """The batch must stop without retrying or changing credentials."""


class VKPrivateProfile(VKError):
    """The API explicitly reported error 30."""


@dataclass
class _Gate:
    lock: Any = field(default_factory=threading.Lock)
    next_start: float = 0
    cooldown_until: float = 0


_gates: dict[str, _Gate] = {}
_gates_lock = threading.Lock()


class VKClient:
    def __init__(self, http: httpx.AsyncClient, token: str) -> None:
        self.http = http
        self._token = token
        self.requests = 0
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        with _gates_lock:
            self._gate = _gates.setdefault(fingerprint, _Gate())

    async def _pace(self) -> None:
        while True:
            with self._gate.lock:
                now = time.monotonic()
                if now < self._gate.cooldown_until:
                    raise VKStopped("VK: cooldown active; retry later")
                delay = self._gate.next_start - now
                if delay <= 0:
                    self._gate.next_start = now + 0.25
                    return
            await asyncio.sleep(delay)

    def _stop(self, message: str) -> None:
        with self._gate.lock:
            self._gate.cooldown_until = max(
                self._gate.cooldown_until, time.monotonic() + 60
            )
        raise VKStopped(message)

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        if method not in {"users.get", "friends.get"}:
            raise VKError("VK: unsupported method")
        if self.requests >= 100:
            raise VKStopped("VK: batch request budget reached (100 calls)")
        await self._pace()
        self.requests += 1
        try:
            async with self.http.stream(
                "POST",
                API + method,
                data=params | {"v": VERSION},
                headers={"Authorization": f"Bearer {self._token}"},
            ) as response:
                if response.status_code == 429:
                    self._stop("VK: HTTP 429; batch stopped")
                if response.status_code in {401, 403}:
                    raise VKStopped(f"VK: HTTP {response.status_code}; batch stopped")
                if response.status_code != 200:
                    raise VKError(f"VK: HTTP {response.status_code}")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise VKError("VK: response exceeds size limit")
        except httpx.RequestError:
            raise VKError("VK: network request failed") from None
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            raise VKError("VK: invalid JSON response") from None
        if not isinstance(payload, dict):
            raise VKError("VK: invalid response envelope")
        if "error" in payload:
            error = payload["error"]
            code = error.get("error_code") if isinstance(error, dict) else None
            subcode = error.get("error_subcode") if isinstance(error, dict) else None
            if type(code) is not int:
                raise VKError("VK: invalid error response")
            if code == 30:
                raise VKPrivateProfile("VK: profile is private (code 30)")
            if code in {6, 9, 14, 17, 29, 32}:
                self._stop(f"VK: restriction code {code}; batch stopped")
            if code in {2, 5, 7, 20, 21, 23, 27, 28, 38, 42, 1051} or subcode in {
                1133,
                1134,
            }:
                raise VKStopped(
                    f"VK: authorization or application restriction (code {code})"
                )
            raise VKError(f"VK: API error code {code}")
        if "response" not in payload:
            raise VKError("VK: missing response")
        return payload["response"]

    async def profile(self, identifier: str) -> dict[str, Any]:
        data = await self.call(
            "users.get", {"user_ids": identifier, "fields": PROFILE_FIELDS}
        )
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
        ):
            raise VKError("VK: profile not found or invalid profile response")
        profile = data[0]
        if type(profile.get("id")) is not int or profile["id"] < 1:
            raise VKError("VK: invalid profile ID")
        if identifier.isdecimal() and profile["id"] != int(identifier):
            raise VKError("VK: returned profile does not match requested ID")
        return profile

    async def friends_page(
        self, user_id: int, offset: int, count: int
    ) -> dict[str, Any]:
        data = await self.call(
            "friends.get",
            {
                "user_id": user_id,
                "offset": offset,
                "count": count,
                "fields": FRIEND_FIELDS,
            },
        )
        if (
            not isinstance(data, dict)
            or type(data.get("count")) is not int
            or data["count"] < 0
            or not isinstance(data.get("items"), list)
            or len(data["items"]) > count
            or len(data["items"]) > data["count"]
        ):
            raise VKError("VK: invalid friends page")
        records = []
        for item in data["items"]:
            record = {"id": item} if type(item) is int else item
            if (
                not isinstance(record, dict)
                or type(record.get("id")) is not int
                or record["id"] < 1
            ):
                raise VKError("VK: invalid friend ID")
            records.append(record)
        return {"count": data["count"], "items": records}


def vk_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20),
        follow_redirects=False,
        headers={"Accept": "application/json", "User-Agent": "Flowsint/VK"},
    )
