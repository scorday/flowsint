import math
from typing import Any

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.aviation._base import AviationEnricher
from flowsint_enrichers.aviation._client import (
    AviationProviderError,
    AviationRateLimited,
    PublicAviationClient,
    aviation_http_client,
)
from flowsint_enrichers.aviation._mapping import aircraft_from_position, distance_nm
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_types import Aircraft, AircraftPosition, Location


@flowsint_enricher
class LocationToAircraftEnricher(AviationEnricher):
    """Discover observed aircraft around explicit location coordinates."""

    metadata = EnricherMetadata(
        description="Finds aircraft with fresh ADSB.lol position observations within a radius of a Location's explicit latitude and longitude. Adds aircraft and dated observations to the graph; results reflect receiver coverage and are not a complete traffic inventory.",
        providers=("ADSB.lol",),
        api_key_requirement="not_required",
        api_key_notes="Free public API, ODbL 1.0 data; attribute ADSB.lol. The provider asks production users to contact them. Radius is in nautical miles, up to 250 NM.",
    )
    InputType = Location
    OutputType = Aircraft

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._observations: list[tuple[Location, AircraftPosition]] = []

    @classmethod
    def name(cls) -> str:
        return "location_to_aircraft"

    @classmethod
    def category(cls) -> str:
        return "Location"

    @classmethod
    def key(cls) -> str:
        return "address"

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "radius_nm",
                "type": "string",
                "required": False,
                "default": "25",
                "description": "Search radius in nautical miles (0.1–250); 1 NM = 1.852 km",
            },
            {
                "name": "max_results",
                "type": "string",
                "required": False,
                "default": "100",
                "description": "Nearest aircraft per location (integer, 1–500)",
            },
            *super().get_params_schema(),
        ]

    async def scan(self, data: list[InputType]) -> list[OutputType]:
        self._observations = []
        radius = self.numeric_param("radius_nm", "25", 0.1, 250)
        limit = self.numeric_param("max_results", "100", 1, 500)
        self.numeric_param("max_age_seconds", "300", 1, 3600)
        if not limit.is_integer():
            raise InvalidEnricherParams("max_results must be an integer")
        results = {}
        async with aviation_http_client() as http:
            client = PublicAviationClient(http)
            for location in data:
                lat, lon = location.latitude, location.longitude
                if (
                    lat is None
                    or lon is None
                    or not (
                        math.isfinite(lat)
                        and math.isfinite(lon)
                        and -90 <= lat <= 90
                        and -180 <= lon <= 180
                    )
                ):
                    self.warn(
                        "Location needs valid explicit latitude and longitude; skipped"
                    )
                    continue
                url = f"https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}"
                try:
                    payload = await client.get(url)
                    positions = (
                        self.positions(payload, url) if payload is not None else []
                    )
                    nearby = sorted(
                        (p for p in positions if distance_nm(lat, lon, p) <= radius),
                        key=lambda p: distance_nm(lat, lon, p),
                    )
                    if len(nearby) > limit:
                        self.warn(
                            f"Results limited to {int(limit)} nearest aircraft for this location"
                        )
                    # Multiple records for one hex must not consume the aircraft limit.
                    selected = set()
                    for position in nearby:
                        if position.aircraft_hex in selected:
                            continue
                        selected.add(position.aircraft_hex)
                        self._observations.append((location, position))
                        aircraft = aircraft_from_position(position)
                        results[aircraft.identifier] = aircraft
                        if len(selected) >= limit:
                            break
                    if not selected:
                        self.warn(
                            "No fresh aircraft positions observed in this radius; coverage may be missing"
                        )
                except AviationRateLimited as exc:
                    self.warn(str(exc))
                    break
                except AviationProviderError as exc:
                    self.warn(str(exc))
        return list(results.values())

    def postprocess(
        self, results: list[OutputType], input_data: list[InputType] | None = None
    ) -> list[OutputType]:
        for location, position in self._observations:
            self.store_position(position)
            self.create_node(location)
            self.create_relationship(
                location, position, "HAS_NEARBY_AIRCRAFT_OBSERVATION"
            )
        return results


InputType = LocationToAircraftEnricher.InputType
OutputType = LocationToAircraftEnricher.OutputType
