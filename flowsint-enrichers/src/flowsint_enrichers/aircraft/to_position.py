import re

from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.aviation._base import AviationEnricher
from flowsint_enrichers.aviation._client import (
    AviationProviderError,
    AviationRateLimited,
    PublicAviationClient,
    aviation_http_client,
)
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_types import Aircraft, AircraftPosition


@flowsint_enricher
class AircraftToPositionEnricher(AviationEnricher):
    """Retrieve fresh observed positions, rather than assume continuous coverage."""

    metadata = EnricherMetadata(
        description="Retrieves fresh ADSB.lol position observations for an aircraft registration or ICAO hex and links them to the input Aircraft node, preserving its identity. Includes observation time, coordinates and available altitude and speed. Missing coverage or stale data produces no position, not evidence of absence.",
        providers=("ADSB.lol",),
        api_key_requirement="not_required",
        api_key_notes="Free public API, ODbL 1.0 data; attribute ADSB.lol. The provider asks production users to contact them. Coverage and availability are not guaranteed.",
    )
    InputType = Aircraft
    OutputType = AircraftPosition

    @classmethod
    def name(cls) -> str:
        return "aircraft_to_position"

    @classmethod
    def category(cls) -> str:
        return "Aircraft"

    @classmethod
    def key(cls) -> str:
        return "identifier"

    async def scan(self, data: list[InputType]) -> list[OutputType]:
        self.numeric_param("max_age_seconds", "300", 1, 3600)
        results = {}
        async with aviation_http_client() as http:
            client = PublicAviationClient(http)
            for aircraft in data:
                endpoint = (
                    "hex"
                    if re.fullmatch(r"[0-9A-F]{6}", aircraft.identifier)
                    else "reg"
                )
                url = f"https://api.adsb.lol/v2/{endpoint}/{aircraft.identifier}"
                try:
                    payload = await client.get(url)
                    positions = (
                        self.positions(payload, url) if payload is not None else []
                    )
                    matched = [
                        position
                        for position in positions
                        if aircraft.identifier
                        in (
                            position.aircraft_hex,
                            (position.registration or "").upper(),
                        )
                    ]
                    if not matched:
                        self.warn(
                            f"No fresh position observed for {aircraft.identifier}; coverage may be missing"
                        )
                    for position in matched:
                        results[position.observation_id] = position
                except AviationRateLimited as exc:
                    self.warn(str(exc))
                    break
                except AviationProviderError as exc:
                    self.warn(str(exc))
        return list(results.values())

    def postprocess(
        self, results: list[OutputType], input_data: list[InputType] | None = None
    ) -> list[OutputType]:
        for position in results:
            for original in input_data or []:
                if original.identifier in (
                    position.aircraft_hex,
                    (position.registration or "").upper(),
                ):
                    self.store_position(position, original)
        return results


InputType = AircraftToPositionEnricher.InputType
OutputType = AircraftToPositionEnricher.OutputType
