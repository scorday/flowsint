"""Small, paced HTTP adapter. No paid endpoints, API keys or route database calls."""

import asyncio
import gzip
import io
import json
import math
import threading
import time
import zlib
from _thread import LockType
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class AviationProviderError(Exception):
    """A request failed; messages deliberately exclude response bodies."""


class AviationRateLimited(AviationProviderError):
    """Stop the current batch rather than hammering a rate-limited provider."""


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024


def _decode_json(body: bytes) -> dict[str, Any]:
    # The history server normally sets Content-Encoding, which httpx decodes.
    # Some mirrors serve the gzipped trace as an ordinary JSON file instead.
    try:
        if body.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                body = compressed.read(MAX_JSON_BYTES + 1)
        if len(body) > MAX_JSON_BYTES:
            raise AviationProviderError("Aviation JSON response exceeds size limit")
        result = json.loads(body)
    except (
        ValueError,
        OSError,
        EOFError,
        UnicodeError,
        zlib.error,
        RecursionError,
    ) as exc:
        raise AviationProviderError(
            "Aviation provider returned invalid JSON or gzip"
        ) from exc
    if not isinstance(result, dict):
        raise AviationProviderError(
            "Aviation provider returned an invalid response envelope"
        )
    return result


@dataclass
class _ProviderGate:
    lock: LockType = field(default_factory=threading.Lock)
    next_request: float = 0
    cooldown_until: float = 0


# Celery calls asyncio.run for each job. Pacing/cooldowns must survive that loop
# closing; only the brief slot reservation uses a thread lock, never network I/O.
# Separate worker processes have independent limits.
_gates: dict[str, _ProviderGate] = {}
_gates_lock = threading.Lock()


def _gate_for(host: str) -> _ProviderGate:
    with _gates_lock:
        return _gates.setdefault(host, _ProviderGate())


def _retry_delay(value: str | None) -> float:
    try:
        delay = float(value or "60")
    except ValueError:
        try:
            delay = (
                parsedate_to_datetime(value or "") - datetime.now(timezone.utc)
            ).total_seconds()
        except (ValueError, TypeError, OverflowError):
            delay = 60
    return max(1, delay) if math.isfinite(delay) else 60


class PublicAviationClient:
    """Async JSON requests with timeouts, per-provider pacing and 429 cooldown."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get(self, url: str) -> dict[str, Any] | None:
        host = httpx.URL(url).host
        gate = _gate_for(host)
        while True:
            with gate.lock:
                now = time.monotonic()
                if gate.cooldown_until > now:
                    raise AviationRateLimited(
                        f"{host}: rate-limit cooldown active; retry later"
                    )
                delay = gate.next_request - now
                if delay <= 0:
                    gate.next_request = now + 1
                    break
            # Recheck both pacing and cooldown after waking: other scans can
            # obtain the next slot or receive a 429 while this scan is asleep.
            await asyncio.sleep(delay)
        try:
            async with self.client.stream("GET", url) as response:
                if response.status_code == 429:
                    with gate.lock:
                        delay = _retry_delay(response.headers.get("Retry-After"))
                        gate.cooldown_until = max(
                            gate.cooldown_until, time.monotonic() + delay
                        )
                    raise AviationRateLimited(
                        f"{host}: rate limited; retry after {delay:.0f}s"
                    )
                if response.status_code == 404:
                    return None
                if response.is_error:
                    raise AviationProviderError(f"{host}: HTTP {response.status_code}")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise AviationProviderError(
                            f"{host}: response exceeds size limit"
                        )
        except httpx.RequestError as exc:
            raise AviationProviderError(f"{host}: network request failed") from exc
        return await asyncio.to_thread(_decode_json, bytes(body))


def aviation_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15),
        headers={"User-Agent": "Flowsint/aviation", "Accept": "application/json"},
        follow_redirects=False,
    )
