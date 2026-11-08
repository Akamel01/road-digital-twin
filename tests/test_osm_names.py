import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from shapely.geometry import LineString, box, mapping

from twin import osm_names
from twin.osm_names import fetch_streets, name_facility, osm_names_meta, to_utm

FIXTURE = Path(__file__).parent / "fixtures" / "overpass_boston.json"
BBOX = (-71.06, 42.34, -71.04, 42.36)  # west, south, east, north
X0, Y0 = to_utm(-71.05, 42.35)  # synthetic intersection of Main Street and Park Avenue


@pytest.fixture
def recorded():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def streets(tmp_path, monkeypatch, recorded):
    monkeypatch.setattr(osm_names, "_post", lambda query: recorded)
    return fetch_streets(BBOX, tmp_path)[0]


def test_one_request_on_miss_none_on_hit(tmp_path, monkeypatch, recorded):
    calls = []

    def fake_post(query):
        calls.append(query)
        return recorded

    monkeypatch.setattr(osm_names, "_post", fake_post)

    streets, when = fetch_streets(BBOX, tmp_path)
    assert len(calls) == 1
    assert when == datetime.now(UTC).date()
    assert {name for name, _ in streets} == {
        "Main Street",
        "Park Avenue",
        "Elm Street",
        "Far Road",
    }
    assert len(list(tmp_path.glob("overpass-*.json"))) == 1

    again, when_again = fetch_streets(BBOX, tmp_path)
    assert len(calls) == 1  # cache hit, no network
    assert when_again == when
    assert [n for n, _ in again] == [n for n, _ in streets]


def test_query_and_user_agent(recorded):
    query = osm_names._query(BBOX)
    assert 'way["highway"]["name"](42.34,-71.06,42.36,-71.04);' in query
    assert query.rstrip().endswith("out geom;")
    headers = {k.lower(): v for k, v in osm_names._request(query).headers.items()}
    assert headers["user-agent"] == (
        "road-digital-twin/0.1 (+https://github.com/Akamel01/road-digital-twin)"
    )
    assert "@" not in headers["user-agent"]
    assert osm_names.TIMEOUT_S == 60


def test_meta_for_manifest():
    d = date(2026, 11, 8)
    assert osm_names_meta(d) == {"overpass_query_date": d, "licence": "ODbL"}


def test_intersection_takes_two_nearest_distinct_streets(streets):
    core = box(
        X0 - 3, Y0 - 3, X0 + 3, Y0 + 3
    )  # Elm Street is ~5 m away, third in range
    facility = {"type": "intersection", "core": mapping(core)}
    assert name_facility(facility, streets) == "Main Street & Park Avenue"


def test_intersection_out_of_range_is_none(streets):
    far = box(X0 + 2000, Y0 + 2000, X0 + 2006, Y0 + 2006)
    assert (
        name_facility({"type": "intersection", "core": mapping(far)}, streets) is None
    )


def test_segment_named_by_nearest_street_to_midpoint(streets):
    centre = LineString(
        [(X0 + 20, Y0 + 6), (X0 + 60, Y0 + 6)]
    )  # midpoint 1.8 m from Elm
    facility = {"type": "segment", "centreline": mapping(centre)}
    assert name_facility(facility, streets) == "Elm Street"


def test_segment_out_of_range_is_none(streets):
    centre = LineString([(X0 + 2000, Y0), (X0 + 2040, Y0)])
    assert (
        name_facility({"type": "segment", "centreline": mapping(centre)}, streets)
        is None
    )


def test_access_point_names_nearest_street(streets):
    core = box(X0 + 98, Y0 - 6, X0 + 102, Y0 - 4)  # 4 m from Main Street, 12 m from Elm
    facility = {"type": "access_point", "core": mapping(core)}
    assert name_facility(facility, streets) == "Access to Main Street"


def test_access_point_out_of_range_is_none(streets):
    far = box(X0 + 2000, Y0 + 2000, X0 + 2004, Y0 + 2004)
    assert (
        name_facility({"type": "access_point", "core": mapping(far)}, streets) is None
    )
