"""Domain identities, independent of graph labels and view presentation.

Only strong identifiers participate in automatic coalescing. In particular a
person's name and an organisation's name are never identity keys.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

PRESENTATION = frozenset(
    {"x", "y", "nodeSize", "nodeColor", "nodeIcon", "nodeFlag", "nodeShape", "nodeRole"}
)
RESERVED = frozenset(
    {
        "id",
        "uid",
        "scope_key",
        "project_id",
        "investigation_id",
        "sketch_id",
        "identity_keys",
        "legacy_ids",
        "view_ids",
        "deleted_at",
        "graph_history",
        "graph_edge_key",
        "migration_records",
    }
)
VK_HOSTS = {"vk.com", "vk.ru", "www.vk.com", "www.vk.ru", "m.vk.com", "m.vk.ru"}


class IdentityConflict(ValueError):
    """An alias would join two different authoritative identifiers."""


@dataclass(frozen=True)
class GraphScope:
    project_id: str
    investigation_id: str
    sketch_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.project_id or not self.investigation_id:
            raise ValueError("Graph project and investigation are required")

    @property
    def key(self) -> str:
        return json.dumps(
            [self.project_id, self.investigation_id], separators=(",", ":")
        )


def _vk_identifier(value: Any) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    candidate = str(value).strip()
    if "://" in candidate:
        url = urlsplit(candidate)
        if url.hostname not in VK_HOSTS or url.query or url.fragment:
            return None
        candidate = url.path.strip("/")
    match = re.fullmatch(r"(?:id)?([1-9][0-9]*)", candidate)
    if match:
        return f"id{match[1]}"
    if re.fullmatch(r"[A-Za-z0-9_.]{1,100}", candidate):
        return candidate.lower()
    return None


def identity_keys(properties: dict[str, Any]) -> list[str]:
    """Return namespaced, normalised keys from flattened entity properties.

    An empty result deliberately means 'unknown identity', not 'same label'.
    VK aliases become equivalent only when supplied together by a resolved
    profile. The repository rejects contradictory numeric VK IDs.
    """
    kind = str(properties.get("nodeType", "")).lower()
    p = {
        k.removeprefix("nodeProperties."): v
        for k, v in properties.items()
        if k.startswith("nodeProperties.")
    }
    keys: set[str] = set()
    if kind == "socialaccount":
        platform = str(p.get("platform") or "").lower().rstrip("/")
        platform = platform.removeprefix("https://").removeprefix("http://")
        profile_url = str(p.get("profile_url") or "")
        host = urlsplit(profile_url).hostname
        username = p.get("username.value", p.get("username"))
        if platform in VK_HOSTS | {"vk", "vkontakte"} or host in VK_HOSTS:
            for value in (
                p.get("vk_user_id"),
                p.get("vk_screen_name"),
                username,
                profile_url,
            ):
                identifier = _vk_identifier(value)
                if identifier:
                    keys.add(f"socialaccount:vk:{identifier}")
        elif platform and username:
            keys.add(f"socialaccount:{platform}:{username}")
    elif kind == "organization":
        # SIREN is a national registration number; names aren't identifiers.
        if re.fullmatch(r"[0-9]{9}", str(p.get("siren", ""))):
            keys.add(f"organization:fr:siren:{p['siren']}")
    elif kind not in {"individual", "person", "avl4_card"}:
        fields = {
            "domain": "domain",
            "email": "email",
            "ip": "address",
            "phone": "number",
            "website": "url",
            "username": "value",
            "asn": "asn_str",
            "cidr": "network",
            "cryptowallet": "address",
        }
        field = fields.get(kind)
        value = p.get(field) if field else None
        if value is not None and str(value).strip():
            value = str(value).strip()
            if kind == "domain":
                value = value.rstrip(".").lower().encode("idna").decode()
            elif kind == "ip":
                value = str(ipaddress.ip_address(value))
            elif kind == "cidr":
                value = str(ipaddress.ip_network(value, strict=False))
            elif kind == "email" and "@" in value:
                local, domain = value.rsplit("@", 1)
                value = f"{local}@{domain.lower()}"
            elif kind == "website":
                url = urlsplit(value)
                value = urlunsplit(
                    (
                        url.scheme.lower(),
                        url.netloc.lower(),
                        url.path or "/",
                        url.query,
                        "",
                    )
                )
            elif kind == "phone":
                # Only E.164 numbers are unambiguous without country context.
                value = re.sub(r"[ ()-]", "", value)
                if not re.fullmatch(r"\+[1-9][0-9]{6,14}", value):
                    return []
            keys.add(f"{kind}:{value}")
    return sorted(keys)


def check_identity_compatibility(keys: list[str]) -> None:
    platforms = {k.split(":", 2)[1] for k in keys if k.startswith("socialaccount:")}
    if len(platforms) > 1:
        raise IdentityConflict("Accounts on different platforms are separate entities")
    vk_ids = {k for k in keys if re.fullmatch(r"socialaccount:vk:id[1-9][0-9]*", k)}
    if len(vk_ids) > 1:
        raise IdentityConflict("VK alias refers to conflicting numeric user IDs")
    # Only resolved VK aliases prove equivalence between different keys.
    non_vk = {k for k in keys if not k.startswith("socialaccount:vk:")}
    if len(non_vk) > 1:
        raise IdentityConflict(
            "Conflicting domain identifiers belong to separate entities"
        )


def split_properties(
    properties: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate canonical data from display overrides, ignoring supplied scope."""
    if properties.get("nodeRole") not in (None, "primary", "secondary"):
        raise ValueError("nodeRole must be primary or secondary")
    entity = {
        k: v
        for k, v in properties.items()
        if k not in RESERVED | PRESENTATION
        and not k.startswith("avl4_")
        and not k.startswith("nodeMetadata.observations")
        and v is not None
    }
    # Null clears a display override, e.g. a flag.
    view = {k: v for k, v in properties.items() if k in PRESENTATION}
    return entity, view


def merge_properties(
    old: dict[str, Any], new: dict[str, Any], *, source: str
) -> dict[str, Any]:
    """Keep new observations without destroying previous conflicting values."""
    result = dict(old)
    history = json.loads(old.get("graph_history") or "[]")
    for key, value in new.items():
        if key in RESERVED or value is None:
            continue
        previous = result.get(key)
        if previous is not None and previous != value:
            observation = {
                "field": key,
                "previous": previous,
                "value": value,
                "source": source,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
            history.append(observation)
        result[key] = value
    if history:
        result["graph_history"] = json.dumps(
            history, ensure_ascii=False, separators=(",", ":")
        )
    return result
