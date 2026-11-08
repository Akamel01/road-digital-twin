import hashlib
import re

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from twin.contracts import IsdParams
from twin.facilities import (
    Area,
    Lane,
    MapView,
    RoadSegment,
    facility_id,
    intersections,
    isd_required_m,
)

ISD = isd_required_m(IsdParams())
SETBACK = IsdParams().eye_setback_m


def _view(stop_lines=(), reverse=False):
    # x = 0 corridor. Approach A0 -> connector CONY in Y -> approach A1 -> connector CON1 in X.
    # Y core y in [-60, -40]; X core y in [-5, 5].
    segs = [
        RoadSegment("R_A", box(-4, -200, 4, -60), False),
        RoadSegment("Y", box(-5, -60, 5, -40), True),
        RoadSegment("R_A2", box(-4, -40, 4, -5), False),
        RoadSegment("X", box(-5, -5, 5, 5), True),
        RoadSegment("R_EXIT", box(-4, 5, 4, 200), False),
    ]
    lanes = [
        Lane("A0", LineString([(0, -200), (0, -60)]), "R_A", outgoing=["CONY"]),
        Lane(
            "CONY",
            LineString([(0, -60), (0, -40)]),
            "Y",
            incoming=["A0"],
            outgoing=["A1"],
        ),
        Lane(
            "A1",
            LineString([(0, -40), (0, -5)]),
            "R_A2",
            incoming=["CONY"],
            outgoing=["CON1"],
        ),
        Lane(
            "CON1",
            LineString([(0, -5), (0, 5)]),
            "X",
            incoming=["A1"],
            outgoing=["EXIT"],
        ),
        Lane("EXIT", LineString([(0, 5), (0, 200)]), "R_EXIT", incoming=["CON1"]),
    ]
    if reverse:
        segs.reverse()
        lanes.reverse()
    return MapView(segs, lanes, stop_lines=[Area(t, p) for t, p in stop_lines])


def _x_facility(facs):
    return next(f for f in facs if "X" in f["map_tokens"])


def test_isd_required_matches_formula_for_defaults():
    assert ISD == pytest.approx(0.278 * 50.0 * 7.5)
    assert ISD == pytest.approx(104.25)


def test_facility_id_format_and_order_independent():
    assert facility_id("I", ["b", "a"]) == facility_id("I", ["a", "b"])
    assert facility_id("I", ["a", "b"]) == "I-" + hashlib.sha1(b"a,b").hexdigest()[:4]


def test_ids_identical_across_builds_and_token_order():
    first = intersections(_view(), ISD, SETBACK)
    second = intersections(_view(reverse=True), ISD, SETBACK)
    assert [f["id"] for f in first] == [f["id"] for f in second]
    assert [f["map_tokens"] for f in first] == [f["map_tokens"] for f in second]
    for f in first:
        assert re.fullmatch(r"I-[0-9a-f]{4}", f["id"])
        assert f["name"] is None and f["type"] == "intersection"


def test_leg_stops_at_next_intersection_core():
    facs = intersections(_view(), ISD, SETBACK)
    x = _x_facility(facs)
    (leg,) = [leg for leg in x["legs"] if leg["approach"] == "A1"]
    coords = leg["geometry"]["coordinates"]
    assert coords[0] == pytest.approx((0, -5))
    assert coords[-1] == pytest.approx((0, -40))  # Y core edge, not the full ISD


def test_leg_runs_full_isd_when_nothing_in_the_way():
    view = _view()
    view.lanes = [ln for ln in view.lanes if ln.token not in ("CONY", "A0", "A1")]
    view.lanes.append(
        Lane(
            "A1",
            LineString([(0, -200), (0, -5)]),
            "R_A2",
            incoming=[],
            outgoing=["CON1"],
        )
    )
    view.road_segments = [s for s in view.road_segments if s.token != "Y"]
    facs = intersections(view, ISD, SETBACK)
    x = _x_facility(facs)
    coords = x["legs"][0]["geometry"]["coordinates"]
    assert Point(coords[-1]).distance(Point(0, -5 - ISD)) < 1e-6


def test_eye_point_on_stop_line_when_present():
    stop = Polygon([(-3, -11), (3, -11), (3, -9), (-3, -9)])
    facs = intersections(_view(stop_lines=[("SL", stop)]), ISD, SETBACK)
    eye = next(e for e in _x_facility(facs)["eye_points"] if e["approach"] == "A1")
    assert eye["source"] == "stop_line"
    assert eye["geometry"]["coordinates"] == pytest.approx((0, -9))


def test_eye_point_at_setback_without_stop_line():
    facs = intersections(_view(), ISD, SETBACK)
    eye = next(e for e in _x_facility(facs)["eye_points"] if e["approach"] == "A1")
    assert eye["source"] == "setback"
    assert eye["geometry"]["coordinates"] == pytest.approx((0, -5 - SETBACK))
