import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from flowsint_types import SocialAccount, Website

from ._client import VKError

VK_HOSTS = {"vk.ru", "vk.com", "www.vk.ru", "www.vk.com", "m.vk.ru", "m.vk.com"}


def profile_identifier(value: Website | SocialAccount) -> str:
    if isinstance(value, Website):
        candidate = str(value.url)
    elif value.profile_url:
        candidate = value.profile_url
    else:
        platform = (value.platform or "").lower().rstrip("/")
        if platform not in VK_HOSTS | {
            "vk",
            "vkontakte",
            "https://vk.ru",
            "https://vk.com",
        }:
            raise VKError("VK: input is not a VK account")
        candidate = value.username.value if value.username else ""
    if "://" in candidate:
        url = urlsplit(candidate)
        if (
            url.scheme not in {"https", "http"}
            or url.netloc.lower() not in VK_HOSTS
            or url.query
            or url.fragment
        ):
            raise VKError("VK: expected a direct VK profile URL")
        candidate = url.path.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.]{1,100}", candidate):
        raise VKError("VK: invalid user ID or screen name")
    if re.fullmatch(r"id[0-9]+", candidate):
        candidate = candidate[2:]
    if candidate.isdecimal() and int(candidate) < 1:
        raise VKError("VK: user ID must be positive")
    return candidate


def account_from_profile(
    raw: dict[str, Any], *, partial: bool = False
) -> SocialAccount:
    user_id = raw.get("id")
    if type(user_id) is not int or user_id < 1:
        raise VKError("VK: invalid profile ID")
    closed = raw.get("is_closed")
    closed = closed if type(closed) is bool else None
    accessible = raw.get("can_access_closed")
    accessible = accessible if type(accessible) is bool else None
    deactivated = raw.get("deactivated")
    deactivated = (
        deactivated
        if isinstance(deactivated, str) and deactivated in {"deleted", "banned"}
        else None
    )
    name = " ".join(
        raw.get(field, "")
        for field in ("first_name", "last_name")
        if isinstance(raw.get(field), str)
    ).strip()
    location = ", ".join(
        raw[field]["title"]
        for field in ("city", "country")
        if isinstance(raw.get(field), dict) and isinstance(raw[field].get("title"), str)
    )
    photo = raw.get("photo_200")
    photo = photo if isinstance(photo, str) and photo.startswith("https://") else None
    counters = raw.get("counters")
    if not isinstance(counters, dict):
        counters = {}
    friends = counters.get("friends")
    friends = friends if type(friends) is int and friends >= 0 else None
    values: dict[str, Any] = dict(
        username=f"id{user_id}",
        platform="vk.ru",
        display_name=name or None,
        profile_url=f"https://vk.ru/id{user_id}",
        profile_picture_url=photo,
        location=location or None,
        bio=raw.get("status") if isinstance(raw.get("status"), str) else None,
        verified=raw.get("verified")
        if type(raw.get("verified")) is bool
        else bool(raw["verified"])
        if type(raw.get("verified")) is int and raw["verified"] in (0, 1)
        else None,
        is_private=closed,
        is_suspended=deactivated == "banned" if deactivated else None,
        vk_user_id=user_id,
        vk_screen_name=raw.get("screen_name")
        if isinstance(raw.get("screen_name"), str)
        else None,
        vk_can_access_closed=accessible,
        vk_deactivated=deactivated,
        vk_profile_status="deactivated"
        if deactivated
        else "closed"
        if closed is True
        else "open"
        if closed is False
        else "unknown",
        vk_friends_reported_count=friends,
        vk_profile_source="VK API",
        vk_profile_retrieved_at=datetime.now(UTC).isoformat(),
    )
    if partial:
        # Friends pages are partial profile records. Do not clear previously
        # enriched fields on MERGE just because this endpoint omitted them.
        allowed = {"nodeLabel", "username", "platform", "profile_url", "vk_user_id"}
        for field, targets in {
            "first_name": {"display_name"},
            "last_name": {"display_name"},
            "photo_200": {"profile_picture_url"},
            "city": {"location"},
            "country": {"location"},
            "screen_name": {"vk_screen_name"},
            "is_closed": {"is_private", "vk_profile_status"},
            "can_access_closed": {"vk_can_access_closed"},
            "deactivated": {"vk_deactivated", "is_suspended", "vk_profile_status"},
        }.items():
            if field in raw:
                allowed.update(targets)
        values = {key: value for key, value in values.items() if key in allowed}
    return SocialAccount(**values)


def enrich_original(original: SocialAccount, profile: SocialAccount) -> SocialAccount:
    """Keep graph identity and user annotations when enriching an existing node."""
    return original.model_copy(
        update=profile.model_dump(
            exclude={"id", "username", "platform", "nodeLabel"}, exclude_unset=True
        )
    )
