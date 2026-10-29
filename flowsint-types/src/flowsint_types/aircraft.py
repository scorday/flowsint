"""Aircraft lookup identifiers and time-stamped ADS-B position observations."""

import re
from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .flowsint_base import FlowsintType
from .registry import flowsint_type


def normalize_aircraft_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Aircraft identifiers must be strings")
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,14}", value):
        raise ValueError("Use an aircraft registration or a six-digit ICAO hex code")
    return value


@flowsint_type
class Aircraft(FlowsintType):
    """Aircraft identified by registration or ICAO hex; details preserve that identity.

    Identifiers may be reassigned. Registry details are a retrieved snapshot,
    not proof of current operation or of a person's presence aboard.
    """

    identifier: str = Field(
        description="Registration (G-EUUU) or ICAO hex (400942)",
        title="Aircraft identifier",
        json_schema_extra={"primary": True},
    )
    registration: str | None = None
    icao_hex: str | None = Field(None, pattern=r"^[0-9A-F]{6}$")
    model: str | None = None
    icao_type: str | None = None
    manufacturer: str | None = None
    registered_owner: str | None = Field(
        None,
        description="Reported registered owner; may be a person or organization, not necessarily the operator",
    )
    registered_owner_country: str | None = None
    details_source: str | None = None
    details_source_url: str | None = None
    details_retrieved_at: AwareDatetime | None = None

    @field_validator("identifier", "registration", "icao_hex", mode="before")
    @classmethod
    def normalize_identifiers(cls, value: str | None) -> str | None:
        return normalize_aircraft_identifier(value) if value is not None else None

    @model_validator(mode="after")
    def label_identifier(self) -> Self:
        # Graph persistence matches by label, so it must not change with metadata.
        self.nodeLabel = self.identifier
        return self

    @classmethod
    def detect(cls, line: str) -> bool:
        # Bare hex and registration-like strings collide with unrelated entities.
        return False


@flowsint_type
class AircraftPosition(FlowsintType):
    """A provider's observed position of one aircraft at a specific UTC time."""

    observation_id: str = Field(
        description="Computed from provider, ICAO hex and position observation time",
        json_schema_extra={"primary": True},
    )
    aircraft_hex: str = Field(pattern=r"^[0-9A-F]{6}$")
    observed_at: AwareDatetime
    retrieved_at: AwareDatetime
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    altitude_baro_ft: float | None = Field(None, allow_inf_nan=False)
    altitude_geom_ft: float | None = Field(None, allow_inf_nan=False)
    ground_speed_knots: float | None = Field(None, ge=0, allow_inf_nan=False)
    track_degrees: float | None = Field(None, ge=0, lt=360, allow_inf_nan=False)
    on_ground: bool | None = None
    callsign: str | None = None
    registration: str | None = None
    icao_type: str | None = None
    source: Literal["ADSB.lol"] = "ADSB.lol"
    source_url: str

    @field_validator("aircraft_hex", mode="before")
    @classmethod
    def uppercase_hex(cls, value: str) -> str:
        return normalize_aircraft_identifier(value)

    @field_validator("registration", mode="before")
    @classmethod
    def normalize_registration(cls, value: str | None) -> str | None:
        return normalize_aircraft_identifier(value) if value is not None else None

    @model_validator(mode="after")
    def label_observation(self) -> Self:
        self.observed_at = self.observed_at.astimezone(timezone.utc)
        self.retrieved_at = self.retrieved_at.astimezone(timezone.utc)
        expected = self.make_id(self.aircraft_hex, self.observed_at)
        if self.observation_id != expected:
            raise ValueError("Observation ID must match aircraft and observation time")
        if self.observed_at > self.retrieved_at:
            raise ValueError("Position observation cannot follow retrieval time")
        self.nodeLabel = self.observation_id
        return self

    @staticmethod
    def make_id(aircraft_hex: str, observed_at: datetime) -> str:
        return f"ADSB.lol:{aircraft_hex.upper()}:{observed_at.astimezone(timezone.utc).isoformat()}"

    @classmethod
    def detect(cls, line: str) -> bool:
        return False


@flowsint_type
class Flight(FlowsintType):
    """An observed airborne segment inferred from an ADS-B trace.

    The endpoints are observations, not confirmed takeoff/landing locations or
    scheduled airports. Gaps and requested archive boundaries can split flights.
    """

    flight_id: str = Field(json_schema_extra={"primary": True})
    aircraft_hex: str = Field(pattern=r"^[0-9A-F]{6}$")
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    start_latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    start_longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    end_latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    end_longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    callsigns: list[str] = Field(default_factory=list)
    observation_count: int = Field(ge=2)
    stored_position_count: int = Field(
        ge=2,
        description="Positions selected in this run; earlier samples can remain in the graph",
    )
    gap_minutes: float = Field(default=30, ge=5, le=180, allow_inf_nan=False)
    start_boundary: Literal["archive_start", "ground", "provider_leg", "coverage_gap"]
    end_boundary: Literal["archive_end", "ground", "provider_leg", "coverage_gap"]
    source: Literal["ADSB.lol"] = "ADSB.lol"
    source_urls: list[str] = Field(min_length=1)
    retrieved_at: AwareDatetime

    @model_validator(mode="after")
    def label_segment(self) -> Self:
        if not self.first_seen_at < self.last_seen_at <= self.retrieved_at:
            raise ValueError(
                "Flight observation times must be ordered and not in the future"
            )
        if self.stored_position_count > self.observation_count:
            raise ValueError("Stored positions cannot exceed observed positions")
        self.first_seen_at = self.first_seen_at.astimezone(timezone.utc)
        self.last_seen_at = self.last_seen_at.astimezone(timezone.utc)
        self.retrieved_at = self.retrieved_at.astimezone(timezone.utc)
        if self.flight_id != self.make_id(
            self.aircraft_hex, self.first_seen_at, self.gap_minutes
        ):
            raise ValueError("Flight ID must match aircraft and first observation time")
        self.nodeLabel = self.flight_id
        return self

    @staticmethod
    def make_id(
        aircraft_hex: str, first_seen_at: datetime, gap_minutes: float = 30
    ) -> str:
        return f"ADSB.lol:flight:{aircraft_hex}:{first_seen_at.astimezone(timezone.utc).isoformat()}:gap{gap_minutes:g}"

    @classmethod
    def detect(cls, line: str) -> bool:
        return False
