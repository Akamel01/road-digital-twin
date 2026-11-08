import hashlib
import re

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from twin.contracts import FacilitiesParams, IsdParams
from twin.facilities import (
    Area,
    Lane,
    MapView,
    RoadSegment,
    build_facilities,
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


def _with_side_lanes(view):
    # Two more lanes on the same arm (R_A2) as A1, one either side of it.
    for token, x in (("A1b", 1.0), ("A1c", -1.0)):
        view.lanes.append(
            Lane(
                token,
                LineString([(x, -40), (x, -5)]),
                "R_A2",
                incoming=["CONY"],
                outgoing=["CON1"],
            )
        )
    return view


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


def test_three_lane_arm_gives_one_leg_on_middle_lane():
    facs = intersections(_with_side_lanes(_view()), ISD, SETBACK)
    x = _x_facility(facs)
    assert len(x["legs"]) == 1
    assert x["legs"][0]["approach"] == "A1"  # closest to the arm's mean midpoint
    assert len(x["eye_points"]) == 1


def test_id_unchanged_when_approach_lanes_change():
    base = _x_facility(intersections(_view(), ISD, SETBACK))
    more = _x_facility(intersections(_with_side_lanes(_view()), ISD, SETBACK))
    assert base["id"] == more["id"]
    assert base["map_tokens"] != more["map_tokens"]


def test_id_hashes_core_token_only():
    x = _x_facility(intersections(_view(), ISD, SETBACK))
    assert x["id"] == "I-" + hashlib.sha1(b"X").hexdigest()[:4]


def test_clashing_ids_extend_others_stay_four(monkeypatch):
    from twin import facilities

    fixed = {"X": "aaaa1" + "0" * 35, "Y": "aaaa2" + "0" * 35, "Z": "bbbb3" + "0" * 35}
    monkeypatch.setattr(facilities, "_digest", lambda toks: fixed[toks[0]])
    view = _view()
    view.road_segments.append(RoadSegment("Z", box(50, 50, 60, 60), True))
    by_core = {
        next(t for t in f["map_tokens"] if t in ("X", "Y", "Z")): f["id"]
        for f in intersections(view, ISD, SETBACK)
    }
    assert by_core == {"X": "I-aaaa1", "Y": "I-aaaa2", "Z": "I-bbbb"}


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


# Synthetic map for build_facilities: a north-south corridor.
#   Z (intersection) y -120..-100 | P (segment) y -100..-60 | Y (intersection) y -60..-40
#   Q1 + Q2 (segments) y -40..-5 | X (intersection) y -5..5
# Carpark C sits 0.5 m off Q1's east edge. Carpark D is far away and touches nothing.
def _map(reverse=False):
    segs = [
        RoadSegment("Z", box(-5, -120, 5, -100), True),
        RoadSegment("P", box(-4, -100, 4, -60), False),
        RoadSegment("Y", box(-5, -60, 5, -40), True),
        RoadSegment("Q1", box(-4, -40, 4, -22), False),
        RoadSegment("Q2", box(-4, -22, 4, -5), False),
        RoadSegment("X", box(-5, -5, 5, 5), True),
    ]
    lanes = [
        Lane("F1", LineString([(0, -40), (0, -30)]), "Q1", outgoing=["F2"]),
        Lane(
            "F2",
            LineString([(0, -30), (0, -22)]),
            "Q1",
            incoming=["F1"],
            outgoing=["F3"],
        ),
        Lane("F3", LineString([(0, -22), (0, -5)]), "Q2", incoming=["F2"]),
        Lane(
            "B1", LineString([(0, -22), (0, -40)]), "Q1"
        ),  # opposite direction, own chain
    ]
    carparks = [
        Area("C", box(4.5, -35, 15, -25)),
        Area("D", box(50, 50, 60, 60)),
    ]
    if reverse:
        segs.reverse()
        lanes.reverse()
        carparks.reverse()
    return MapView(segs, lanes, carpark_areas=carparks)


def _build(view):
    return build_facilities(view, IsdParams(), FacilitiesParams())


def _by_type(facs, kind):
    return [f for f in facs if f["type"] == kind]


def test_segment_merges_two_road_segments_between_intersections():
    segs = _by_type(_build(_map()), "segment")
    merged = next(f for f in segs if f["map_tokens"] == ["Q1", "Q2"])
    assert merged["id"] == facility_id("S", ["Q1", "Q2"])
    assert merged["id"].startswith("S-")
    assert merged["between"] == ["X", "Y"]
    # Centreline runs from Y's edge (y=-40) to X's edge (y=-5), forward lanes only.
    coords = merged["centreline"]["coordinates"]
    assert coords[0] == pytest.approx((0, -40))
    assert coords[-1] == pytest.approx((0, -5))
    assert merged["core"]["type"] == "Polygon"


def test_segment_not_merged_across_intersection():
    segs = _by_type(_build(_map()), "segment")
    assert sorted(f["map_tokens"] for f in segs) == [["P"], ["Q1", "Q2"]]
    for f in segs:
        assert "Y" not in f["map_tokens"] and "X" not in f["map_tokens"]
    p = next(f for f in segs if f["map_tokens"] == ["P"])
    assert p["between"] == ["Y", "Z"]


def test_access_point_found_where_carpark_touches_road_and_labelled():
    facs = _build(_map())
    access = _by_type(facs, "access_point")
    assert len(access) == 1  # D touches nothing
    (a,) = access
    assert a["source"] == "map-derived"
    assert a["id"] == "A-" + hashlib.sha1(b"C").hexdigest()[:4]
    assert a["map_tokens"] == ["C", "Q1"]
    assert a["core"]["type"] == "Polygon"


def test_ids_stable_across_builds():
    first = _build(_map())
    second = _build(_map(reverse=True))
    assert [(f["id"], f["type"]) for f in first] == [
        (f["id"], f["type"]) for f in second
    ]


def test_all_ids_unique_across_types_and_letters_match_type():
    facs = _build(_map())
    ids = [f["id"] for f in facs]
    assert len(ids) == len(set(ids)) == 6  # Z, Y, X, P, Q1+Q2, C
    letters = {"intersection": "I", "segment": "S", "access_point": "A"}
    for f in facs:
        assert f["id"][0] == letters[f["type"]]
        assert re.fullmatch(r"[ISA]-[0-9a-f]{4,}", f["id"])
        assert f["observed_core"] is None
        assert f["min_observed"] == 0.5
        assert "hash_tokens" not in f


def _y_x_view(*extra, extent=None):
    # Two intersections, Y (y -60..-40) and X (y -5..5), plus the extra road segments.
    segs = [
        RoadSegment("Y", box(-5, -60, 5, -40), True),
        RoadSegment("X", box(-5, -5, 5, 5), True),
        *extra,
    ]
    return MapView(segs, [], extent=extent)


def test_segments_merge_across_a_0_3m_gap_but_not_a_2m_gap():
    near = _y_x_view(
        RoadSegment("A", box(-4, -40, 4, -22), False),
        RoadSegment("B", box(-4, -21.7, 4, -5), False),  # 0.3 m gap
    )
    (merged,) = _by_type(_build(near), "segment")
    assert merged["map_tokens"] == ["A", "B"]

    far = _y_x_view(
        RoadSegment("A", box(-4, -40, 4, -22), False),
        RoadSegment("B", box(-4, -20, 4, -5), False),  # 2 m gap
    )
    assert sorted(f["map_tokens"] for f in _by_type(_build(far), "segment")) == [
        ["A"],
        ["B"],
    ]


def test_dead_end_segment_touching_one_intersection_is_kept():
    view = _y_x_view(RoadSegment("D", box(-4, -100, 4, -60), False))
    (dead,) = _by_type(_build(view), "segment")
    assert dead["map_tokens"] == ["D"]
    assert dead["between"] == ["Y"]


def test_segment_cut_by_extent_edge_is_kept_and_sliver_is_dropped():
    extent = box(-50, -150, 50, 120)
    view = _y_x_view(
        RoadSegment(
            "E", box(-4, 100, 4, 130), False
        ),  # crosses the extent edge at y=120
        RoadSegment("F", box(20, 20, 22, 22), False),  # touches nothing: a sliver
        extent=extent,
    )
    segs = _by_type(_build(view), "segment")
    assert [f["map_tokens"] for f in segs] == [["E"]]
    assert segs[0]["between"] == []
    # No lanes in the view, so the centreline falls back to the rectangle midline.
    assert segs[0]["centreline"]["type"] == "LineString"


def test_every_segment_has_a_linestring_centreline_and_core():
    for f in _by_type(_build(_map()), "segment"):
        assert f["centreline"]["type"] == "LineString"
        assert f["core"]["type"] == "Polygon"
