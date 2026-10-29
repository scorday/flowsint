from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from flowsint_types import (
    Aircraft,
    AircraftPosition,
    Flight,
    deserialize_pydantic_from_transport,
    get_type,
    serialize_pydantic_for_transport,
)


def test_aircraft_normalizes_lookup_and_keeps_label_when_details_change():
    aircraft = Aircraft(identifier=" g-euuu ")
    assert aircraft.identifier == aircraft.nodeLabel == "G-EUUU"
    resolved = Aircraft(identifier="400942", registration="g-euuu", model="Airbus")
    assert resolved.nodeLabel == "400942"
    assert resolved.registration == "G-EUUU"
    assert Aircraft(identifier="ab12ef", icao_hex="ab12ef").icao_hex == "AB12EF"


@pytest.mark.parametrize(
    "identifier", ["", "../random", "A/B", " N 123 ", "A", "a?x=1"]
)
def test_aircraft_rejects_invalid_identifiers(identifier):
    with pytest.raises(ValidationError):
        Aircraft(identifier=identifier)


def test_aircraft_does_not_autodetect_unrelated_hex_or_names():
    assert not Aircraft.detect("400942")
    assert not Aircraft.detect("G-EUUU")


def test_observations_have_distinct_stable_labels_and_transport_roundtrips():
    now = datetime.now(timezone.utc)
    observations = [
        AircraftPosition(
            observation_id=AircraftPosition.make_id(
                "400942", now - timedelta(seconds=age)
            ),
            aircraft_hex="400942",
            observed_at=now - timedelta(seconds=age),
            retrieved_at=now,
            latitude=0,
            longitude=0,
            source_url="https://api.adsb.lol/v2/hex/400942",
        )
        for age in (1, 2)
    ]
    assert observations[0].nodeLabel != observations[1].nodeLabel
    for model in [Aircraft(identifier="400942"), *observations]:
        name = type(model).__name__.lower()
        assert get_type(name) is type(model)
        assert (
            deserialize_pydantic_from_transport(
                serialize_pydantic_for_transport(model), name
            )
            == model
        )


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": 91},
        {"longitude": float("nan")},
        {"ground_speed_knots": -1},
        {"track_degrees": 360},
        {"observation_id": "wrong"},
        {"aircraft_hex": "~400942"},
        {"observed_at": "2026-01-01T00:00:00"},
    ],
)
def test_position_rejects_invalid_data(change):
    now = datetime.now(timezone.utc)
    values = dict(
        observation_id=AircraftPosition.make_id("400942", now),
        aircraft_hex="400942",
        observed_at=now,
        retrieved_at=now,
        latitude=0,
        longitude=0,
        source_url="https://api.adsb.lol/v2/hex/400942",
    )
    with pytest.raises(ValidationError):
        AircraftPosition(**(values | change))


def flight_values():
    start = datetime(2025, 5, 18, 12, tzinfo=timezone.utc)
    return dict(
        flight_id=Flight.make_id("405455", start),
        aircraft_hex="405455",
        first_seen_at=start,
        last_seen_at=start + timedelta(hours=1),
        retrieved_at=start + timedelta(days=1),
        start_latitude=0,
        start_longitude=0,
        end_latitude=1,
        end_longitude=1,
        observation_count=100,
        stored_position_count=20,
        start_boundary="archive_start",
        end_boundary="ground",
        source_urls=[
            "https://adsb.lol/globe_history/2025/05/18/traces/55/trace_full_405455.json"
        ],
    )


def test_flight_type_and_transport_roundtrip():
    flight = Flight(**flight_values())
    assert get_type("flight") is Flight
    assert flight.nodeLabel == flight.flight_id
    assert (
        deserialize_pydantic_from_transport(
            serialize_pydantic_for_transport(flight), "flight"
        )
        == flight
    )
    assert "takeoff" not in Flight.model_fields
    assert "arrival_airport" not in Flight.model_fields


@pytest.mark.parametrize(
    "change",
    [
        {"observation_count": 1},
        {"stored_position_count": 101},
        {"flight_id": "arbitrary"},
        {"start_latitude": 91},
        {"last_seen_at": datetime(2025, 5, 18, 11, tzinfo=timezone.utc)},
        {"source_urls": []},
        {"aircraft_hex": "~405455"},
        {"gap_minutes": 4},
    ],
)
def test_flight_rejects_invalid_or_inconsistent_data(change):
    with pytest.raises(ValidationError):
        Flight(**(flight_values() | change))
