"""Intersection facilities from HD map geometry (decision 40, spec section 6).

Pure functions over a MapView of plain shapely geometries and tokens, so tests need no nuScenes.
`from_nuscenes_map` is the only function that touches the devkit.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import nearest_points, substring

from twin.contracts import IsdParams


@dataclass
class RoadSegment:
    token: str
    polygon: Polygon
    is_intersection: bool


@dataclass
class Lane:
    """A lane or a lane connector. `road_segment` is the token of the segment the centreline lies in."""

    token: str
    centreline: LineString
    road_segment: str | None
    incoming: list[str] = field(default_factory=list)
    outgoing: list[str] = field(default_factory=list)


@dataclass
class Area:
    """Stop line, ped crossing or carpark area."""

    token: str
    polygon: Polygon


@dataclass
class MapView:
    road_segments: list[RoadSegment]
    lanes: list[Lane]
    stop_lines: list[Area] = field(default_factory=list)
    ped_crossings: list[Area] = field(
        default_factory=list
    )  # not used by intersections() yet
    carpark_areas: list[Area] = field(
        default_factory=list
    )  # not used by intersections() yet


def isd_required_m(params: IsdParams | None = None) -> float:
    """Case B required distance: 0.278 x design speed (km/h) x time gap (s)."""
    p = params or IsdParams()
    return 0.278 * p.design_speed_kmh * p.time_gap_s


def _digest(map_tokens: list[str]) -> str:
    return hashlib.sha1(",".join(sorted(map_tokens)).encode()).hexdigest()


def facility_id(type_letter: str, map_tokens: list[str], length: int = 4) -> str:
    return f"{type_letter}-{_digest(map_tokens)[:length]}"


def _short_ids(hashes: dict[str, str]) -> dict[str, str]:
    """Each id is its first 4 hex; only ids that clash are extended (5, 6, ... hex) until unique."""
    out = {k: h[:4] for k, h in hashes.items()}
    pending = {
        k for k in hashes if sum(v[:4] == hashes[k][:4] for v in hashes.values()) > 1
    }
    n = 4
    while pending and n < 40:
        n += 1
        counts = Counter(hashes[k][:n] for k in pending)
        for k in pending:
            out[k] = hashes[k][:n]
        pending = {k for k in pending if counts[hashes[k][:n]] > 1}
    return out


def _coords(geom) -> list[tuple[float, float]]:
    return [tuple(c[:2]) for c in shapely.get_coordinates(geom)]


def _walk_back(lanes: dict[str, Lane], start: str, length: float) -> LineString:
    """Centrelines followed back from the end of `start`, at least `length` long if the map allows."""
    pts: list[tuple[float, float]] = []
    total = 0.0
    token: str | None = start
    seen: set[str] = set()
    while token is not None and total < length and token in lanes and token not in seen:
        seen.add(token)
        lane = lanes[token]
        coords = [tuple(c[:2]) for c in lane.centreline.coords][::-1]
        pts.extend(coords[1:] if pts else coords)  # consecutive lanes share one vertex
        total += lane.centreline.length
        # DECISION: lane merges: follow the first incoming lane by token order.
        token = min(lane.incoming) if lane.incoming else None
    return LineString(pts)


def _arm_representatives(lanes: list[Lane]) -> list[Lane]:
    """One lane per road arm. Arm = lanes sharing a road_segment; the representative is the lane
    whose midpoint is nearest the arm's mean midpoint (ties by token)."""
    arms: dict[str, list[Lane]] = {}
    # DECISION: arm = road_segment token (road_block not used). Lanes lacking one are their own arm.
    for lane in lanes:
        arms.setdefault(lane.road_segment or lane.token, []).append(lane)
    reps = []
    for group in arms.values():
        mids = [ln.centreline.interpolate(0.5, normalized=True) for ln in group]
        mean = Point(
            sum(m.x for m in mids) / len(mids), sum(m.y for m in mids) / len(mids)
        )
        reps.append(
            min(
                group,
                key=lambda ln: (
                    ln.centreline.interpolate(0.5, normalized=True).distance(mean),
                    ln.token,
                ),
            )
        )
    return sorted(reps, key=lambda ln: ln.token)


def intersections(
    view: MapView, required_isd_m: float, eye_setback_m: float
) -> list[dict]:
    lanes = {lane.token: lane for lane in view.lanes}
    seg_of = {lane.token: lane.road_segment for lane in view.lanes}
    cores = {s.token: s for s in view.road_segments if s.is_intersection}

    # Approach = lane outside any intersection with an outgoing lane inside an intersection.
    approaches: dict[str, list[Lane]] = {t: [] for t in cores}
    for lane in view.lanes:
        if lane.road_segment in cores:
            continue
        for out in lane.outgoing:
            target = seg_of.get(out)
            if target in cores:
                approaches[target].append(lane)
                break

    built = []
    for core_token, core_seg in cores.items():
        core = core_seg.polygon
        other_cores = [c.polygon for t, c in cores.items() if t != core_token]
        legs, eyes = [], []
        for appr in _arm_representatives(approaches[core_token]):
            walk = _walk_back(lanes, appr.token, required_isd_m)
            leg = substring(walk, 0, min(required_isd_m, walk.length))
            # Stop at the next intersection: cut where the leg first enters another core.
            for other in other_cores:
                hit = leg.intersection(other)
                if hit.is_empty:
                    continue
                edge = min(leg.project(Point(c)) for c in _coords(hit))
                leg = substring(leg, 0, edge)
            if not isinstance(leg, LineString):
                continue  # DECISION: a zero-length leg is dropped.

            # Eye point: the stop line for this approach if it crosses the approach centreline,
            # else eye_setback_m back from the core edge along the leg.
            edge_pt = Point(leg.coords[0])
            stop = None
            for sl in view.stop_lines:
                hit = appr.centreline.intersection(sl.polygon)
                if not hit.is_empty:
                    stop = nearest_points(hit, edge_pt)[0]
                    break
            if stop is not None:
                eye = {"source": "stop_line", "point": stop}
            else:
                eye = {"source": "setback", "point": leg.interpolate(eye_setback_m)}

            legs.append({"approach": appr.token, "geometry": mapping(leg)})
            eyes.append(
                {
                    "approach": appr.token,
                    "source": eye["source"],
                    "geometry": mapping(eye["point"]),
                }
            )

        map_tokens = sorted([core_token] + [a.token for a in approaches[core_token]])
        built.append(
            {
                "token": core_token,
                "map_tokens": map_tokens,
                "core": core,
                "legs": legs,
                "eye_points": eyes,
            }
        )

    # ID hashes the core road_segment token only, so changing approach lanes keeps the ID.
    ids = _short_ids({b["token"]: _digest([b["token"]]) for b in built})
    out = [
        {
            "id": f"I-{ids[b['token']]}",
            "type": "intersection",
            "name": None,
            "map_tokens": b["map_tokens"],
            "core": mapping(b["core"]),
            "legs": b["legs"],
            "eye_points": b["eye_points"],
        }
        for b in built
    ]
    return sorted(out, key=lambda f: f["id"])


def from_nuscenes_map(
    nusc_map, patch_box: tuple[float, float, float, float]
) -> MapView:
    """Fill a MapView from the devkit. patch_box is (x_min, y_min, x_max, y_max).

    Lane-to-segment is by the centreline midpoint lying inside a road_segment polygon, because
    the devkit has no direct lane-to-segment link. Itest only: nothing here runs in unit tests.
    """
    layers = [
        "road_segment",
        "lane",
        "lane_connector",
        "stop_line",
        "ped_crossing",
        "carpark_area",
    ]
    recs = nusc_map.get_records_in_patch(patch_box, layers, mode="intersect")

    segments = []
    for t in recs["road_segment"]:
        rec = nusc_map.get("road_segment", t)
        segments.append(
            RoadSegment(
                t,
                nusc_map.extract_polygon(rec["polygon_token"]),
                bool(rec["is_intersection"]),
            )
        )

    lane_tokens = recs["lane"] + recs["lane_connector"]
    poses = nusc_map.discretize_lanes(lane_tokens, 0.5)
    lanes = []
    for t in lane_tokens:
        line = LineString([(x, y) for x, y, *_ in poses[t]])
        mid = line.interpolate(0.5, normalized=True)
        seg = next((s.token for s in segments if s.polygon.contains(mid)), None)
        lanes.append(
            Lane(
                t,
                line,
                seg,
                incoming=list(nusc_map.get_incoming_lane_ids(t)),
                outgoing=list(nusc_map.get_outgoing_lane_ids(t)),
            )
        )

    def areas(layer: str, key: str) -> list[Area]:
        return [
            Area(t, nusc_map.extract_polygon(nusc_map.get(layer, t)[key]))
            for t in recs[layer]
        ]

    return MapView(
        road_segments=segments,
        lanes=lanes,
        stop_lines=areas("stop_line", "polygon_token"),
        ped_crossings=areas("ped_crossing", "polygon_token"),
        carpark_areas=areas("carpark_area", "polygon_token"),
    )
