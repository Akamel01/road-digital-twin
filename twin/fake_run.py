"""Write synthetic run folders and a showcase bundle that match twin.contracts.

Nothing reads sensor data. Geometry comes from twin.fixtures; every other value
is a constant or derived from one, so the output is the same on every call.
Runs are never overwritten, so an existing run folder is an error.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import laspy
import numpy as np
import yaml
from PIL import Image
from shapely.geometry import LineString, Point, Polygon, mapping

from twin import fixtures as fx
from twin import registry
from twin.contracts import (
    STAGE_NAMES,
    STAGES,
    AreaFacility,
    AreaIndex,
    Drive,
    Manifest,
    ManifestCode,
    ManifestData,
    ManifestStage,
    OsmNames,
    Params,
    Pipeline,
    StageResult,
)
from twin.publish import PUBLIC_FILES
from twin.runner import StageContext
from twin.stages.profile import facility_lines, sample_line
from twin.tiles import write_tiles

RUN_DATE = "20261108"
START = datetime(2026, 11, 8, 9, 0, 0)
ORIGIN_E, ORIGIN_N = 330000.0, 4691000.0  # fake UTM 19N position of local (0, 0)
SPACING_M = 0.25  # fixture point spacing
N_SWEEPS = 3
OBSERVED_MAX_X = (
    36.0  # cameras see the ground only up to this x; beyond it is unobserved
)
PAINT_MIN_INTENSITY = 0.6
ROAD_RGB = (112, 112, 112)
SIDEWALK_RGB = (168, 160, 150)
PAINT_RGB = (236, 236, 228)
RASTER_CELLS = 256
RASTER_M = 0.25  # cell size of the base raster
RASTER_ORIGIN = (-12.0, -12.0)  # local x, y of the lower-left cell corner


@dataclass(frozen=True)
class DriveSpec:
    scene_token: str
    name: str


DRIVE_SPECS = (
    DriveSpec("fake-scene-0001", "Synthetic drive 1"),
    DriveSpec("fake-scene-0002", "Synthetic drive 2"),
)


@dataclass(frozen=True)
class FacilitySpec:
    type: str
    name: str
    tokens: tuple[str, ...]
    core: tuple[float, float, float, float]  # x0, x1, y0, y1, local metres
    observed: dict[int, float]  # drive index -> observed_core on that drive

    @property
    def id(self) -> str:
        letter = {"intersection": "I", "segment": "S", "access_point": "A"}[self.type]
        digest = hashlib.sha1("\n".join(sorted(self.tokens)).encode()).hexdigest()
        return f"{letter}-{digest[:4]}"


FACILITIES = (
    FacilitySpec(
        "intersection",
        "Fake Ave at First St",
        ("fake-token-01", "fake-token-02"),
        (2.0, 12.0, 0.0, 16.0),
        {0: 0.92, 1: 0.88},
    ),
    FacilitySpec(
        "segment",
        "Fake St, block 1",
        ("fake-token-03",),
        (14.0, 26.0, 0.0, 16.0),
        {0: 0.61, 1: 0.84},
    ),
    FacilitySpec(
        "access_point",
        "Fake lot entrance A",
        ("fake-token-04",),
        (28.0, 31.0, 16.0, 20.0),
        {0: 0.73},
    ),
    FacilitySpec(
        "intersection",
        "Fake Ave at Second St",
        ("fake-token-05", "fake-token-06"),
        (4.0, 16.0, 4.0, 12.0),
        {1: 0.66},
    ),
    FacilitySpec(
        "segment",
        "Fake St, block 2",
        ("fake-token-07",),
        (20.0, 38.0, 4.0, 12.0),
        {0: 0.55},
    ),
    FacilitySpec(
        "access_point",
        "Fake lot entrance B",
        ("fake-token-08",),
        (36.0, 40.0, 0.0, 4.0),
        {1: 0.31},
    ),
)

PARKED_BOX = {
    "token": "fake-box-parked-1",
    "parked": True,
    "center": [20.0, 1.0, 0.7],
    "size": [4.5, 1.9, 1.4],
    "yaw": 0.0,
}
MOVING_BOX = {
    "token": "fake-box-moving-1",
    "parked": False,
    "center": [32.0, 8.0, 0.8],
    "size": [4.2, 1.8, 1.6],
    "yaw": 0.0,
}
BOXES = (PARKED_BOX, MOVING_BOX)
ISD_REQUIRED_M = 96.4
ISD_AVAILABLE_M = 118.0
ISD_PARKED_M = 61.2
# One leg is short on purpose, so the blocked sight-line ring is exercised in the UI.
SHORT_LEG = ("Fake Ave at Second St", "east")


@dataclass
class _Ctx:
    index: int
    run_id: str
    spec: DriveSpec
    plane: np.ndarray
    canopy: np.ndarray
    wall: np.ndarray
    facilities: list[FacilitySpec]
    observed: dict[str, float]
    rasters: dict[str, np.ndarray] = field(default_factory=dict)


def _raster_bbox() -> tuple[float, float, float, float]:
    """UTM 19N extent of the base raster (EPSG:32619, metres)."""
    x0 = ORIGIN_E + RASTER_ORIGIN[0]
    y0 = ORIGIN_N + RASTER_ORIGIN[1]
    size = RASTER_CELLS * RASTER_M
    return (x0, y0, x0 + size, y0 + size)


def _run_id(index: int) -> str:
    digest = hashlib.sha1(DRIVE_SPECS[index].scene_token.encode()).hexdigest()[:6]
    return f"{RUN_DATE}-09{index:02d}00-{digest}"


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n")


def _feat(geom_type: str, coords, **props) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": geom_type, "coordinates": coords},
        "properties": props,
    }


def _fc(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:32619"}},
        "features": features,
    }


def _p3(x: float, y: float, z: float) -> list[float]:
    return [
        round(ORIGIN_E + float(x), 3),
        round(ORIGIN_N + float(y), 3),
        round(float(z), 3),
    ]


def _all(c: _Ctx) -> tuple[np.ndarray, np.ndarray]:
    pts = np.vstack([c.plane, c.canopy, c.wall])
    sweep = np.arange(len(pts)) % N_SWEEPS
    return pts, sweep


def _cols(pts: np.ndarray, sweep: np.ndarray) -> dict:
    return {
        "x": pts[:, 0].astype(np.float32),
        "y": pts[:, 1].astype(np.float32),
        "z": pts[:, 2].astype(np.float32),
        "intensity": pts[:, 3].astype(np.float32),
        "sweep": sweep.astype(np.uint8),
    }


def _pose_doc(dx: float = 0.0, dy: float = 0.0) -> dict:
    poses = []
    for s in range(N_SWEEPS):
        m = np.eye(4)
        m[0, 3] = 2.0 * s + dx
        m[1, 3] = dy
        poses.append({"sweep": s, "matrix": m.tolist()})
    return {"poses": poses}


def _in_box(pts: np.ndarray, box: dict) -> np.ndarray:
    cx, cy, cz = box["center"]
    length, width, height = box["size"]
    return (
        (np.abs(pts[:, 0] - cx) <= length / 2)
        & (np.abs(pts[:, 1] - cy) <= width / 2)
        & (pts[:, 2] <= cz + height / 2)
    )


def _class_colour(pts: np.ndarray) -> np.ndarray:
    rgb = np.empty((len(pts), 3), np.uint8)
    rgb[:] = ROAD_RGB
    rgb[pts[:, 1] >= fx.CURB_Y] = SIDEWALK_RGB
    rgb[pts[:, 3] > PAINT_MIN_INTENSITY] = PAINT_RGB
    return rgb


def _cell_index(x: np.ndarray, y: np.ndarray):
    col = np.floor((x - RASTER_ORIGIN[0]) / RASTER_M).astype(int)
    up = np.floor((y - RASTER_ORIGIN[1]) / RASTER_M).astype(int)
    inside = (col >= 0) & (col < RASTER_CELLS) & (up >= 0) & (up < RASTER_CELLS)
    return RASTER_CELLS - 1 - up, col, inside


def _rasters(plane: np.ndarray) -> dict[str, np.ndarray]:
    """Base-level RGBA rasters (north up) for lidar, ortho and coverage."""
    shape = (RASTER_CELLS, RASTER_CELLS, 4)
    row, col, inside = _cell_index(plane[:, 0], plane[:, 1])
    lidar = np.zeros(shape, np.uint8)
    value = np.clip(plane[:, 3] * 255, 0, 255).astype(np.uint8)
    lidar[row[inside], col[inside], :3] = value[inside, None]
    lidar[row[inside], col[inside], 3] = 255
    ortho = np.zeros(shape, np.uint8)
    seen = inside & (plane[:, 0] <= OBSERVED_MAX_X)
    ortho[row[seen], col[seen], :3] = _class_colour(plane)[seen]
    ortho[row[seen], col[seen], 3] = 255
    coverage = np.zeros(shape, np.uint8)
    coverage[lidar[..., 3] > 0] = (224, 112, 79, 150)  # unobserved, #E0704F
    coverage[ortho[..., 3] > 0] = (156, 199, 164, 160)  # observed, #9CC7A4
    return {"lidar": lidar, "ortho": ortho, "coverage": coverage}


def _las(
    path: Path, pts: np.ndarray, classification: int, rgb: np.ndarray | None = None
) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.offsets = np.array([ORIGIN_E, ORIGIN_N, 0.0])
    header.scales = np.array([0.001, 0.001, 0.001])
    las = laspy.LasData(header)
    las.x = pts[:, 0] + ORIGIN_E
    las.y = pts[:, 1] + ORIGIN_N
    las.z = pts[:, 2]
    las.intensity = np.clip(pts[:, 3] * 65535, 0, 65535).astype(np.uint16)
    las.classification = np.full(len(pts), classification, np.uint8)
    if rgb is not None:
        las.red = rgb[:, 0].astype(np.uint16) * 257
        las.green = rgb[:, 1].astype(np.uint16) * 257
        las.blue = rgb[:, 2].astype(np.uint16) * 257
    las.write(path)


_DIRS = {
    "north": (0.0, 1.0),
    "south": (0.0, -1.0),
    "east": (1.0, 0.0),
    "west": (-1.0, 0.0),
    "exit": (0.0, 1.0),
}
# Legs per facility type. An intersection has four arms, so its profile has two through lines.
LEGS = {"intersection": ["north", "south", "east", "west"], "access_point": ["exit"]}


def _leg_local(core: tuple, name: str) -> LineString:
    """Leg line in local metres, from the core edge facing the approach, out to ISD_REQUIRED_M."""
    x0, x1, y0, y1 = core
    dx, dy = _DIRS[name]
    sx = (x0 + x1) / 2 + dx * (x1 - x0) / 2
    sy = (y0 + y1) / 2 + dy * (y1 - y0) / 2
    return LineString([(sx, sy), (sx + dx * ISD_REQUIRED_M, sy + dy * ISD_REQUIRED_M)])


def _leg(core: tuple, name: str) -> LineString:
    """The same leg in UTM, as the GeoJSON files store it."""
    return LineString([_p3(x, y, 0)[:2] for x, y in _leg_local(core, name).coords])


def _load(d: Path, c: _Ctx) -> dict:
    pts, sweep = _all(c)
    np.savez_compressed(d / "points.npz", **_cols(pts, sweep))
    _dump(d / "poses.json", _pose_doc())
    boxes = [{"sweep": s, "boxes": list(BOXES)} for s in range(N_SWEEPS)]
    _dump(d / "boxes.json", {"sweeps": boxes})
    layers = [
        _feat(
            "Polygon",
            [
                [
                    _p3(x, y, 0)[:2]
                    for x, y in [
                        (0, 0),
                        (40, 0),
                        (40, fx.CURB_Y),
                        (0, fx.CURB_Y),
                        (0, 0),
                    ]
                ]
            ],
            layer="drivable_area",
        ),
        _feat(
            "LineString",
            [_p3(0, fx.CURB_Y, 0)[:2], _p3(40, fx.CURB_Y, 0)[:2]],
            layer="curb_edge",
        ),
    ]
    _dump(d / "reference.geojson", _fc(layers))
    facs = []
    for f in c.facilities:
        x0, x1, y0, y1 = f.core
        ring = [
            _p3(x, y, 0)[:2]
            for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        ]
        legs, eyes = [], []
        for name in LEGS.get(f.type, []):
            leg = _leg(f.core, name)
            eye = Point(*leg.interpolate(Params().isd.eye_setback_m).coords[0])
            legs.append({"approach": name, "geometry": mapping(leg)})
            eyes.append(
                {"approach": name, "source": "setback", "geometry": mapping(eye)}
            )
        facs.append(
            _feat(
                "Polygon",
                [ring],
                id=f.id,
                type=f.type,
                name=f.name,
                map_tokens=list(f.tokens),
                legs=legs,
                eye_points=eyes,
            )
        )
    _dump(d / "facilities.geojson", _fc(facs))
    cams = {
        "cameras": [
            {
                "channel": "CAM_FRONT",
                "sweep": s,
                "timestamp_us": 1_000_000 + 500_000 * s,
                "image": f"fake/CAM_FRONT_{s}.jpg",
                "intrinsics": [[1266.4, 0, 816.3], [0, 1266.4, 491.5], [0, 0, 1]],
                "extrinsics": {
                    "translation": [1.7, 0.0, 1.5],
                    "rotation_wxyz": [1, 0, 0, 0],
                },
            }
            for s in range(N_SWEEPS)
        ]
    }
    _dump(d / "cameras.json", cams)
    # The load stage's real metrics (twin/stages/load.py), the same keys the runner copies into the manifest.
    return {
        "n_sweeps": N_SWEEPS,
        "n_points": len(pts),
        "n_facilities": len(facs),
        "osm_names": {"overpass_query_date": "2026-11-08", "licence": "ODbL"},
    }


def _mask(d: Path, c: _Ctx) -> dict:
    pts, sweep = _all(c)
    parked = _in_box(pts, PARKED_BOX)
    moving = _in_box(pts, MOVING_BOX)
    keep = ~(parked | moving)
    np.savez_compressed(d / "points.npz", **_cols(pts[keep], sweep[keep]))
    np.savez_compressed(d / "parked.npz", **_cols(pts[parked], sweep[parked]))
    n_parked = int(parked.sum())
    n_dropped = int((moving & ~parked).sum())
    # Same keys as twin/stages/mask.py.
    return {
        "n_in": n_parked + n_dropped,
        "n_kept": int(keep.sum()),
        "n_parked": n_parked,
        "n_dropped_moving": n_dropped,
    }


def _align(d: Path, c: _Ctx) -> dict:
    dx, dy = 0.012 + 0.005 * c.index, -0.004
    _dump(d / "poses.json", _pose_doc(dx, dy))
    # Same keys as twin/stages/align.py (qa.json and the manifest metrics).
    drift = round(float(np.hypot(dx, dy)), 4)
    qa = {
        "method": "kiss-icp",
        "fallback_used": False,
        "fallback_reason": None,
        "xy_drift_p50_m": drift,
        "xy_drift_p95_m": drift,
        "yaw_drift_p95_deg": 0.0,
        "n_sweeps": N_SWEEPS,
    }
    _dump(d / "qa.json", qa)
    return qa


def _plane_residuals(road: np.ndarray):
    a = np.column_stack([road[:, 0], road[:, 1], np.ones(len(road))])
    coef, *_ = np.linalg.lstsq(a, road[:, 2], rcond=None)
    return road[:, 2] - a @ coef, coef


def _surface(pts: np.ndarray, cell: float = 0.5):
    nx = int(np.ceil((fx.SITE_X[1] - fx.SITE_X[0]) / cell))
    ny = int(np.ceil((fx.SITE_Y[1] - fx.SITE_Y[0]) / cell))
    ix = np.clip(np.floor((pts[:, 0] - fx.SITE_X[0]) / cell).astype(int), 0, nx - 1)
    iy = np.clip(np.floor((pts[:, 1] - fx.SITE_Y[0]) / cell).astype(int), 0, ny - 1)
    idx = ix * ny + iy
    counts = np.bincount(idx, minlength=nx * ny)
    sums = np.bincount(idx, weights=pts[:, 2], minlength=nx * ny)
    z = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    return z.reshape(nx, ny).astype(np.float32), counts.reshape(nx, ny).astype(
        np.uint16
    )


def _ground(d: Path, c: _Ctx) -> dict:
    road = c.plane[c.plane[:, 1] < fx.CURB_Y]
    res, _ = _plane_residuals(road)
    rmse = float(np.sqrt(np.mean(res**2)))
    p95 = float(np.percentile(np.abs(res), 95))
    _las(d / "ground.laz", c.plane, classification=2)
    _las(d / "nonground.laz", np.vstack([c.canopy, c.wall]), classification=1)
    z, count = _surface(c.plane)
    np.savez_compressed(d / "surface.npz", z=z, count=count)
    # Same keys as twin/stages/ground.py; observed_core and not_scanned_enough live in this qa.
    min_observed = Params().facilities.min_observed
    qa = {
        "method": "ransac-tiles",
        "rmse_m": round(rmse, 4),
        "z_disagreement_p95_m": round(p95, 4),
        "height_valid": True,
        "height_invalid_reason": None,
        "qa_cell_m": Params().ground.qa_cell_m,
        "qa_max_p95_m": Params().ground.qa_max_p95_m,
        "n_ground": len(c.plane),
        "n_nonground": int(len(c.canopy) + len(c.wall)),
        "observed_core": {k: round(v, 4) for k, v in c.observed.items()},
        "min_observed": min_observed,
        "not_scanned_enough": sorted(
            k for k, v in c.observed.items() if v < min_observed
        ),
    }
    _dump(d / "qa.json", qa)
    return qa


def _features(d: Path, c: _Ctx) -> dict:
    markings = []
    for k, (x0, x1, y0, y1) in enumerate(fx.STRIPES):
        xc = (x0 + x1) / 2
        inside = (
            (c.plane[:, 0] >= x0)
            & (c.plane[:, 0] <= x1)
            & (c.plane[:, 1] >= y0)
            & (c.plane[:, 1] <= y1)
            & (c.plane[:, 3] > PAINT_MIN_INTENSITY)
        )
        coords = [_p3(xc, y, fx.ground_z(xc, y)) for y in (y0, y1)]
        markings.append(
            _feat(
                "LineString",
                coords,
                id=f"M-{k + 1}",
                kind="marking",
                marking_type="divider",
                n_points=int(inside.sum()),
            )
        )
    _dump(d / "markings.geojson", _fc(markings))
    # Two zebra bands across the road, so the crosswalk layer is exercised.
    crosswalks = []
    for k, (x0, x1) in enumerate(((14.0, 16.0), (20.0, 22.0))):
        ring = [(x0, 1.0), (x1, 1.0), (x1, 15.0), (x0, 15.0), (x0, 1.0)]
        crosswalks.append(
            _feat(
                "Polygon",
                [[_p3(x, y, fx.ground_z(x, y)) for x, y in ring]],
                id=f"X-{k + 1}",
                kind="crosswalk",
                n_points=0,
            )
        )
    _dump(d / "crosswalks.geojson", _fc(crosswalks))
    curb_pts = int(np.sum(np.isclose(c.plane[:, 1], fx.CURB_Y)))
    curb = _feat(
        "LineString",
        [_p3(x, fx.CURB_Y, fx.ground_z(x, fx.CURB_Y)) for x in (0.0, 40.0)],
        id="C-1",
        kind="curb",
        n_points=curb_pts,
    )
    _dump(d / "curbs.geojson", _fc([curb]))
    # Same keys as twin/stages/features.py (qa.json and the manifest metrics).
    qa = {
        "method": "intensity",
        "n_ground": len(c.plane),
        "height_valid": True,
        "not_scanned_enough": sorted(
            k for k, v in c.observed.items() if v < Params().facilities.min_observed
        ),
        "n_markings": len(markings),
        "n_crosswalks": len(crosswalks),
        "n_curbs": 1,
    }
    _dump(d / "qa.json", qa)
    return qa


def _colour(d: Path, c: _Ctx) -> dict:
    Image.fromarray(c.rasters["ortho"]).save(d / "ortho.png")
    ul_e = ORIGIN_E + RASTER_ORIGIN[0]
    ul_n = ORIGIN_N + RASTER_ORIGIN[1] + RASTER_CELLS * RASTER_M
    pgw = [RASTER_M, 0.0, 0.0, -RASTER_M, ul_e + RASTER_M / 2, ul_n - RASTER_M / 2]
    (d / "ortho.pgw").write_text("\n".join(f"{v:.6f}" for v in pgw) + "\n")
    pts, _ = _all(c)  # same order as ground.laz then nonground.laz
    observed = pts[:, 0] <= OBSERVED_MAX_X
    np.savez_compressed(d / "rgb.npz", rgb=_class_colour(pts), observed=observed)
    # Same keys as twin/stages/colour.py. edge_offset_p95_m stays None: the real stage does not measure it yet.
    colour = {
        "method": "zbuffer-topk",
        "ortho_label": "",
        "height_valid": True,
        "views_median": 3,
        "observed_share": round(float(observed.mean()), 4),
        "n_points": len(pts),
        "n_cameras": N_SWEEPS,
        "n_cameras_skipped_outside_sweeps": 0,
        "top_k": Params().colour.top_k,
        "gsd_m": Params().colour.gsd_m,
        "edge_offset_p95_m": None,
    }
    _dump(d / "qa.json", colour)
    return colour


def _profile(d: Path, c: _Ctx) -> dict:
    rows = ["facility,line,s_m,z_m,n"]
    feats = []
    for f in c.facilities:
        x0, x1, y0, y1 = f.core
        feature = {
            "geometry": mapping(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])),
            "properties": {
                "type": f.type,
                "legs": [
                    {"geometry": mapping(_leg_local(f.core, n))}
                    for n in LEGS.get(f.type, [])
                ],
            },
        }
        for label, line in facility_lines(feature):  # the profile stage's own line rule
            line_id = f"{f.id}/{label}"
            coords = []
            for s, x, y in sample_line(line, 1.0):
                z = float(fx.ground_z(x, y))
                rows.append(f"{f.id},{line_id},{s:.1f},{z:.3f},20")
                coords.append(_p3(x, y, z))
            feats.append(
                _feat("LineString", coords, facility=f.id, line=line_id, label=label)
            )
    (d / "profile.csv").write_text("\n".join(rows) + "\n")
    _dump(d / "centrelines.geojson", _fc(feats))
    # Same keys as twin/stages/profile.py.
    return {
        "height_valid": True,
        "facilities_profiled": len(feats),
        "lines": len(feats),
        "not_scanned_enough": [],
        "samples": len(rows) - 1,
    }


def _isd(d: Path, c: _Ctx) -> dict:
    facs = []
    for f in c.facilities:
        names = {"intersection": ["north", "east"], "access_point": ["exit"]}.get(
            f.type, []
        )
        not_scanned = c.observed[f.id] < Params().facilities.min_observed
        legs = []
        for k, name in enumerate(names):
            # Fake data: an intersection leg's left side looks along the other approach; access exits have no side.
            other = names[1 - k] if f.type == "intersection" else None
            available = ISD_AVAILABLE_M - 10 * k
            if (f.name, name) == SHORT_LEG:
                available = ISD_REQUIRED_M - 20
            if not_scanned:
                status, reason, available = (
                    "indeterminate",
                    "facility not scanned enough",
                    None,
                )
            else:
                status = "ok" if available >= ISD_REQUIRED_M else "short"
                reason = (
                    f"left {other}: with parked vehicles {ISD_PARKED_M} m"
                    if other
                    else f"with parked vehicles {ISD_PARKED_M} m"
                )
            left = None
            if other:
                left = {
                    "leg": other,
                    "available_m": available,
                    "available_with_parked_m": None
                    if available is None
                    else ISD_PARKED_M,
                    "status": status,
                }
            legs.append(
                {
                    "leg": name,
                    "required_m": ISD_REQUIRED_M,
                    "left": left,
                    "right": None,
                    "status": status,
                    "reason": reason,
                }
            )
        facs.append({"facility": f.id, "legs": legs})
    not_scanned = sorted(
        f.id
        for f in c.facilities
        if c.observed[f.id] < Params().facilities.min_observed
    )
    doc = {"case": "B1", "facilities": facs, "not_scanned_enough": not_scanned}
    _dump(d / "isd.json", doc)
    return {"isd": doc}


def _entry(
    layer: str,
    p50: float | None,
    p95: float | None,
    cov: float | None,
    n: int,
    label: str = "",
    reason: str = "",
) -> dict:
    """One accuracy entry, the same keys as twin/stages/accuracy.py _entry."""
    return {
        "reference_layer": layer,
        "p50_m": None if p50 is None else round(p50, 3),
        "p95_m": None if p95 is None else round(p95, 3),
        "matched_p50_m": None if p50 is None else round(p50, 3),
        "matched_p95_m": None if p95 is None else round(p95, 3),
        "false_positive_rate": None if p50 is None else 0.05,
        "coverage": None if cov is None else round(cov, 3),
        "n": n,
        "n_samples": 0 if reason else 4 * n,
        "label": label,
        "reason": reason,
    }


def _accuracy(d: Path, c: _Ctx) -> dict:
    """Same document as the real one-way stage: method, buffer_m, elements, facilities, qa."""
    base = 0.01 * c.index
    elements = {
        "markings": _entry(
            "lane_divider, road_divider", 0.05 + base, 0.13 + base, 0.71, 42
        ),
        "crosswalks": _entry("ped_crossing", 0.07 + base, 0.18 + base, 0.5, 2),
        "curbs": _entry(
            "drivable_area", 0.08 + base, 0.21 + base, 0.64, 18, "map-conditioned"
        ),
    }
    marking_types = {
        "divider": elements["markings"],
        "stop_line": _entry(
            "stop_line", None, None, None, 0, "", "no observed elements"
        ),
        "crosswalk_stripe": _entry(
            "ped_crossing", None, None, None, 0, "", "no observed elements"
        ),
        "other_paint": _entry("", None, None, None, 0, "", "no map layer"),
    }
    min_observed = Params().facilities.min_observed
    facilities = {}
    for f in c.facilities:
        if c.observed[f.id] < min_observed:
            facilities[f.id] = _entry("", None, None, None, 0, "", "not scanned enough")
        else:
            facilities[f.id] = _entry(
                "lane_divider, road_divider, ped_crossing, drivable_area",
                0.09 + base,
                0.2 + base,
                c.observed[f.id],
                10,
                "map-conditioned",
            )
    doc = {
        "method": "one-way",
        "buffer_m": Params().accuracy.buffer_m,
        "match_radius_m": Params().accuracy.match_radius_m,
        "elements": elements,
        "marking_types": marking_types,
        "facilities": facilities,
        "qa": {
            "n_observed_only": True,
            "n_excluded_not_observed": 0,
            "absent_element_files": [],
            "markings_extractable": True,
        },
    }
    _dump(d / "accuracy.json", doc)
    return doc


def _outputs(d: Path, c: _Ctx) -> dict:
    """The real outputs stage, run over the synthetic stage folders. Returns its own metrics."""
    ctx = StageContext(
        run_dir=d.parent,
        scene_token=c.spec.scene_token,
        seed=0,
        log=logging.getLogger("fake-run"),
    )
    return registry.lookup("outputs", "dxf-pdf")(ctx, None).metrics


def _semantics(d: Path, c: _Ctx) -> dict:
    """Placeholder files only: the real stage needs a GPU model, and the fake run is off by default there."""
    for name in STAGES["semantics"].outputs:
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).touch()
    return {}


WRITERS = {
    "load": _load,
    "mask": _mask,
    "align": _align,
    "ground": _ground,
    "features": _features,
    "colour": _colour,
    "profile": _profile,
    "isd": _isd,
    "accuracy": _accuracy,
    "outputs": _outputs,
    "semantics": _semantics,
}


def _code() -> ManifestCode:
    root = Path(__file__).resolve().parents[1]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(status)
    except (OSError, subprocess.CalledProcessError):
        sha, dirty = "0" * 40, False
    lock = root / "uv.lock"
    digest = hashlib.sha256(lock.read_bytes() if lock.exists() else b"").hexdigest()
    return ManifestCode(git_sha=sha, dirty=dirty, lockfile_sha256=digest)


def _write_run(out: Path, index: int, showcase: Path) -> str:
    spec = DRIVE_SPECS[index]
    run_id = _run_id(index)
    run_dir = out / run_id
    if run_dir.exists():
        raise FileExistsError(f"run folder exists, not overwritten: {run_dir}")
    run_dir.mkdir(parents=True)
    facilities = [f for f in FACILITIES if index in f.observed]
    observed = {f.id: f.observed[index] for f in facilities}
    plane = fx.make_plane(seed=index, spacing_m=SPACING_M)
    ctx = _Ctx(
        index=index,
        run_id=run_id,
        spec=spec,
        plane=plane,
        canopy=fx.make_canopy(seed=index + 10, spacing_m=SPACING_M),
        wall=fx.make_wall(seed=index + 20, spacing_m=SPACING_M),
        facilities=facilities,
        observed=observed,
        rasters=_rasters(plane),
    )
    pipeline, params = Pipeline(), Params()
    metrics: dict = {}
    stages = []
    for n, name in enumerate(STAGE_NAMES):
        folder = run_dir / f"{STAGES[name].number}_{name}"
        folder.mkdir()
        stage_metrics = WRITERS[name](folder, ctx)
        # The runner's rule: each stage's metrics sit under the stage name (twin/runner.py).
        if stage_metrics:
            metrics[name] = stage_metrics
        result = StageResult(
            status="ok",
            files=list(STAGES[name].outputs),
            metrics=stage_metrics,
            message="synthetic fake-run",
        )
        (folder / "stage_result.json").write_text(result.model_dump_json(indent=2))
        stages.append(
            ManifestStage(
                name=name,
                method=getattr(pipeline, name).method,
                status="ok",
                started=START + timedelta(seconds=15 * n),
                seconds=2.0 + n,
                files=list(STAGES[name].outputs),
            )
        )
    manifest = Manifest(
        run_id=run_id,
        code=_code(),
        data=ManifestData(
            scene_token=spec.scene_token,
            osm_names=OsmNames(overpass_query_date=date(2026, 11, 8)),
        ),
        pipeline=pipeline,
        params=params,
        stages=stages,
        metrics=metrics,
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    (run_dir / "pipeline.yaml").write_text(
        yaml.safe_dump(pipeline.model_dump(mode="json"), sort_keys=False)
    )
    (run_dir / "params.yaml").write_text(
        yaml.safe_dump(params.model_dump(mode="json"), sort_keys=False)
    )
    write_tiles(showcase, run_id, ctx.rasters, _raster_bbox())
    (showcase / run_id).mkdir(parents=True, exist_ok=True)
    for name in (
        *PUBLIC_FILES,
        "twin.laz",
    ):  # what publish copies; LAZ is not thinned here
        shutil.copy(run_dir / "10_outputs" / name, showcase / run_id / name)
    shutil.copy(run_dir / "manifest.json", showcase / run_id / "manifest.json")
    for name in ("profile.csv", "centrelines.geojson"):
        shutil.copy(run_dir / "7_profile" / name, showcase / run_id / name)
    return run_id


def _area(run_ids: list[str]) -> AreaIndex:
    drives = [
        Drive(
            run_id=rid,
            scene_token=DRIVE_SPECS[i].scene_token,
            name=DRIVE_SPECS[i].name,
            bbox=list(_raster_bbox()),
        )
        for i, rid in enumerate(run_ids)
    ]
    min_observed = Params().facilities.min_observed
    facilities = []
    for f in FACILITIES:
        covered = {i: v for i, v in f.observed.items() if i < len(run_ids)}
        if not covered:
            continue
        best = max(covered, key=covered.get)
        facilities.append(
            AreaFacility(
                id=f.id,
                type=f.type,
                name=f.name,
                best_run=run_ids[best],
                runs=[run_ids[i] for i in covered],
                observed_core=covered[best],
                not_scanned_enough=covered[best] < min_observed,
            )
        )
    return AreaIndex(drives=drives, facilities=facilities)


def write_fake_runs(out: Path, drives: int = 2) -> list[Path]:
    """Write one synthetic run per drive under out, plus out/showcase. Returns run folders."""
    if not 1 <= drives <= len(DRIVE_SPECS):
        raise ValueError(f"drives must be 1 to {len(DRIVE_SPECS)}, got {drives}")
    out.mkdir(parents=True, exist_ok=True)
    showcase = out / "showcase"
    showcase.mkdir(exist_ok=True)
    run_ids = [_write_run(out, i, showcase) for i in range(drives)]
    (showcase / "area.json").write_text(_area(run_ids).model_dump_json(indent=2))
    return [out / rid for rid in run_ids]
