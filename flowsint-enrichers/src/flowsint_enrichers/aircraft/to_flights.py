import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.aviation._base import AviationEnricher
from flowsint_enrichers.aviation._client import (
    AviationProviderError,
    AviationRateLimited,
    PublicAviationClient,
    aviation_http_client,
)
from flowsint_enrichers.aviation._history import (
    ObservedFlight,
    TracePoint,
    observed_flights,
    parse_trace,
    trace_url,
)
from flowsint_enrichers.aviation._mapping import aircraft_details
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_types import Aircraft, Flight

MAX_HISTORY_POINTS = 200_000


@flowsint_enricher
class AircraftToFlightsEnricher(AviationEnricher):
    """Build observed flight history from free daily ADSB.lol aircraft traces."""

    metadata = EnricherMetadata(
        description="Retrieves free ADSB.lol daily aircraft traces for a UTC date range and infers observed airborne segments using ground states, provider leg markers and coverage gaps. Links dated Flight nodes and sampled positions to the input Aircraft node, preserving its identity; endpoints are observations, not confirmed takeoff, landing or airports.",
        providers=("ADSB.lol", "adsbdb"),
        api_key_requirement="not_required",
        api_key_notes="No API key. ADSB.lol archive data is ODbL 1.0; retain attribution. Registration inputs use the current adsbdb ICAO mapping, which does not prove historical registration. Archive availability varies; missing days do not prove no flights.",
    )
    InputType = Aircraft
    OutputType = Flight

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._flights: list[ObservedFlight] = []
        self._aircraft_hexes: dict[str, str] = {}

    @classmethod
    def name(cls) -> str:
        return "aircraft_to_flights"

    @classmethod
    def category(cls) -> str:
        return "Aircraft"

    @classmethod
    def key(cls) -> str:
        return "identifier"

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "start_date",
                "type": "string",
                "required": False,
                "description": "First UTC day (YYYY-MM-DD); defaults to six days before end_date",
            },
            {
                "name": "end_date",
                "type": "string",
                "required": False,
                "description": "Last UTC day (YYYY-MM-DD, inclusive); defaults to yesterday. Maximum range: 31 completed days",
            },
            {
                "name": "gap_minutes",
                "type": "string",
                "required": False,
                "default": "30",
                "description": "Split observed flights after a coverage gap in minutes (5–180)",
            },
            {
                "name": "max_flights",
                "type": "string",
                "required": False,
                "default": "50",
                "description": "Maximum newest observed flights per aircraft (integer, 1–100)",
            },
            {
                "name": "positions_per_flight",
                "type": "string",
                "required": False,
                "default": "20",
                "description": "Maximum stored positions per flight, including endpoints (integer, 2–200)",
            },
        ]

    def date_range(self) -> list[date]:
        today = datetime.now(timezone.utc).date()

        def parameter(name: str, default: date) -> date:
            value = self.params.get(name)
            if value is None or isinstance(value, str) and not value.strip():
                return default
            if isinstance(value, str):
                value = value.strip()
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", value
            ):
                raise InvalidEnricherParams(f"{name} must use YYYY-MM-DD")
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise InvalidEnricherParams(f"{name} is not a valid date") from exc

        end = parameter("end_date", today - timedelta(days=1))
        try:
            start = parameter("start_date", end - timedelta(days=6))
        except OverflowError as exc:
            raise InvalidEnricherParams("Date range is out of bounds") from exc
        count = (end - start).days + 1
        if not 1 <= count <= 31 or end >= today:
            raise InvalidEnricherParams(
                "Use 1–31 completed UTC days, ordered from start_date to end_date"
            )
        return [start + timedelta(days=offset) for offset in range(count)]

    async def scan(self, data: list[InputType]) -> list[OutputType]:
        self._flights, self._aircraft_hexes = [], {}
        days = self.date_range()
        gap = self.numeric_param("gap_minutes", "30", 5, 180) * 60
        limit = self.numeric_param("max_flights", "50", 1, 100)
        positions = self.numeric_param("positions_per_flight", "20", 2, 200)
        if not limit.is_integer() or not positions.is_integer():
            raise InvalidEnricherParams(
                "max_flights and positions_per_flight must be integers"
            )
        processed = set()
        async with aviation_http_client() as http:
            client = PublicAviationClient(http)
            for original in data:
                try:
                    if re.fullmatch(r"[0-9A-F]{6}", original.identifier):
                        hex_id = original.identifier
                    elif original.icao_hex:
                        hex_id = original.icao_hex
                    else:
                        url = (
                            f"https://api.adsbdb.com/v0/aircraft/{original.identifier}"
                        )
                        payload = await client.get(url)
                        if payload is None:
                            self.warn(
                                f"Cannot resolve ICAO hex for {original.identifier}; skipped"
                            )
                            continue
                        resolved = aircraft_details(payload, url)
                        if resolved.registration != original.identifier:
                            raise AviationProviderError(
                                "adsbdb: registration lookup mismatch"
                            )
                        hex_id = resolved.identifier
                    self._aircraft_hexes[original.identifier] = hex_id
                    if hex_id in processed:
                        continue
                    processed.add(hex_id)
                    points: list[TracePoint] = []
                    rate_limited = False
                    available_days = 0
                    for day in reversed(days):
                        url = trace_url(hex_id, day)
                        try:
                            payload = await client.get(url)
                            if payload is None:
                                self.warn(
                                    f"No archive available for {hex_id} on {day}; not evidence of no flights"
                                )
                                continue
                            daily, skipped = await asyncio.to_thread(
                                parse_trace,
                                payload,
                                hex_id,
                                day,
                                url,
                                datetime.now(timezone.utc),
                            )
                            available_days += 1
                            remaining = MAX_HISTORY_POINTS - len(points)
                            points.extend(
                                sorted(daily, key=lambda p: p.position.observed_at)[
                                    -remaining:
                                ]
                            )
                            if skipped:
                                self.warn(
                                    f"Skipped {skipped} stale or invalid historical positions for {hex_id} on {day}"
                                )
                            if len(points) >= MAX_HISTORY_POINTS:
                                self.warn(
                                    f"History processing limit reached for {hex_id}; retaining the newest {MAX_HISTORY_POINTS} positions"
                                )
                                break
                        except AviationRateLimited as exc:
                            self.warn(str(exc))
                            rate_limited = True
                            break
                        except AviationProviderError as exc:
                            self.warn(f"History {hex_id} on {day}: {exc}")
                    segments = await asyncio.to_thread(
                        observed_flights, points, gap, int(positions)
                    )
                    if len(segments) > limit:
                        self.warn(
                            f"History limited to {int(limit)} newest observed flights for {hex_id}"
                        )
                    self._flights.extend(segments[-int(limit) :])
                    self.info(
                        f"History {hex_id}: {available_days}/{len(days)} archive days available, {len(segments)} observed flight segments"
                    )
                    if rate_limited:
                        break
                except AviationRateLimited as exc:
                    self.warn(str(exc))
                    break
                except (AviationProviderError, ValidationError, ValueError) as exc:
                    self.warn(
                        f"History lookup failed for {original.identifier}: {type(exc).__name__}"
                    )
        return [segment.flight for segment in self._flights]

    def postprocess(
        self, results: list[OutputType], input_data: list[InputType] | None = None
    ) -> list[OutputType]:
        observed_hexes = {flight.aircraft_hex for flight in results}
        aircraft_by_hex: dict[str, list[Aircraft]] = {}
        for original in input_data or []:
            hex_id = self._aircraft_hexes.get(original.identifier)
            if hex_id is not None and hex_id in observed_hexes:
                aircraft = original.model_copy(update={"icao_hex": hex_id})
                self.create_node(aircraft)
                aircraft_by_hex.setdefault(hex_id, []).append(aircraft)
        for segment in self._flights:
            aircraft_nodes = aircraft_by_hex.get(segment.flight.aircraft_hex, [])
            self.create_node(segment.flight)
            for aircraft in aircraft_nodes:
                self.create_relationship(
                    aircraft, segment.flight, "HAS_OBSERVED_FLIGHT"
                )
            for position in segment.positions:
                # Historical registration/type snapshots belong to observations;
                # do not overwrite present-day aircraft metadata with them.
                self.create_node(position)
                for aircraft in aircraft_nodes:
                    self.create_relationship(
                        aircraft, position, "HAS_POSITION_OBSERVATION"
                    )
                self.create_relationship(
                    segment.flight, position, "HAS_POSITION_OBSERVATION"
                )
        return results


InputType = AircraftToFlightsEnricher.InputType
OutputType = AircraftToFlightsEnricher.OutputType
