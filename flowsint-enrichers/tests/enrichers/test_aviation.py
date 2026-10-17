import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from flowsint_core.core.enricher_base import InvalidEnricherParams
from flowsint_core.core.graph import GraphService
from flowsint_core.core.services.type_registry_service import TypeRegistryService
from flowsint_enrichers import ENRICHER_REGISTRY
from flowsint_enrichers.aircraft.to_details import AircraftToDetailsEnricher
from flowsint_enrichers.aircraft.to_position import AircraftToPositionEnricher
from flowsint_enrichers.aviation import _base, _client
from flowsint_enrichers.aviation._client import (
    AviationProviderError,
    AviationRateLimited,
    PublicAviationClient,
)
from flowsint_enrichers.aviation._mapping import position_records
from flowsint_enrichers.location.to_aircraft import LocationToAircraftEnricher
from flowsint_types import Aircraft, Location

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def aviation_environment(monkeypatch):
    _client._gates.clear()
    logger = MagicMock()
    monkeypatch.setattr(_base, "Logger", logger)
    monkeypatch.setattr("flowsint_core.core.enricher_base.Logger", logger)
    yield
    _client._gates.clear()


@pytest.fixture
def mock_api(monkeypatch):
    requests = []
    original_client = httpx.AsyncClient

    def install(handler):
        def dispatch(request):
            requests.append(request)
            return handler(request)

        def factory():
            return original_client(transport=httpx.MockTransport(dispatch), timeout=15)

        for module in (
            "flowsint_enrichers.aircraft.to_details",
            "flowsint_enrichers.aircraft.to_position",
            "flowsint_enrichers.location.to_aircraft",
        ):
            monkeypatch.setattr(f"{module}.aviation_http_client", factory)
        return requests

    return install


def registry_record(hex="400942", registration="G-EUUU"):
    return {
        "response": {
            "aircraft": {
                "mode_s": hex,
                "registration": registration,
                "type": "A320",
                "manufacturer": "Airbus",
                "icao_type": "A320",
                "registered_owner": "Example Registered Owner",
                "registered_owner_country_name": "United Kingdom",
            }
        }
    }


def record(**kwargs):
    return (
        dict(
            hex="400942",
            r="G-EUUU",
            lat=0,
            lon=0,
            seen_pos=1,
            flight="TEST123 ",
            alt_baro=10000,
            gs=200,
            track=90,
        )
        | kwargs
    )


def envelope(*records, age=0):
    return {
        "now": int((NOW.timestamp() - age) * 1000),
        "msg": "No error",
        "ac": list(records),
    }


def enricher(cls, **kwargs):
    return cls(sketch_id="s", scan_id="t", graph_service=MagicMock(), **kwargs)


def location(address="Area", lat=0, lon=0):
    return Location(
        address=address, city="", country="", zip="", latitude=lat, longitude=lon
    )


def test_discovery_catalog_and_type_menu():
    for name, input_type, output_type in [
        ("aircraft_to_details", "Aircraft", "Aircraft"),
        ("aircraft_to_position", "Aircraft", "AircraftPosition"),
        ("location_to_aircraft", "Location", "Aircraft"),
    ]:
        item = next(
            item
            for item in ENRICHER_REGISTRY.list_by_input_type(input_type)
            if item["name"] == name
        )
        assert item["inputs"]["type"] == input_type
        assert item["outputs"]["type"] == output_type
        assert item["api_key_requirement"] == "not_required"
    service = TypeRegistryService(db=MagicMock(), custom_type_repo=MagicMock())
    service._custom_type_repo.get_by_owner.return_value = []
    types = service.get_types_list("user")
    aviation = next(group for group in types if group["key"] == "aviation")
    assert {item["type"] for item in aviation["children"]} == {
        "Aircraft",
        "AircraftPosition",
        "Flight",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["g-euuu", "400942"])
async def test_details_execute_enriches_original_node_and_preserves_provenance(
    mock_api, identifier
):
    requests = mock_api(lambda request: httpx.Response(200, json=registry_record()))
    job = enricher(AircraftToDetailsEnricher)
    original = Aircraft(identifier=identifier, model="Old model", notes="Keep my notes")
    [result] = await job.execute([original])
    assert result.identifier == result.nodeLabel == original.identifier
    assert result.icao_hex == "400942"
    assert result.registration == "G-EUUU"
    assert result.model == "A320"
    assert result.notes == "Keep my notes"
    assert result.registered_owner == "Example Registered Owner"
    assert result.details_source == "adsbdb"
    assert result.details_retrieved_at.tzinfo is not None
    assert result.details_source_url == str(requests[0].url)
    assert requests[0].url.path == f"/v0/aircraft/{original.identifier}"
    job.graph_service.create_relationship.assert_not_called()
    job.graph_service.create_node_from_flowsint_type.assert_called_once_with(
        node_obj=result
    )


@pytest.mark.asyncio
async def test_details_partial_failure_does_not_misassociate_results(mock_api):
    def handler(request):
        if request.url.path.endswith("G-FAIL"):
            return httpx.Response(404)
        return httpx.Response(200, json=registry_record())

    mock_api(handler)
    job = enricher(AircraftToDetailsEnricher)
    inputs = [Aircraft(identifier="G-FAIL"), Aircraft(identifier="G-EUUU")]
    results = await job.scan(inputs)
    job.postprocess(results, inputs)
    assert len(results) == 1
    assert results[0].identifier == "G-EUUU"
    job.graph_service.create_relationship.assert_not_called()
    job.graph_service.create_node_from_flowsint_type.assert_called_once_with(
        node_obj=results[0]
    )


@pytest.mark.asyncio
async def test_details_enriches_each_input_identity_for_same_aircraft(mock_api):
    mock_api(lambda request: httpx.Response(200, json=registry_record()))
    job = enricher(AircraftToDetailsEnricher)
    results = await job.execute(["G-EUUU", "400942"])
    assert {result.identifier for result in results} == {"G-EUUU", "400942"}
    assert all(result.icao_hex == "400942" for result in results)
    assert job.graph_service.create_node_from_flowsint_type.call_count == 2
    job.graph_service.create_relationship.assert_not_called()


@pytest.mark.asyncio
async def test_details_repeated_lookup_keeps_original_graph_identity(mock_api):
    mock_api(lambda request: httpx.Response(200, json=registry_record()))
    repository = MagicMock()
    graph = GraphService(sketch_id="s", repository=repository)
    original = Aircraft(identifier="G-EUUU", notes="Keep my notes")
    graph.create_node_from_flowsint_type(original)
    job = AircraftToDetailsEnricher(sketch_id="s", graph_service=graph)
    [result] = await job.execute([original])
    await job.execute([result])
    nodes = [call.kwargs["node_obj"] for call in repository.create_node.call_args_list]
    assert len(nodes) == 3
    assert {node["nodeType"] for node in nodes} == {"aircraft"}
    assert {node["nodeLabel"] for node in nodes} == {"G-EUUU"}
    assert nodes[-1]["nodeProperties.icao_hex"] == "400942"
    assert nodes[-1]["nodeProperties.notes"] == "Keep my notes"
    repository.create_relationship.assert_not_called()


@pytest.mark.asyncio
async def test_mismatched_registry_result_is_rejected(mock_api):
    mock_api(lambda request: httpx.Response(200, json=registry_record()))
    assert (
        await enricher(AircraftToDetailsEnricher).scan([Aircraft(identifier="FFFFFF")])
        == []
    )


@pytest.mark.asyncio
async def test_position_execute_preserves_zero_coordinates_units_and_time(mock_api):
    requests = mock_api(lambda request: httpx.Response(200, json=envelope(record())))
    job = enricher(AircraftToPositionEnricher)
    [position] = await job.execute(["400942"])
    assert requests[0].url.path == "/v2/hex/400942"
    assert (position.latitude, position.longitude) == (0, 0)
    assert position.altitude_baro_ft == 10000
    assert position.ground_speed_knots == 200
    assert position.callsign == "TEST123"
    assert position.source == "ADSB.lol"
    assert position.source_url == str(requests[0].url)
    assert abs((NOW - position.observed_at).total_seconds() - 1) < 0.01
    assert (
        job.graph_service.create_relationship.call_args.kwargs["rel_label"]
        == "HAS_POSITION_OBSERVATION"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["g-euuu", "400942"])
async def test_position_links_original_aircraft_and_preserves_metadata(
    mock_api, identifier
):
    requests = mock_api(lambda request: httpx.Response(200, json=envelope(record())))
    repository = MagicMock()
    graph = GraphService(sketch_id="s", repository=repository)
    original = Aircraft(
        identifier=identifier,
        model="Airbus A320",
        registered_owner="Known owner",
        notes="Keep my notes",
    )
    graph.create_node_from_flowsint_type(original)
    job = AircraftToPositionEnricher(graph_service=graph)
    [position] = await job.execute([original])
    await job.execute([original])
    endpoint = "hex" if identifier == "400942" else "reg"
    assert requests[0].url.path == f"/v2/{endpoint}/{original.identifier}"
    assert position.aircraft_hex == "400942"
    aircraft_nodes = [
        call.kwargs["node_obj"]
        for call in repository.create_node.call_args_list
        if call.kwargs["node_obj"]["nodeType"] == "aircraft"
    ]
    assert len(aircraft_nodes) == 3
    assert {node["nodeLabel"] for node in aircraft_nodes} == {original.identifier}
    assert aircraft_nodes[-1]["nodeProperties.icao_hex"] == "400942"
    assert aircraft_nodes[-1]["nodeProperties.model"] == "Airbus A320"
    assert aircraft_nodes[-1]["nodeProperties.registered_owner"] == "Known owner"
    assert aircraft_nodes[-1]["nodeProperties.notes"] == "Keep my notes"
    edges = [
        call.kwargs["rel_obj"] for call in repository.create_relationship.call_args_list
    ]
    assert len(edges) == 2
    assert all(edge["rel_label"] == "HAS_POSITION_OBSERVATION" for edge in edges)
    assert all(edge["from_label"] == original.identifier for edge in edges)
    assert all(edge["to_label"] == position.observation_id for edge in edges)


@pytest.mark.asyncio
async def test_position_links_both_input_identifiers_to_shared_observation(mock_api):
    mock_api(lambda request: httpx.Response(200, json=envelope(record())))
    job = enricher(AircraftToPositionEnricher)
    [position] = await job.execute(["G-EUUU", "400942"])
    edges = [
        call.kwargs for call in job.graph_service.create_relationship.call_args_list
    ]
    assert {edge["from_obj"].identifier for edge in edges} == {"G-EUUU", "400942"}
    assert all(edge["rel_label"] == "HAS_POSITION_OBSERVATION" for edge in edges)
    assert all(edge["to_obj"] == position for edge in edges)


@pytest.mark.asyncio
async def test_position_partial_failure_does_not_link_unmatched_input(mock_api):
    mock_api(lambda request: httpx.Response(200, json=envelope(record())))
    job = enricher(AircraftToPositionEnricher)
    [position] = await job.execute(["G-FAIL", "G-EUUU"])
    job.graph_service.create_relationship.assert_called_once()
    edge = job.graph_service.create_relationship.call_args.kwargs
    assert edge["from_obj"].identifier == "G-EUUU"
    assert edge["to_obj"] == position
    aircraft_nodes = [
        call.kwargs["node_obj"]
        for call in job.graph_service.create_node_from_flowsint_type.call_args_list
        if isinstance(call.kwargs["node_obj"], Aircraft)
    ]
    assert [aircraft.identifier for aircraft in aircraft_nodes] == ["G-EUUU"]


@pytest.mark.asyncio
async def test_stale_and_malformed_records_are_skipped_individually(mock_api):
    mock_api(
        lambda request: httpx.Response(
            200,
            json=envelope(
                record(seen_pos=900),
                record(seen_pos=None),
                record(lat=None),
                record(lat=91),
                record(hex="~400942"),
                record(r="malformed registration"),
                "invalid",
                record(),
                record(),
                record(seen_pos=-1),
                record(seen_pos=1e99),
            ),
        )
    )
    [position] = await enricher(AircraftToPositionEnricher).execute(["400942"])
    assert position.aircraft_hex == "400942"


@pytest.mark.asyncio
async def test_old_response_is_stale_even_with_recent_seen_pos(mock_api):
    mock_api(lambda request: httpx.Response(200, json=envelope(record(), age=1000)))
    job = enricher(AircraftToPositionEnricher)
    assert await job.execute(["400942"]) == []
    job.graph_service.create_node_from_flowsint_type.assert_not_called()


@pytest.mark.asyncio
async def test_ground_altitude_is_not_fabricated_as_zero(mock_api):
    mock_api(
        lambda request: httpx.Response(
            200, json=envelope(record(alt_baro="ground", gs=0))
        )
    )
    [position] = await enricher(AircraftToPositionEnricher).execute(["400942"])
    assert position.on_ground is True
    assert position.altitude_baro_ft is None
    assert position.ground_speed_knots == 0


@pytest.mark.asyncio
async def test_area_results_keep_both_locations_and_nearest_limit(mock_api):
    requests = mock_api(
        lambda request: httpx.Response(
            200,
            json=envelope(
                record(hex="FFFFFF", lon=0.2),
                record(hex="400942", lon=0.01),
                record(hex="AAAAAA", lon=10),
            ),
        )
    )
    job = enricher(
        LocationToAircraftEnricher, params={"radius_nm": "25", "max_results": "1"}
    )
    results = await job.execute([location("A"), location("B")])
    assert [a.identifier for a in results] == ["400942"]
    assert len(requests) == 2
    assert requests[0].url.path == "/v2/point/0.0/0.0/25.0"
    edges = [c.kwargs for c in job.graph_service.create_relationship.call_args_list]
    nearby = [e for e in edges if e["rel_label"] == "HAS_NEARBY_AIRCRAFT_OBSERVATION"]
    assert {e["from_obj"].address for e in nearby} == {"A", "B"}
    assert len({e["to_obj"].observation_id for e in nearby}) == 1


@pytest.mark.asyncio
async def test_invalid_inputs_and_coordinates_never_reach_provider(mock_api):
    requests = mock_api(lambda request: pytest.fail("Unexpected HTTP request"))
    assert await enricher(AircraftToDetailsEnricher).execute(["../../random", {}]) == []
    assert (
        await enricher(LocationToAircraftEnricher).execute(
            [
                location(lat=None),
                location(lat=91),
                location(lon=float("nan")),
            ]
        )
        == []
    )
    assert not requests


@pytest.mark.asyncio
async def test_bad_input_does_not_prevent_other_inputs_from_running(mock_api):
    requests = mock_api(lambda request: httpx.Response(200, json=registry_record()))
    results = await enricher(AircraftToDetailsEnricher).execute(
        [{"identifier": 123}, "400942"]
    )
    assert len(results) == len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", False, 0])
async def test_explicit_falsey_params_are_not_replaced_with_defaults(value, mock_api):
    requests = mock_api(lambda request: pytest.fail("Unexpected HTTP request"))
    job = enricher(LocationToAircraftEnricher, params={"radius_nm": value})
    assert await job.execute([location()]) == []
    assert not requests


@pytest.mark.asyncio
async def test_position_without_optional_metadata_still_creates_aircraft(mock_api):
    mock_api(
        lambda request: httpx.Response(
            200,
            json=envelope(
                {
                    "hex": "400942",
                    "lat": 0,
                    "lon": 0,
                    "seen_pos": 1,
                }
            ),
        )
    )
    job = enricher(LocationToAircraftEnricher)
    [aircraft] = await job.execute([location()])
    assert aircraft.identifier == "400942"
    assert aircraft.registration is None
    assert job._observations[0][1].on_ground is None


@pytest.mark.asyncio
async def test_area_uses_latest_position_per_aircraft_before_radius_filter(mock_api):
    mock_api(
        lambda request: httpx.Response(
            200,
            json=envelope(
                record(lon=0, seen_pos=120),
                record(lon=5, seen_pos=1),
            ),
        )
    )
    job = enricher(LocationToAircraftEnricher)
    assert await job.execute([location()]) == []


@pytest.mark.asyncio
async def test_missing_registry_fields_are_explicit_unknown_in_latest_snapshot(
    mock_api,
):
    mock_api(
        lambda request: httpx.Response(
            200,
            json={
                "response": {"aircraft": {"mode_s": "400942"}},
            },
        )
    )
    [aircraft] = await enricher(AircraftToDetailsEnricher).execute(["400942"])
    fields = aircraft.model_dump(exclude_unset=True)
    assert "registered_owner" in fields
    assert fields["registered_owner"] is None


@pytest.mark.asyncio
async def test_requests_share_provider_pacing_across_client_instances():
    timestamps = []

    def handler(request):
        timestamps.append(asyncio.get_running_loop().time())
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await asyncio.gather(
            *[
                PublicAviationClient(http).get("https://api.adsb.lol/v2/hex/400942")
                for _ in range(2)
            ]
        )
    assert len(timestamps) == 2
    assert timestamps[1] - timestamps[0] >= 0.99


def test_rate_limit_survives_separate_celery_style_event_loops():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    async def run_job():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AviationRateLimited):
                await PublicAviationClient(http).get(
                    "https://api.adsb.lol/v2/hex/400942"
                )

    asyncio.run(run_job())
    asyncio.run(run_job())
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"radius_nm": "251"},
        {"radius_nm": "0"},
        {"radius_nm": "nan"},
        {"max_results": "1.5"},
        {"max_results": "501"},
        {"max_age_seconds": "0"},
        {"max_age_seconds": "bad"},
    ],
)
async def test_invalid_parameters_fail_before_http(params, mock_api):
    mock_api(lambda request: pytest.fail("Unexpected HTTP request"))
    with pytest.raises(InvalidEnricherParams):
        await enricher(LocationToAircraftEnricher, params=params).scan([location()])


@pytest.mark.asyncio
async def test_rate_limit_preserves_success_and_stops_remaining_inputs(mock_api):
    def handler(request):
        return (
            httpx.Response(200, json=registry_record())
            if request.url.path.endswith("G-EUUU")
            else httpx.Response(429, headers={"Retry-After": "120"})
        )

    requests = mock_api(handler)
    job = enricher(AircraftToDetailsEnricher)
    results = await job.execute(["G-EUUU", "G-NEXT", "G-LAST"])
    assert len(results) == 1
    assert len(requests) == 2
    assert await enricher(AircraftToDetailsEnricher).execute(["G-NEXT"]) == []
    assert len(requests) == 2  # Shared provider cooldown, no new request.


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "500", "json", "envelope"])
async def test_provider_errors_are_handled_without_graph_changes(kind, mock_api):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private response detail", request=request)
        if kind == "500":
            return httpx.Response(500, text="private response detail")
        if kind == "json":
            return httpx.Response(200, text="not JSON")
        return httpx.Response(200, json={"response": "bad"})

    mock_api(handler)
    job = enricher(AircraftToDetailsEnricher)
    assert await job.execute(["400942"]) == []
    job.graph_service.create_node_from_flowsint_type.assert_not_called()


def test_seconds_and_milliseconds_envelopes():
    _, ms = position_records(envelope())
    _, seconds = position_records(dict(envelope(), now=NOW.timestamp()))
    assert abs((seconds - ms).total_seconds()) < 0.001
    with pytest.raises(AviationProviderError):
        position_records({"now": 1, "ac": [], "msg": "provider error"})


@pytest.mark.asyncio
async def test_retry_after_http_date_and_safe_error_messages():
    from email.utils import format_datetime

    retry = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=90), usegmt=True
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429, headers={"Retry-After": retry}, text="secret body"
            )
        )
    ) as http:
        with pytest.raises(AviationRateLimited) as error:
            await PublicAviationClient(http).get("https://api.adsb.lol/v2/hex/400942")
        assert "secret body" not in str(error.value)
        assert (
            85
            < _client._gate_for("api.adsb.lol").cooldown_until
            - asyncio.get_running_loop().time()
            <= 90
        )


def test_graph_serialization_preserves_details_and_distinct_observations():
    repository = MagicMock()
    graph = GraphService(sketch_id="s", repository=repository)
    job = AircraftToPositionEnricher(graph_service=graph)
    positions = job.positions(envelope(record()), "https://api.adsb.lol/v2/hex/400942")
    positions += job.positions(
        envelope(record(seen_pos=2)), "https://api.adsb.lol/v2/hex/400942"
    )
    job.postprocess(positions, [Aircraft(identifier="400942")])
    nodes = [call.kwargs["node_obj"] for call in repository.create_node.call_args_list]
    aircraft_nodes = [n for n in nodes if n["nodeType"] == "aircraft"]
    observation_nodes = [n for n in nodes if n["nodeType"] == "aircraftposition"]
    assert len({n["nodeLabel"] for n in observation_nodes}) == 2
    assert all("nodeProperties.registered_owner" not in n for n in aircraft_nodes)
    assert all(n["nodeProperties.source"] == "ADSB.lol" for n in observation_nodes)
    assert all(
        isinstance(n["nodeProperties.observed_at"], str) for n in observation_nodes
    )
