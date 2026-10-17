"""Common execution, parameter validation, and position graph operations."""

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from flowsint_core.core.enricher_base import Enricher, InvalidEnricherParams
from flowsint_core.core.logger import Logger
from flowsint_types import Aircraft, AircraftPosition

from ._mapping import aircraft_from_position, position_observation, position_records


class AviationEnricher(Enricher):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("params_schema", self.get_params_schema())
        super().__init__(**kwargs)

    def preprocess(self, values: list[Any]) -> list[Any]:
        # The base implementation returns the original invalid values when every
        # item fails validation. Aviation must never send those to an external API.
        cleaned = []
        for value in values:
            try:
                if isinstance(value, str):
                    value = {self.key(): value}
                cleaned.append(self.InputType.model_validate(value))
            except (ValidationError, TypeError, ValueError):
                self.warn("Skipped invalid input")
        return cleaned

    def resolve_params(self) -> dict[str, Any]:
        resolved: dict[str, Any] = super().resolve_params()
        # Empty, false, and zero values are explicit input, not requests for the
        # default. Keep them so validation rejects them before making requests.
        for param in self.params_schema:
            if param["name"] in self.params:
                resolved[param["name"]] = self.params[param["name"]]
        return resolved

    def numeric_param(
        self, name: str, default: str, minimum: float, maximum: float
    ) -> float:
        raw = self.params.get(name, default)
        try:
            result = float(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidEnricherParams(f"{name} must be a number") from exc
        if (
            isinstance(raw, bool)
            or not math.isfinite(result)
            or not minimum <= result <= maximum
        ):
            raise InvalidEnricherParams(
                f"{name} must be between {minimum} and {maximum}"
            )
        return result

    def warn(self, message: str) -> None:
        Logger.warn(self.sketch_id, {"message": f"[{self.name()}] {message}"})

    def info(self, message: str) -> None:
        Logger.info(self.sketch_id, {"message": f"[{self.name()}] {message}"})

    @classmethod
    def icon(cls) -> str:
        return "Plane"

    @classmethod
    def get_params_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "max_age_seconds",
                "type": "string",
                "description": "Maximum position age in seconds (1–3600); stale positions are skipped",
                "required": False,
                "default": "300",
            }
        ]

    def positions(self, payload: dict[str, Any], url: str) -> list[AircraftPosition]:
        max_age = self.numeric_param("max_age_seconds", "300", 1, 3600)
        records, provider_time = position_records(payload)
        retrieved_at = datetime.now(timezone.utc)
        observations: dict[str, AircraftPosition] = {}
        skipped = 0
        for raw in records:
            try:
                position = (
                    position_observation(raw, provider_time, retrieved_at, url, max_age)
                    if isinstance(raw, dict)
                    else None
                )
            except (ValidationError, ValueError, OverflowError):
                position = None
            if position is None:
                skipped += 1
            else:
                previous = observations.get(position.aircraft_hex)
                if previous is None or position.observed_at > previous.observed_at:
                    observations[position.aircraft_hex] = position
        if skipped:
            self.warn(f"Skipped {skipped} stale, missing or invalid position records")
        return list(observations.values())

    def store_position(
        self, position: AircraftPosition, original: Aircraft | None = None
    ) -> Aircraft:
        aircraft = aircraft_from_position(position)
        if original is not None:
            aircraft = original.model_copy(
                update=aircraft.model_dump(
                    exclude={"identifier", "nodeLabel"}, exclude_unset=True
                )
            )
        self.create_node(aircraft)
        self.create_node(position)
        self.create_relationship(aircraft, position, "HAS_POSITION_OBSERVATION")
        return aircraft
