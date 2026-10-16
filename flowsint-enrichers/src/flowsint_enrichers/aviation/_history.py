"""Read readsb daily traces and conservatively split observed airborne segments."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from flowsint_types import AircraftPosition, Flight

from ._client import AviationProviderError
from ._mapping import number, text


@dataclass
class TracePoint:
    position: AircraftPosition
    new_leg: bool = False


@dataclass
class ObservedFlight:
    flight: Flight
    positions: list[AircraftPosition]


def trace_url(aircraft_hex: str, day: date) -> str:
    hex_id = aircraft_hex.lower()
    return f"https://adsb.lol/globe_history/{day:%Y/%m/%d}/traces/{hex_id[-2:]}/trace_full_{hex_id}.json"


def parse_trace(
    payload: dict[str, Any],
    aircraft_hex: str,
    day: date,
    url: str,
    retrieved_at: datetime,
) -> tuple[list[TracePoint], int]:
    epoch = number(payload.get("timestamp"))
    rows = payload.get("trace")
    if (
        (text(payload.get("icao")) or "").upper() != aircraft_hex
        or epoch is None
        or not isinstance(rows, list)
    ):
        raise AviationProviderError("ADSB.lol: invalid or mismatched historical trace")
    try:
        origin = datetime.fromtimestamp(epoch, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise AviationProviderError("ADSB.lol: invalid trace timestamp") from exc
    points = []
    skipped = 0
    pending_leg = False
    for row in rows:
        try:
            if not isinstance(row, list) or len(row) < 7:
                raise ValueError("Invalid trace row")
            flags = row[6]
            if not isinstance(flags, int) or isinstance(flags, bool) or flags < 0:
                raise ValueError("Invalid trace flags")
            if flags & 2:
                pending_leg = True
            extra = row[8] if len(row) > 8 and isinstance(row[8], dict) else {}
            callsign = text(extra.get("flight"))
            if flags & 1:
                skipped += 1
                continue  # Stale position; preserve any leg boundary for the next row.
            seconds = number(row[0])
            if seconds is None or seconds < 0:
                raise ValueError("Invalid trace offset")
            observed_at = origin + timedelta(seconds=seconds)
            if observed_at.date() != day:
                continue  # Midnight overlap belongs to the requested UTC day only.
            lat, lon = number(row[1]), number(row[2])
            if lat is None or lon is None:
                raise ValueError("Missing trace coordinates")
            altitude = row[3]
            height = number(altitude)
            on_ground = (
                True if altitude == "ground" else False if height is not None else None
            )
            optional: dict[str, Any] = {
                "altitude_baro_ft": height if not flags & 8 else None,
                "altitude_geom_ft": height
                if flags & 8
                else number(row[10])
                if len(row) > 10
                else None,
                "ground_speed_knots": number(row[4]),
                # readsb row[5] is heading, not track, on the ground.
                "track_degrees": number(row[5]) if on_ground is not True else None,
                "on_ground": on_ground,
                "callsign": callsign,
                "registration": text(payload.get("r")),
                "icao_type": text(payload.get("t")),
            }
            position = AircraftPosition(
                observation_id=AircraftPosition.make_id(aircraft_hex, observed_at),
                aircraft_hex=aircraft_hex,
                observed_at=observed_at,
                retrieved_at=retrieved_at,
                latitude=lat,
                longitude=lon,
                source="ADSB.lol",
                source_url=url,
                **{key: value for key, value in optional.items() if value is not None},
            )
            points.append(TracePoint(position, pending_leg))
            pending_leg = False
        except (ValidationError, ValueError, TypeError, OverflowError):
            skipped += 1
    return points, skipped


def observed_flights(
    points: list[TracePoint],
    gap_seconds: float,
    max_positions: int,
) -> list[ObservedFlight]:
    # Merge overlapping archives by observation time, preserving provider flags.
    unique: dict[str, TracePoint] = {}
    for point in points:
        key = point.position.observation_id
        duplicate = unique.get(key)
        if duplicate is None:
            unique[key] = point
        elif point.new_leg:
            duplicate.new_leg = True
    ordered = sorted(unique.values(), key=lambda p: p.position.observed_at)
    results: list[ObservedFlight] = []
    current: list[AircraftPosition] = []
    prior_ground: AircraftPosition | None = None
    previous: AircraftPosition | None = None
    start = "archive_start"

    def finish(end: str) -> None:
        # A single airborne report between ground reports is often a noisy
        # ground-state toggle, and is insufficient to reconstruct a flight.
        if sum(p.on_ground is False for p in current) < 2:
            return
        first, last = current[0], current[-1]
        if first.observed_at >= last.observed_at:
            return
        if len(current) <= max_positions:
            sampled = list(current)
        else:
            sampled = [
                current[round(i * (len(current) - 1) / (max_positions - 1))]
                for i in range(max_positions)
            ]
        flight = Flight(
            flight_id=Flight.make_id(
                first.aircraft_hex, first.observed_at, gap_seconds / 60
            ),
            aircraft_hex=first.aircraft_hex,
            first_seen_at=first.observed_at,
            last_seen_at=last.observed_at,
            start_latitude=first.latitude,
            start_longitude=first.longitude,
            end_latitude=last.latitude,
            end_longitude=last.longitude,
            callsigns=sorted({p.callsign for p in current if p.callsign}),
            observation_count=len(current),
            stored_position_count=len(sampled),
            gap_minutes=gap_seconds / 60,
            start_boundary=start,
            end_boundary=end,
            source="ADSB.lol",
            source_urls=sorted({p.source_url for p in current}),
            retrieved_at=max(p.retrieved_at for p in current),
        )
        results.append(ObservedFlight(flight, sampled))

    for point in ordered:
        position = point.position
        gap = (
            previous is not None
            and (position.observed_at - previous.observed_at).total_seconds()
            > gap_seconds
        )
        if gap or point.new_leg:
            boundary = "coverage_gap" if gap else "provider_leg"
            finish(boundary)
            current = []
            prior_ground = None
            start = boundary
        if position.on_ground is True:
            if current:
                current.append(position)
                finish("ground")
                current = []
            prior_ground = position
            start = "ground"
        else:
            if not current and prior_ground is not None:
                current.append(prior_ground)
                prior_ground = None
            current.append(position)
        previous = position
    finish("archive_end")
    return results
