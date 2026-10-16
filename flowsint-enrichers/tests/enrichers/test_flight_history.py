import gzip
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.graph import GraphService
from flowsint_enrichers import ENRICHER_REGISTRY
from flowsint_enrichers.aircraft import to_flights
from flowsint_enrichers.aircraft.to_flights import AircraftToFlightsEnricher
from flowsint_enrichers.aviation import _base, _client
from flowsint_enrichers.aviation._client import (
    AviationProviderError,
    PublicAviationClient,
)
from flowsint_enrichers.aviation._history import (
    observed_flights,
    parse_trace,
    trace_url,
)
from flowsint_types import Aircraft

DAY = date(2025, 5, 18)
ORIGIN = datetime(2025, 5, 18, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    _client._gates.clear()
    logger = MagicMock()
    monkeypatch.setattr(_base, "Logger", logger)
    monkeypatch.setattr("flowsint_core.core.enricher_base.Logger", logger)
    yield logger
    _client._gates.clear()


@pytest.fixture
def mock_history(monkeypatch):
    requests = []
    original_client = httpx.AsyncClient

    def install(handler):
        def dispatch(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            to_flights,
            "aviation_http_client",
            lambda: original_client(
                transport=httpx.MockTransport(dispatch),
                timeout=15,
            ),
        )
        return requests

    return install


def job(**params):
    return AircraftToFlightsEnricher(
        graph_service=MagicMock(),
        params={
            "start_date": str(DAY),
            "end_date": str(DAY),
            **params,
        },
    )


def row(seconds, altitude=10000, flags=0, callsign=None):
    return [
        seconds,
        0,
        0,
        altitude,
        200,
        90,
        flags,
        0,
        {"flight": callsign} if callsign else None,
        "adsb_icao",
        11000,
    ]


def archive(rows=None, day=DAY, hex_id="405455"):
    if rows is None:
        rows = [
            row(0, "ground"),
            row(60, callsign="TEST123 "),
            row(120),
            row(180, "ground"),
        ]
    return {
        "icao": hex_id.lower(),
        "r": "G-OLD",
        "t": "A320",
        "timestamp": datetime.combine(
            day, datetime.min.time(), timezone.utc
        ).timestamp(),
        "trace": rows,
    }


def parse(payload=None, day=DAY):
    return parse_trace(
        payload or archive(),
        "405455",
        day,
        trace_url("405455", day),
        datetime.now(timezone.utc),
    )


def test_catalog_exposes_history_for_aircraft_without_key():
    item = next(
        item
        for item in ENRICHER_REGISTRY.list_by_input_type("Aircraft")
        if item["name"] == "aircraft_to_flights"
    )
    assert item["outputs"]["type"] == "Flight"
    assert item["api_key_requirement"] == "not_required"
    assert {p["name"] for p in item["params_schema"]} == {
        "start_date",
        "end_date",
        "gap_minutes",
        "max_flights",
        "positions_per_flight",
    }


def test_trace_mapping_and_ground_boundaries():
    points, skipped = parse()
    [segment] = observed_flights(points, 1800, 20)
    assert skipped == 0
    assert segment.flight.start_boundary == segment.flight.end_boundary == "ground"
    assert segment.flight.first_seen_at == ORIGIN
    assert segment.flight.last_seen_at == ORIGIN + timedelta(seconds=180)
    assert segment.flight.callsigns == ["TEST123"]
    assert segment.flight.observation_count == 4
    assert segment.positions[0].track_degrees is None  # Ground heading is not track.
    assert segment.positions[1].altitude_baro_ft == 10000
    assert segment.positions[1].altitude_geom_ft == 11000
    assert segment.positions[2].callsign is None  # No invented callsign propagation.


def test_leg_marker_on_stale_point_is_preserved():
    points, skipped = parse(
        archive([row(0), row(60), row(120, flags=3), row(180), row(240)])
    )
    segments = observed_flights(points, 1800, 20)
    assert len(segments) == 2
    assert skipped == 1
    assert segments[0].flight.end_boundary == "provider_leg"
    assert segments[1].flight.start_boundary == "provider_leg"


def test_gaps_split_segments_and_sampling_keeps_endpoints():
    rows = [row(i * 60) for i in range(10)] + [row(5000), row(5060)]
    points, _ = parse(archive(rows))
    first, second = observed_flights(points, 1800, 3)
    assert first.flight.end_boundary == "coverage_gap"
    assert second.flight.start_boundary == "coverage_gap"
    assert first.flight.observation_count == 10
    assert len(first.positions) == 3
    assert first.positions[0].observed_at == ORIGIN
    assert first.positions[-1].observed_at == ORIGIN + timedelta(seconds=540)


def test_cross_midnight_flight_is_merged_and_duplicate_points_are_deduped():
    first, _ = parse(archive([row(86300), row(86360)]))
    next_day = DAY + timedelta(days=1)
    second, _ = parse(archive([row(20), row(80)], day=next_day), day=next_day)
    [segment] = observed_flights(first + second + first, 1800, 20)
    assert segment.flight.observation_count == 4
    assert len(segment.flight.source_urls) == 2


@pytest.mark.parametrize(
    "rows",
    [
        [row(0, "ground"), row(60, "ground")],
        [row(0)],
        [row(0, "ground"), row(1), row(2, "ground")],
        [row(0, None), row(60, None)],
    ],
)
def test_ground_only_singletons_and_unknown_altitudes_are_not_flights(rows):
    points, _ = parse(archive(rows))
    assert observed_flights(points, 1800, 20) == []


def test_bad_points_are_skipped_without_losing_good_points():
    bad = row(40)
    bad[1] = True
    points, skipped = parse(
        archive([row(0), [], "broken", row(-1), bad, row(60), row(86401)])
    )
    assert skipped == 4
    assert len(points) == 2
    assert len(observed_flights(points, 1800, 20)) == 1


def test_geometric_altitude_is_not_stored_as_barometric():
    points, _ = parse(archive([row(0, flags=8), row(60, flags=8)]))
    assert points[0].position.altitude_baro_ft is None
    assert points[0].position.altitude_geom_ft == 10000


def test_mismatched_or_invalid_trace_envelopes_are_rejected():
    for payload in (
        archive(hex_id="FFFFFF"),
        {"icao": "405455", "timestamp": 0},
        archive() | {"timestamp": float("inf")},
    ):
        with pytest.raises(AviationProviderError):
            parse(payload)


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "wrong"},
        {"end_date": "2025-02-30"},
        {"start_date": "2025-06-01"},
        {"start_date": "2025-01-01"},
        {"end_date": "2999-01-01"},
        {"gap_minutes": "4"},
        {"positions_per_flight": "1"},
        {"max_flights": "1.5"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_params_fail_before_network(params, mock_history):
    requests = mock_history(lambda request: pytest.fail("Unexpected request"))
    with pytest.raises(InvalidEnricherParams):
        await job(**params).scan([Aircraft(identifier="405455")])
    assert not requests


def test_blank_ui_dates_use_seven_completed_utc_days():
    dates = job(start_date="", end_date="").date_range()
    assert len(dates) == 7
    assert dates[-1] == datetime.now(timezone.utc).date() - timedelta(days=1)
    assert dates[0] == dates[-1] - timedelta(days=6)


@pytest.mark.asyncio
async def test_history_execute_reads_gzip_and_preserves_graph_metadata(mock_history):
    requests = mock_history(
        lambda request: httpx.Response(
            200, content=gzip.compress(json.dumps(archive()).encode())
        )
    )
    repository = MagicMock()
    instance = job(positions_per_flight="2")
    instance._graph_service = GraphService(sketch_id="s", repository=repository)
    [flight] = await instance.execute(["405455"])
    assert str(requests[0].url) == trace_url("405455", DAY)
    assert flight.stored_position_count == 2
    nodes = [c.kwargs["node_obj"] for c in repository.create_node.call_args_list]
    aircraft = next(n for n in nodes if n["nodeType"] == "aircraft")
    assert (
        "nodeProperties.registration" not in aircraft
    )  # Historical r=G-OLD stays on positions.
    position = next(n for n in nodes if n["nodeType"] == "aircraftposition")
    assert position["nodeProperties.registration"] == "G-OLD"
    assert isinstance(position["nodeProperties.observed_at"], str)
    assert "HAS_OBSERVED_FLIGHT" in {
        c.kwargs["rel_obj"]["rel_label"]
        for c in repository.create_relationship.call_args_list
    }


@pytest.mark.asyncio
async def test_registration_resolves_once_and_aliases_share_history(mock_history):
    def handler(request):
        if request.url.host == "api.adsbdb.com":
            return httpx.Response(
                200,
                json={
                    "response": {
                        "aircraft": {"mode_s": "405455", "registration": "G-EUUU"}
                    }
                },
            )
        return httpx.Response(200, json=archive())

    requests = mock_history(handler)
    instance = job()
    results = await instance.execute(["G-EUUU", "405455"])
    assert len(results) == 1
    assert len(requests) == 2
    edge = instance.graph_service.create_relationship.call_args.kwargs
    assert edge["rel_label"] == "RESOLVES_TO_AIRCRAFT"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 500, 429])
async def test_missing_or_failed_day_preserves_other_day_results(status, mock_history):
    def handler(request):
        if "/2025/05/19/" in request.url.path:
            return httpx.Response(200, json=archive(day=DAY + timedelta(days=1)))
        return httpx.Response(status, headers={"Retry-After": "30"})

    requests = mock_history(handler)
    instance = job(end_date="2025-05-19")
    [flight] = await instance.execute(["405455"])
    assert flight.first_seen_at.date() == date(2025, 5, 19)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_flight_limit_keeps_newest_segments(mock_history):
    mock_history(
        lambda request: httpx.Response(
            200,
            json=archive(
                [
                    row(0),
                    row(60),
                    row(120, flags=2),
                    row(180),
                ]
            ),
        )
    )
    [flight] = await job(max_flights="1").execute(["405455"])
    assert flight.first_seen_at == ORIGIN + timedelta(seconds=120)


@pytest.mark.asyncio
async def test_point_processing_cap_is_explicit_and_keeps_newest_points(
    mock_history, monkeypatch, environment
):
    monkeypatch.setattr(to_flights, "MAX_HISTORY_POINTS", 3)
    mock_history(
        lambda request: httpx.Response(
            200, json=archive([row(i * 60) for i in range(5)])
        )
    )
    [flight] = await job().execute(["405455"])
    assert flight.first_seen_at == ORIGIN + timedelta(seconds=120)
    assert flight.observation_count == 3
    assert any("processing limit" in str(c) for c in environment.warn.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["header", "raw"])
async def test_http_adapter_handles_gzipped_archives(encoding):
    compressed = gzip.compress(json.dumps(archive()).encode())
    headers = {"Content-Encoding": "gzip"} if encoding == "header" else {}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=compressed, headers=headers)
        )
    ) as http:
        payload = await PublicAviationClient(http).get(trace_url("405455", DAY))
    assert payload["icao"] == "405455"


@pytest.mark.asyncio
async def test_bounded_http_read_rejects_oversized_payload(monkeypatch):
    monkeypatch.setattr(_client, "MAX_RESPONSE_BYTES", 100)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 101)
        )
    ) as http:
        with pytest.raises(AviationProviderError, match="size limit"):
            await PublicAviationClient(http).get(trace_url("405455", DAY))


def test_bounded_gzip_inflation_and_corrupt_gzip_are_rejected(monkeypatch):
    monkeypatch.setattr(_client, "MAX_JSON_BYTES", 100)
    with pytest.raises(AviationProviderError, match="size limit"):
        _client._decode_json(gzip.compress(b"x" * 101))
    with pytest.raises(AviationProviderError, match="invalid"):
        _client._decode_json(b"\x1f\x8b corrupt")
