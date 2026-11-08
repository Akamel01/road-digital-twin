"""Write synthetic run folders and a showcase bundle that match twin.contracts.

Nothing reads sensor data. Geometry comes from twin.fixtures; every other value
is a constant or derived from one, so the output is the same on every call.
Runs are never overwritten, so an existing run folder is an error.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import ezdxf
import laspy
import numpy as np
import yaml
from matplotlib.figure import Figure
from PIL import Image

from twin import fixtures as fx
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
SOURCE_LINE = "Source: synthetic fixture (fake-run), not nuScenes data"
LICENCE_LINE = "Licence: CC BY-NC-SA 4.0 for derived outputs"


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
    coverage[ortho[..., 3] > 0] = (0, 150, 140, 160)
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
        legs = {"intersection": ["north", "east"], "access_point": ["exit"]}.get(
            f.type, []
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
                eye_point=_p3((x0 + x1) / 2, y0, 0)[:2],
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
    return {"load": {"points": len(pts), "sweeps": N_SWEEPS, "facilities": len(facs)}}


def _mask(d: Path, c: _Ctx) -> dict:
    pts, sweep = _all(c)
    parked = _in_box(pts, PARKED_BOX)
    moving = _in_box(pts, MOVING_BOX)
    keep = ~(parked | moving)
    np.savez_compressed(d / "points.npz", **_cols(pts[keep], sweep[keep]))
    np.savez_compressed(d / "parked.npz", **_cols(pts[parked], sweep[parked]))
    return {
        "mask": {
            "kept": int(keep.sum()),
            "removed": int((~keep).sum()),
            "parked": int(parked.sum()),
        }
    }


def _align(d: Path, c: _Ctx) -> dict:
    dx, dy = 0.012 + 0.005 * c.index, -0.004
    _dump(d / "poses.json", _pose_doc(dx, dy))
    _dump(d / "qa.json", {"x_drift_m": dx, "y_drift_m": dy, "fallback_used": False})
    return {"align": {"x_drift_m": dx, "y_drift_m": dy}}


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
    ground = {
        "rmse_m": round(rmse, 4),
        "z_disagreement_p95_m": round(p95, 4),
        "height_valid": True,
    }
    _dump(d / "qa.json", {**ground, "observed_core": c.observed})
    return {"ground": ground, "observed_core": c.observed}


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
                n_points=int(inside.sum()),
            )
        )
    _dump(d / "markings.geojson", _fc(markings))
    _dump(d / "crosswalks.geojson", _fc([]))
    curb_pts = int(np.sum(np.isclose(c.plane[:, 1], fx.CURB_Y)))
    curb = _feat(
        "LineString",
        [_p3(x, fx.CURB_Y, fx.ground_z(x, fx.CURB_Y)) for x in (0.0, 40.0)],
        id="C-1",
        kind="curb",
        n_points=curb_pts,
    )
    _dump(d / "curbs.geojson", _fc([curb]))
    return {"features": {"markings": len(markings), "crosswalks": 0, "curbs": 1}}


def _colour(d: Path, c: _Ctx) -> dict:
    Image.fromarray(c.rasters["ortho"]).save(d / "ortho.png")
    ul_e = ORIGIN_E + RASTER_ORIGIN[0]
    ul_n = ORIGIN_N + RASTER_ORIGIN[1] + RASTER_CELLS * RASTER_M
    pgw = [RASTER_M, 0.0, 0.0, -RASTER_M, ul_e + RASTER_M / 2, ul_n - RASTER_M / 2]
    (d / "ortho.pgw").write_text("\n".join(f"{v:.6f}" for v in pgw) + "\n")
    rgb = _class_colour(c.plane)
    observed = (c.plane[:, 0] <= OBSERVED_MAX_X).astype(np.uint8)
    np.savez_compressed(
        d / "rgb.npz",
        x=c.plane[:, 0].astype(np.float32),
        y=c.plane[:, 1].astype(np.float32),
        z=c.plane[:, 2].astype(np.float32),
        r=rgb[:, 0],
        g=rgb[:, 1],
        b=rgb[:, 2],
        observed=observed,
    )
    colour = {
        "edge_offset_p95_m": round(0.04 + 0.01 * c.index, 3),
        "views_median": 3,
        "height_valid": True,
    }
    _dump(d / "qa.json", colour)
    return {"colour": colour}


def _profile(d: Path, c: _Ctx) -> dict:
    rows = ["facility,s_m,z_m,n"]
    feats = []
    for f in c.facilities:
        x0, x1, y0, y1 = f.core
        yc = (y0 + y1) / 2
        coords = []
        for s in np.arange(0.0, x1 - x0 + 1e-9, 1.0):
            x = x0 + float(s)
            z = float(fx.ground_z(x, yc))
            rows.append(f"{f.id},{s:.1f},{z:.3f},20")
            coords.append(_p3(x, yc, z))
        feats.append(_feat("LineString", coords, facility=f.id))
    (d / "profile.csv").write_text("\n".join(rows) + "\n")
    _dump(d / "centrelines.geojson", _fc(feats))
    return {}


def _isd(d: Path, c: _Ctx) -> dict:
    facs = []
    for f in c.facilities:
        names = {"intersection": ["north", "east"], "access_point": ["exit"]}.get(
            f.type, []
        )
        not_scanned = c.observed[f.id] < Params().facilities.min_observed
        legs = []
        for k, name in enumerate(names):
            if not_scanned:
                status, reason = "indeterminate", "facility not scanned enough"
            elif ISD_AVAILABLE_M - 10 * k >= ISD_REQUIRED_M:
                status, reason = "ok", f"with parked vehicles {ISD_PARKED_M} m"
            else:
                status, reason = "short", f"with parked vehicles {ISD_PARKED_M} m"
            legs.append(
                {
                    "leg": name,
                    "required_m": ISD_REQUIRED_M,
                    "available_m": ISD_AVAILABLE_M - 10 * k,
                    "available_with_parked_m": ISD_PARKED_M,
                    "status": status,
                    "reason": reason,
                }
            )
        facs.append({"facility": f.id, "legs": legs})
    doc = {"case": "B1", "facilities": facs}
    _dump(d / "isd.json", doc)
    return {"isd": doc}


def _entry(
    layer: str, p50: float, p95: float, cov: float, n: int, label: str = ""
) -> dict:
    return {
        "reference_layer": layer,
        "p50_m": round(p50, 3),
        "p95_m": round(p95, 3),
        "coverage": round(cov, 3),
        "n": n,
        "label": label,
    }


def _accuracy(d: Path, c: _Ctx) -> dict:
    base = 0.01 * c.index
    elements = {
        "markings": _entry("lane_divider", 0.05 + base, 0.13 + base, 0.71, 42),
        "crosswalks": _entry("ped_crossing", 0.07 + base, 0.18 + base, 0.5, 0),
        "curbs": _entry(
            "drivable_area", 0.08 + base, 0.21 + base, 0.64, 18, "map-conditioned"
        ),
    }
    facilities = {
        f.id: _entry("drivable_area", 0.09 + base, 0.2 + base, c.observed[f.id], 10)
        for f in c.facilities
    }
    doc = {"elements": elements, "facilities": facilities}
    _dump(d / "accuracy.json", doc)
    return {"accuracy": doc}


def _outputs(d: Path, c: _Ctx) -> dict:
    pts, _ = _all(c)
    _las(d / "twin.laz", pts, classification=2, rgb=_class_colour(pts))
    feats = []
    for name in ("markings", "crosswalks", "curbs"):
        feats += json.loads((d.parent / "05_features" / f"{name}.geojson").read_text())[
            "features"
        ]
    _dump(d / "twin.geojson", _fc(feats))
    lines = [[(p[0], p[1]) for p in f["geometry"]["coordinates"]] for f in feats]
    _plan_dxf(d / "plan.dxf", lines)
    _plan_pdf(d / "plan.pdf", lines)
    profile = json.loads((d.parent / "07_profile" / "centrelines.geojson").read_text())
    prof = [
        [(p[0] - ORIGIN_E, p[2]) for p in f["geometry"]["coordinates"]]
        for f in profile["features"]
    ]
    _profile_dxf(d / "profile.dxf", prof)
    _profile_pdf(d / "profile.pdf", prof)
    return {}


def _plan_dxf(path: Path, lines: list) -> None:
    doc = ezdxf.new("R2013")
    doc.layers.add("MARKINGS")
    msp = doc.modelspace()
    for coords in lines:
        msp.add_lwpolyline(coords, dxfattribs={"layer": "MARKINGS"})
    msp.add_text(
        SOURCE_LINE, dxfattribs={"height": 0.5, "insert": (ORIGIN_E, ORIGIN_N - 2)}
    )
    msp.add_text(
        LICENCE_LINE, dxfattribs={"height": 0.5, "insert": (ORIGIN_E, ORIGIN_N - 3)}
    )
    doc.saveas(path)


def _plan_pdf(path: Path, lines: list) -> None:
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    for coords in lines:
        xs, ys = zip(*coords)
        ax.plot([x - ORIGIN_E for x in xs], [y - ORIGIN_N for y in ys], color="black")
    ax.plot([0, 10], [-2, -2], color="black", linewidth=3)
    ax.text(0, -2.8, "10 m scale bar")
    ax.annotate(
        "N", xy=(38, 18), xytext=(38, 12), ha="center", arrowprops={"arrowstyle": "->"}
    )
    ax.set_aspect("equal")
    fig.text(0.05, 0.02, f"{SOURCE_LINE}. {LICENCE_LINE}.", fontsize=7)
    fig.savefig(path, format="pdf")


def _profile_dxf(path: Path, profiles: list) -> None:
    doc = ezdxf.new("R2013")
    msp = doc.modelspace()
    for coords in profiles:
        msp.add_lwpolyline([(s, z) for s, z in coords])
    msp.add_text(
        "Descriptive ground profile (not an accuracy claim)",
        dxfattribs={"height": 0.5, "insert": (0, -1)},
    )
    doc.saveas(path)


def _profile_pdf(path: Path, profiles: list) -> None:
    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(111)
    for coords in profiles:
        ax.plot([s for s, _ in coords], [z for _, z in coords])
    ax.set_xlabel("distance along centreline (m)")
    ax.set_ylabel("ground z (m)")
    fig.text(0.05, 0.02, f"{SOURCE_LINE}. {LICENCE_LINE}.", fontsize=7)
    fig.savefig(path, format="pdf")


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
        folder = run_dir / f"{STAGES[name].number:02d}_{name}"
        folder.mkdir()
        stage_metrics = WRITERS[name](folder, ctx)
        metrics.update(stage_metrics)
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
    shutil.copy(
        run_dir / "10_outputs" / "twin.geojson", showcase / run_id / "twin.geojson"
    )
    shutil.copy(run_dir / "manifest.json", showcase / run_id / "manifest.json")
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
