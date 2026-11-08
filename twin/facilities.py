"""Intersection facilities from HD map geometry (decision 40, spec section 6).

Pure functions over a MapView of plain shapely geometries and tokens, so tests need no nuScenes.
`from_nuscenes_map` is the only function that touches the devkit.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

import shapely
from shapely.geometry import LineString, Point, Polygon, box, mapping
from shapely.ops import nearest_points, substring, unary_union

from twin.contracts import FacilitiesParams, IsdParams

LETTERS = {"intersection": "I", "segment": "S", "access_point": "A"}


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
    extent: Polygon | None = None  # the patch box; chains reaching its edge are kept


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


def _intersection_records(
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

    return [
        {
            "type": "intersection",
            "name": None,
            "map_tokens": b["map_tokens"],
            # ID hashes the core road_segment token only, so changing approach lanes keeps the ID.
            "hash_tokens": [b["token"]],
            "core": mapping(b["core"]),
            "legs": b["legs"],
            "eye_points": b["eye_points"],
        }
        for b in built
    ]


def intersections(
    view: MapView, required_isd_m: float, eye_setback_m: float
) -> list[dict]:
    return _with_ids(_intersection_records(view, required_isd_m, eye_setback_m))


def _with_ids(records: list[dict]) -> list[dict]:
    """Give every facility its ID. Collisions are resolved across all types at once, so an
    extended ID never clashes with another facility's ID. Each record's `hash_tokens` drive the
    hash and are dropped from the output."""
    hashes = {i: _digest(r["hash_tokens"]) for i, r in enumerate(records)}
    short = _short_ids(hashes)
    for i, r in enumerate(records):
        r["id"] = f"{LETTERS[r['type']]}-{short[i]}"
        del r["hash_tokens"]
    return sorted(records, key=lambda f: f["id"])


def _adjacent(a: Polygon, b: Polygon) -> bool:
    # DECISION: adjacent = within 0.5 m over a stretch. Each polygon is buffered 0.25 m and the
    # overlap must exceed 0.25 m^2: a 0.3 m gap over an 8 m edge merges, a 2 m gap does not, and
    # corner-only contact does not.
    return a.buffer(0.25).intersection(b.buffer(0.25)).area > 0.25


def _fallback_centreline(core: Polygon) -> LineString:
    """Used when no lane centreline lies in the core: the midline along the long axis of the
    core's minimum rotated rectangle."""
    # DECISION: rectangle midline, not a lane. Only a rough line, enough for name lookup.
    p = list(core.minimum_rotated_rectangle.exterior.coords)
    a = math.dist(p[0], p[1])
    b = math.dist(p[1], p[2])
    short = (0, 2) if a <= b else (1, 3)  # the two short sides; join their midpoints
    mids = [((p[i][0] + p[i + 1][0]) / 2, (p[i][1] + p[i + 1][1]) / 2) for i in short]
    return LineString(mids)


def _centreline(core: Polygon, lanes: list[Lane]) -> LineString | None:
    """Longest connected chain of lane centrelines inside `core`, in the direction of travel.
    DECISION: a lane is inside if its midpoint is covered by the core (as in from_nuscenes_map).
    DECISION: chains follow outgoing links, so opposite-direction lanes form their own chain and
    only the longest one is kept. At a fork the first successor by token order is followed."""
    inside = {
        ln.token: ln
        for ln in lanes
        if core.covers(ln.centreline.interpolate(0.5, normalized=True))
    }
    has_pred = {t for ln in inside.values() for t in ln.outgoing if t in inside}
    best: list[Lane] = []
    best_len = -1.0
    for start in sorted(t for t in inside if t not in has_pred):
        chain, token, seen = [], start, set()
        while token in inside and token not in seen:
            seen.add(token)
            chain.append(inside[token])
            nxt = sorted(t for t in inside[token].outgoing if t in inside)
            token = nxt[0] if nxt else None
        length = sum(ln.centreline.length for ln in chain)
        if length > best_len:
            best, best_len = chain, length
    if not best:
        return None
    pts: list[tuple[float, float]] = []
    for ln in best:
        coords = [tuple(c[:2]) for c in ln.centreline.coords]
        pts.extend(coords[1:] if pts and pts[-1] == coords[0] else coords)
    return LineString(pts)


def _segment_records(view: MapView) -> list[dict]:
    """Non-intersection road segments merged into connected chains (adjacency per _adjacent).
    A chain is kept if it touches an intersection or reaches the patch edge (see below)."""
    segs = [s for s in view.road_segments if not s.is_intersection]
    cores = [s for s in view.road_segments if s.is_intersection]
    adj: dict[int, set[int]] = {i: set() for i in range(len(segs))}
    for i, j in combinations(range(len(segs)), 2):
        if _adjacent(segs[i].polygon, segs[j].polygon):
            adj[i].add(j)
            adj[j].add(i)

    # DECISION: keep a chain that touches at least one intersection (a dead end) or reaches the
    # patch edge (cut by the extent). Drop only chains that touch neither: isolated slivers.
    records, done = [], set()
    for start in range(len(segs)):
        if start in done:
            continue
        comp, stack = set(), [start]
        while stack:
            i = stack.pop()
            if i not in comp:
                comp.add(i)
                stack.extend(adj[i] - comp)
        done |= comp
        members = sorted((segs[i] for i in comp), key=lambda s: s.token)
        core = unary_union([s.polygon for s in members])
        ends = sorted(c.token for c in cores if _adjacent(core, c.polygon))
        at_edge = view.extent is not None and core.intersects(view.extent.boundary)
        if not ends and not at_edge:
            continue
        tokens = [s.token for s in members]
        line = _centreline(core, view.lanes) or _fallback_centreline(core)
        records.append(
            {
                "type": "segment",
                "name": None,
                "map_tokens": tokens,
                "hash_tokens": tokens,
                "core": mapping(core),
                "centreline": mapping(line),
                "between": ends,
            }
        )
    return records


def _access_records(view: MapView) -> list[dict]:
    """One access point per carpark area within 1 m of a road segment, map-derived."""
    records = []
    for carpark in sorted(view.carpark_areas, key=lambda a: a.token):
        near = sorted(
            (
                s
                for s in view.road_segments
                if carpark.polygon.buffer(1.0).intersects(s.polygon)
            ),
            key=lambda s: s.token,
        )
        if not near:
            continue
        # Core: carpark where it lies within 5 m of the touching road edges.
        edge = unary_union([s.polygon.boundary for s in near])
        core = carpark.polygon.intersection(edge.buffer(5.0))
        if core.is_empty:
            continue  # DECISION: a carpark wholly inside the road with no edge in reach is dropped.
        records.append(
            {
                "type": "access_point",
                "name": None,
                "source": "map-derived",
                "map_tokens": sorted([carpark.token] + [s.token for s in near]),
                "hash_tokens": [carpark.token],
                "core": mapping(core),
            }
        )
    return records


def build_facilities(
    view: MapView, isd_params: IsdParams, facilities_params: FacilitiesParams
) -> list[dict]:
    """All facilities for one map view: intersections, segments and access points, with IDs
    unique across types. `observed_core` is a placeholder for the ground stage to fill."""
    records = _intersection_records(
        view, isd_required_m(isd_params), isd_params.eye_setback_m
    )
    records += _segment_records(view)
    records += _access_records(view)
    for r in records:
        r["observed_core"] = None
        # DECISION: carried per facility so the ground stage can mark "not scanned enough"
        # without reloading params.
        r["min_observed"] = facilities_params.min_observed
    return _with_ids(records)


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
        extent=box(*patch_box),
    )
