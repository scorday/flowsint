"""Map the public providers' documented fields into Flowsint entities."""

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from flowsint_types import Aircraft, AircraftPosition

from ._client import AviationProviderError


def text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value) if math.isfinite(value) else None
        except OverflowError:
            return None
    return None


def aircraft_details(payload: dict[str, Any], url: str) -> Aircraft:
    response = payload.get("response")
    raw = response.get("aircraft") if isinstance(response, dict) else None
    if not isinstance(raw, dict) or not text(raw.get("mode_s")):
        raise AviationProviderError(
            "adsbdb: missing aircraft record or Mode-S identifier"
        )
    aircraft = Aircraft(
        identifier=raw["mode_s"],
        icao_hex=raw["mode_s"],
        **{
            field: text(raw.get(key))
            for field, key in {
                "registration": "registration",
                "model": "type",
                "icao_type": "icao_type",
                "manufacturer": "manufacturer",
                "registered_owner": "registered_owner",
                "registered_owner_country": "registered_owner_country_name",
            }.items()
        },
        details_source="adsbdb",
        details_source_url=url,
        details_retrieved_at=datetime.now(timezone.utc),
    )
    return aircraft


def position_records(payload: dict[str, Any]) -> tuple[list[Any], datetime]:
    now = number(payload.get("now"))
    records = payload.get("ac")
    if (
        payload.get("msg") not in (None, "No error")
        or not isinstance(records, list)
        or now is None
        or now <= 0
    ):
        raise AviationProviderError("ADSB.lol: invalid position response")
    # readsb uses seconds; ADSBexchange-compatible envelopes can use milliseconds.
    if now > 100_000_000_000:
        now /= 1000
    try:
        return records, datetime.fromtimestamp(now, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise AviationProviderError("ADSB.lol: invalid response timestamp") from exc


def position_observation(
    raw: dict[str, Any],
    provider_time: datetime,
    retrieved_at: datetime,
    source_url: str,
    max_age_seconds: float,
) -> AircraftPosition | None:
    age = number(raw.get("seen_pos"))
    latitude, longitude = number(raw.get("lat")), number(raw.get("lon"))
    if age is None or age < 0 or latitude is None or longitude is None:
        return None
    observed_at = provider_time - timedelta(seconds=age)
    if not 0 <= (retrieved_at - observed_at).total_seconds() <= max_age_seconds:
        return None
    aircraft_hex = str(raw.get("hex", "")).upper()
    altitude = raw.get("alt_baro")
    optional = {
        "altitude_baro_ft": number(altitude),
        "ground_speed_knots": number(raw.get("gs")),
        "track_degrees": number(raw.get("track")),
        "callsign": text(raw.get("flight")),
        "registration": text(raw.get("r")),
        "icao_type": text(raw.get("t")),
    }
    if altitude == "ground":
        optional["on_ground"] = True
    elif number(altitude) is not None:
        optional["on_ground"] = False
    return AircraftPosition(
        observation_id=AircraftPosition.make_id(aircraft_hex, observed_at),
        aircraft_hex=aircraft_hex,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        latitude=latitude,
        longitude=longitude,
        source="ADSB.lol",
        source_url=source_url,
        **{key: value for key, value in optional.items() if value is not None},
    )


def aircraft_from_position(position: AircraftPosition) -> Aircraft:
    return Aircraft(
        identifier=position.aircraft_hex,
        icao_hex=position.aircraft_hex,
        **{
            key: value
            for key in ("registration", "icao_type")
            if (value := getattr(position, key)) is not None
        },
    )


def distance_nm(lat: float, lon: float, position: AircraftPosition) -> float:
    a_lat, b_lat = math.radians(lat), math.radians(position.latitude)
    d_lat = b_lat - a_lat
    d_lon = math.radians(position.longitude - lon)
    haversine = math.sin(d_lat / 2) ** 2 + (
        math.cos(a_lat) * math.cos(b_lat) * math.sin(d_lon / 2) ** 2
    )
    return 3440.065 * 2 * math.asin(math.sqrt(min(1, max(0, haversine))))
