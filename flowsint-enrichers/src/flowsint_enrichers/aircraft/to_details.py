from typing import Any

from pydantic import ValidationError

from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_enrichers.aviation._base import AviationEnricher
from flowsint_enrichers.aviation._client import (
    AviationProviderError,
    AviationRateLimited,
    PublicAviationClient,
    aviation_http_client,
)
from flowsint_enrichers.aviation._mapping import aircraft_details
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_types import Aircraft


@flowsint_enricher
class AircraftToDetailsEnricher(AviationEnricher):
    """Look up aircraft registry details using the public adsbdb aircraft endpoint."""

    metadata = EnricherMetadata(
        description="Looks up an aircraft by registration or ICAO hex using adsbdb and records its model, manufacturer and reported registered owner. Registered ownership does not establish the operator, beneficial owner or passengers.",
        providers=("adsbdb",),
        api_key_requirement="not_required",
        api_key_notes="Public aircraft lookup, no API key. Does not request restricted flight-route data. Registry details may be incomplete or outdated.",
    )
    InputType = Aircraft
    OutputType = Aircraft

    @classmethod
    def name(cls) -> str:
        return "aircraft_to_details"

    @classmethod
    def category(cls) -> str:
        return "Aircraft"

    @classmethod
    def key(cls) -> str:
        return "identifier"

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        return []

    async def scan(self, data: list[InputType]) -> list[OutputType]:
        results = {}
        async with aviation_http_client() as http:
            client = PublicAviationClient(http)
            for original in data:
                url = f"https://api.adsbdb.com/v0/aircraft/{original.identifier}"
                try:
                    payload = await client.get(url)
                    if payload is None:
                        self.warn(f"No registry record for {original.identifier}")
                        continue
                    aircraft = aircraft_details(payload, url)
                    if original.identifier not in (
                        aircraft.identifier,
                        aircraft.registration,
                    ):
                        raise AviationProviderError(
                            "adsbdb: result does not match requested identifier"
                        )
                    results[aircraft.identifier] = aircraft
                except AviationRateLimited as exc:
                    self.warn(str(exc))
                    break
                except (AviationProviderError, ValidationError, ValueError) as exc:
                    self.warn(
                        f"Lookup failed for {original.identifier}: {type(exc).__name__}"
                    )
        return list(results.values())

    def postprocess(
        self, results: list[OutputType], input_data: list[InputType] | None = None
    ) -> list[OutputType]:
        for aircraft in results:
            self.create_node(aircraft)
            for original in input_data or []:
                if original.identifier in (aircraft.identifier, aircraft.registration):
                    self.store_alias(original, aircraft)
        return results


InputType = AircraftToDetailsEnricher.InputType
OutputType = AircraftToDetailsEnricher.OutputType
