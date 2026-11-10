"""Stage 1 load (nuscenes): sweeps, poses, boxes, map layers, facilities and cameras in the run CRS.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4 and 6.
Prior work: docs/research/devkit-py311.md (devkit map import on 3.11),
docs/research/camera-ground-projection.md (devkit transform chain, sweep and image timing).

Pure functions take plain numbers and dicts. `DevkitSource` is the only code that calls
nuscenes; `assemble` takes any object with the same five methods, so the adapter logic is
tested with a fake dataset.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import box, mapping, shape

from twin.contracts import FacilitiesParams, IsdParams, StageResult
from twin.devkit_compat import nuscenes_map_class
from twin.facilities import MapView, build_facilities, from_nuscenes_map
from twin.osm_names import fetch_streets, name_facility, osm_names_meta
from twin.parallel import pmap, savez_fast
from twin.registry import register

CRS_EPSG = 32619
# DECISION: dataset version is fixed to v1.0-mini, matching the manifest default (contracts ManifestData).
VERSION = "v1.0-mini"
LOCATION = "boston-seaport"
# DECISION: nuScenes reads data from NUSCENES_ROOT, default /data/nuscenes (as tests/itest does).
DATAROOT_DEFAULT = "/data/nuscenes"
# DECISION: shared Overpass cache at /data/osm (spec section 6); overridable with TWIN_OSM_CACHE.
OSM_CACHE_DEFAULT = "/data/osm"
# nuscenes-devkit 1.1.9 scripts/export_poses.py, line 22: REFERENCE_COORDINATES["boston-seaport"]
# is [42.336849169438615, -71.05785369873047] (lat, lon). It is the lat/lon of map (0, 0).
MAP_ORIGIN_LATLON = (42.336849169438615, -71.05785369873047)
EXTENT_MARGIN_M = 60.0
# DECISION: the four map layers the accuracy stage reads (spec section 6, Accuracy).
MAP_LAYERS = ("drivable_area", "ped_crossing", "lane_divider", "road_divider")
BOX_PREFIXES = (
    "vehicle.",
    "human.",
    "animal",
)  # dynamic agents; barriers and static objects stay in the cloud
PARKED_ATTRIBUTE = "vehicle.parked"
CAMERA_PREFIX = "CAM_"
OUTPUT_FILES = (
    "points.npz",
    "poses.json",
    "boxes.json",
    "reference.geojson",
    "facilities.geojson",
    "cameras.json",
)


# ------------------------------------------------------------------ quaternions


def _unit(q: np.ndarray) -> np.ndarray:
    return q / np.linalg.norm(q)


def quat_to_matrix(q: list[float] | np.ndarray) -> np.ndarray:
    """Rotation matrix from a [w, x, y, z] quaternion (nuScenes order)."""
    w, x, y, z = _unit(np.asarray(q, dtype=float))
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def yaw_of(q: list[float] | np.ndarray) -> float:
    w, x, y, z = _unit(np.asarray(q, dtype=float))
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def qz(theta: float) -> np.ndarray:
    """Quaternion for a rotation of theta about +z."""
    return np.array([math.cos(theta / 2), 0.0, 0.0, math.sin(theta / 2)])


def qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )

    # DECISION: slerp in numpy, not pyquaternion (a devkit transitive dependency, not pinned here).


def slerp(q0: list[float], q1: list[float], s: float) -> np.ndarray:
    """Spherical linear interpolation along the shorter arc."""
    a, b = _unit(np.asarray(q0, dtype=float)), _unit(np.asarray(q1, dtype=float))
    d = float(np.dot(a, b))
    if d < 0:  # q and -q are the same rotation; take the shorter way round
        b, d = -b, -d
    if d > 0.9995:  # nearly equal: linear is exact enough and avoids sin(0)
        return _unit(a + s * (b - a))
    theta = math.acos(min(1.0, d))
    return (math.sin((1 - s) * theta) * a + math.sin(s * theta) * b) / math.sin(theta)


def pose_matrix(translation: list[float], rotation: list[float]) -> np.ndarray:
    """4x4 from a translation and a [w, x, y, z] rotation."""
    m = np.eye(4)
    m[:3, :3] = quat_to_matrix(rotation)
    m[:3, 3] = translation
    return m


# ------------------------------------------------------------------ georeference


def run_crs(map_origin_latlon: tuple[float, float]) -> Transformer:
    """Local transverse Mercator centred on the map origin, to UTM 19N (EPSG:32619).

    Map (0, 0) is the origin itself. Offsets are never added straight onto UTM: the local
    projection keeps grid convergence, about 1.3 degrees at Boston (spec section 3).
    """
    lat, lon = map_origin_latlon
    local = f"+proj=tmerc +lat_0={lat} +lon_0={lon} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m"
    return Transformer.from_crs(local, f"EPSG:{CRS_EPSG}", always_xy=True)


def convergence(tr: Transformer, x: float, y: float) -> float:
    """Angle (radians) of the local east axis as it appears in the run CRS, at (x, y)."""
    x0, y0 = tr.transform(x, y)
    x1, y1 = tr.transform(x + 1.0, y)
    return math.atan2(y1 - y0, x1 - x0)

    # DECISION: poses are rigid in run CRS: translation through the transform, yaw turned by convergence; the sub-0.01% scale of the tmerc->UTM map is ignored.


def to_run_pose(m: np.ndarray, tr: Transformer) -> np.ndarray:
    """Dataset 4x4 (map frame) to run CRS: translation through the transform, rotation
    turned by the grid convergence at the pose."""
    x, y = float(m[0, 3]), float(m[1, 3])
    xu, yu = tr.transform(x, y)
    out = np.eye(4)
    out[:3, :3] = quat_to_matrix(qz(convergence(tr, x, y))) @ m[:3, :3]
    out[:3, 3] = [xu, yu, m[2, 3]]
    return out


def to_run_box(box_d: dict, tr: Transformer) -> dict:
    x, y = box_d["center"][0], box_d["center"][1]
    xu, yu = tr.transform(x, y)
    rot = qmul(
        qz(convergence(tr, x, y)), _unit(np.asarray(box_d["rotation"], dtype=float))
    )
    return {
        **box_d,
        "center": [float(xu), float(yu), float(box_d["center"][2])],
        "rotation": [float(v) for v in rot],
        "yaw": yaw_of(rot),
    }


# ------------------------------------------------------------------ sweeps


def sweep_to_global(
    points_sensor: np.ndarray, calibrated_sensor: dict, ego_pose: dict
) -> np.ndarray:
    """(N, >=3) sensor-frame points to (N, 3) global (map) frame, via ego."""
    t_ego_sensor = pose_matrix(
        calibrated_sensor["translation"], calibrated_sensor["rotation"]
    )
    t_global_ego = pose_matrix(ego_pose["translation"], ego_pose["rotation"])
    t = t_global_ego @ t_ego_sensor
    p = np.asarray(points_sensor, dtype=float)[:, :3]
    return p @ t[:3, :3].T + t[:3, 3]

    # DECISION: sweep pose is the ego pose at the sweep timestamp (dataset, map frame); z is the ego z from nuScenes (0 by schema).


def sweep_matrix(rec: dict) -> np.ndarray:
    """Dataset 4x4, ego to map frame, for one sweep."""
    return pose_matrix(rec["ego_pose"]["translation"], rec["ego_pose"]["rotation"])


# ------------------------------------------------------------------ boxes


def interpolate_box(box_a: dict, box_b: dict, t_a: int, t_b: int, t: int) -> dict:
    """Centre, size and yaw interpolated between two keyframe boxes at time t.

    Each box is {"center", "size", "rotation" ([w,x,y,z]), "parked"}. Centre and size are
    linear, rotation is slerp. Raises outside [t_a, t_b]: boxes are not extrapolated.
    """
    if not t_a <= t <= t_b:
        raise ValueError(
            f"t={t} is outside keyframes [{t_a}, {t_b}]; boxes are not extrapolated"
        )
    s = 0.0 if t_b == t_a else (t - t_a) / (t_b - t_a)
    center = (1 - s) * np.asarray(box_a["center"], float) + s * np.asarray(
        box_b["center"], float
    )
    size = (1 - s) * np.asarray(box_a["size"], float) + s * np.asarray(
        box_b["size"], float
    )
    rot = slerp(box_a["rotation"], box_b["rotation"], s)
    # DECISION: parked comes from the nearer keyframe; an exact midpoint takes the earlier one.
    parked = box_a["parked"] if (t - t_a) <= (t_b - t) else box_b["parked"]
    return {
        "center": center.tolist(),
        "size": size.tolist(),
        "rotation": rot.tolist(),
        "parked": bool(parked),
    }

    # DECISION: boxes cover vehicle.*, human.* and animal (all dynamic agents). movable_object.* (barriers, cones) and static_object.* stay in the cloud, because they block sight.


def dynamic_tracks(keyframes: list[dict]) -> dict[str, list[tuple[int, dict]]]:
    """Keyframe dynamic-agent annotations grouped by instance token, sorted by time.

    keyframes: [{"timestamp": us, "anns": [{"instance", "category", "center", "size",
    "rotation", "parked"}]}]. Only categories under BOX_PREFIXES are kept.
    """
    tracks: dict[str, list[tuple[int, dict]]] = {}
    for kf in keyframes:
        for ann in kf["anns"]:
            if not ann["category"].startswith(BOX_PREFIXES):
                continue
            tracks.setdefault(ann["instance"], []).append((kf["timestamp"], ann))
    for track in tracks.values():
        track.sort(key=lambda pair: pair[0])
    return tracks

    # DECISION: boxes are interpolated per sweep in the map frame, then converted to run CRS (centre via transform, rotation via qz(convergence) * q).


def boxes_per_sweep(
    tracks: dict[str, list[tuple[int, dict]]], sweep_times: list[int]
) -> list[list[dict]]:
    """For each sweep, the interpolated boxes in the map frame.

    A sweep uses the keyframe pair with t_a <= t < t_b. The last keyframe's own time is
    included on the last pair, so a sweep exactly on it gets its box.
    """
    out: list[list[dict]] = [[] for _ in sweep_times]
    for token, track in tracks.items():
        last_t = track[-1][0]
        for (ta, a), (tb, b) in itertools.pairwise(track):
            for i, t in enumerate(sweep_times):
                if ta <= t < tb or (tb == last_t and t == tb):
                    geo = interpolate_box(a, b, ta, tb, t)
                    out[i].append({"token": token, "category": a["category"], **geo})
    return out


# ------------------------------------------------------------------ map and facilities


def _warp(geom: Any, tr: Transformer) -> Any:
    """Map-frame shapely geometry to the run CRS (2D)."""
    return shapely.transform(
        geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1]))
    )


def _run_geom(geom: dict, tr: Transformer) -> dict:
    return mapping(_warp(shape(geom), tr))


def to_run_facility(rec: dict, tr: Transformer) -> dict:
    """A facility record from twin.facilities, with every geometry in the run CRS."""
    out = {k: v for k, v in rec.items()}
    out["core"] = _run_geom(rec["core"], tr)
    if "centreline" in rec:
        out["centreline"] = _run_geom(rec["centreline"], tr)
    if "legs" in rec:
        out["legs"] = [
            {**leg, "geometry": _run_geom(leg["geometry"], tr)} for leg in rec["legs"]
        ]
    if "eye_points" in rec:
        out["eye_points"] = [
            {**eye, "geometry": _run_geom(eye["geometry"], tr)}
            for eye in rec["eye_points"]
        ]
    return out


def osm_cache_dir() -> Path:
    """Shared Overpass cache (spec section 6): /data/osm, or TWIN_OSM_CACHE."""
    return Path(os.environ.get("TWIN_OSM_CACHE") or OSM_CACHE_DEFAULT)


def name_facilities(
    facilities: list[dict],
    streets: list | None,
) -> list[str]:
    """Display name per facility: the OSM street name, else the facility ID."""
    names = []
    for rec in facilities:
        try:
            name = name_facility(rec, streets) if streets is not None else None
        except Exception:  # noqa: BLE001 # DECISION: best-effort naming; a bad geometry keeps the ID
            name = None
        names.append(name or rec["id"])
    return names


def wgs84_bbox(patch: tuple[float, float, float, float], tr: Transformer) -> tuple:
    """(west, south, east, north) in WGS84 for a map-frame patch."""
    x0, y0, x1, y1 = patch
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    utm = [tr.transform(x, y) for x, y in corners]
    to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)
    ll = [to_ll.transform(x, y) for x, y in utm]
    lons, lats = [p[0] for p in ll], [p[1] for p in ll]
    return (min(lons), min(lats), max(lons), max(lats))


def reference_features(
    layers: list[tuple[str, str, Any]],
    patch: tuple[float, float, float, float],
    tr: Transformer,
) -> list[dict]:
    """Map layers clipped to the patch, in the run CRS. layers: (layer, token, map-frame geometry)."""
    clip = box(*patch)
    feats = []
    for layer, token, geom in layers:
        part = geom.intersection(clip)
        if part.is_empty:
            continue
        part = _warp(part, tr)
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(part),
                "properties": {"layer": layer, "token": token},
            }
        )
    return feats


# ------------------------------------------------------------------ scene assembly


@dataclass
# DECISION: points are kept in run CRS with z as nuScenes z (ego-relative to map ground); no height offset is applied.
class LoadedScene:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    intensity: np.ndarray
    sweep: np.ndarray
    sweeps: list[dict]  # per sweep: index, token, timestamp_us, matrix (run CRS)
    boxes: list[list[dict]]  # per sweep, run CRS
    cameras: list[dict]
    reference: list[dict]
    facilities: list[dict]  # run CRS, unnamed
    extent: tuple[float, float, float, float] = field(default=(0.0, 0.0, 0.0, 0.0))

    # DECISION: facility defaults (IsdParams, FacilitiesParams) are used because load has no parameters (spec section 4).


_SWEEP_JOB: tuple[Any, Transformer, list[dict]] | None = None  # read by forked workers


def _load_sweep(i: int) -> tuple:
    source, tr, recs = _SWEEP_JOB  # type: ignore[misc]
    rec = recs[i]
    pts = np.asarray(source.sweep_points(rec), dtype=float)
    g = sweep_to_global(pts[:, :3], rec["calibrated_sensor"], rec["ego_pose"])
    xu, yu = tr.transform(g[:, 0], g[:, 1])
    m = sweep_matrix(rec)
    info = {
        "sweep": i,
        "token": rec["token"],
        "timestamp_us": int(rec["timestamp"]),
        "matrix": to_run_pose(m, tr).tolist(),
    }
    return (
        np.asarray(xu, float),
        np.asarray(yu, float),
        g[:, 2],
        pts[:, 3].astype(np.float32),
        np.full(len(pts), i, dtype=np.uint16),
        info,
        m[:2, 3],
    )


def assemble(
    source: Any, scene_token: str, tr: Transformer, workers: int | None = None
) -> LoadedScene:
    """Everything the stage writes, built from `source` (the small interface in DevkitSource)."""
    recs = source.sweep_records(scene_token)
    global _SWEEP_JOB
    _SWEEP_JOB = (source, tr, recs)
    try:
        # Sweeps are independent; results come back in sweep order, so any worker count gives the same arrays.
        done = pmap(_load_sweep, range(len(recs)), workers)
    finally:
        _SWEEP_JOB = None
    xs, ys, zs, ints, sws, sweeps, egos = ([d[k] for d in done] for k in range(7))

    ego_xy = np.asarray(egos)
    lo, hi = ego_xy.min(axis=0), ego_xy.max(axis=0)
    # DECISION: the extent is the sweep ego positions plus 60 m, in the map frame.
    patch = (
        float(lo[0] - EXTENT_MARGIN_M),
        float(lo[1] - EXTENT_MARGIN_M),
        float(hi[0] + EXTENT_MARGIN_M),
        float(hi[1] + EXTENT_MARGIN_M),
    )

    # DECISION: sweeps before the first keyframe are not in the sweep chain (chain starts at the first keyframe's LIDAR_TOP).
    tracks = dynamic_tracks(source.keyframes(scene_token))
    per_sweep = boxes_per_sweep(tracks, [int(r["timestamp"]) for r in recs])
    boxes = [[to_run_box(b, tr) for b in group] for group in per_sweep]

    view = source.map_view(patch)
    fac_recs = build_facilities(view, IsdParams(), FacilitiesParams())
    facilities = [to_run_facility(r, tr) for r in fac_recs]

    return LoadedScene(
        x=np.concatenate(xs) if xs else np.zeros(0),
        y=np.concatenate(ys) if ys else np.zeros(0),
        z=np.concatenate(zs) if zs else np.zeros(0),
        intensity=np.concatenate(ints) if ints else np.zeros(0, np.float32),
        sweep=np.concatenate(sws) if sws else np.zeros(0, np.uint16),
        sweeps=sweeps,
        boxes=boxes,
        cameras=source.cameras(scene_token),
        reference=reference_features(source.map_layers(patch), patch, tr),
        facilities=facilities,
        extent=patch,
    )


def _fc(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": f"EPSG:{CRS_EPSG}"}},
        "features": features,
    }


def write_outputs(out: Path, scene: LoadedScene, names: list[str]) -> None:
    savez_fast(
        out / "points.npz",
        # DECISION: x, y, z as float64 (UTM northings near 4.7e6 m lose metres in float32); sweep stored as uint16 (a 20 s scene has about 400 sweeps, more than uint8 holds).
        x=scene.x.astype(np.float64),  # float64: UTM northings near 4.7e6 m need it
        y=scene.y.astype(np.float64),
        z=scene.z.astype(np.float64),
        intensity=scene.intensity.astype(np.float32),
        sweep=scene.sweep.astype(np.uint16),
    )
    (out / "poses.json").write_text(
        json.dumps({"crs": f"EPSG:{CRS_EPSG}", "poses": scene.sweeps})
    )
    sweeps = [
        {"sweep": i, "timestamp_us": scene.sweeps[i]["timestamp_us"], "boxes": group}
        for i, group in enumerate(scene.boxes)
    ]
    (out / "boxes.json").write_text(
        json.dumps({"crs": f"EPSG:{CRS_EPSG}", "sweeps": sweeps})
    )
    (out / "reference.geojson").write_text(json.dumps(_fc(scene.reference)))

    feats = []
    for rec, name in zip(scene.facilities, names):
        props = {k: v for k, v in rec.items() if k != "core"}
        props["name"] = name
        feats.append({"type": "Feature", "geometry": rec["core"], "properties": props})
    (out / "facilities.geojson").write_text(json.dumps(_fc(feats)))
    (out / "cameras.json").write_text(json.dumps({"cameras": scene.cameras}))


# ------------------------------------------------------------------ devkit adapter


class DevkitSource:
    """The nuScenes devkit behind the five methods `assemble` uses. Reads plain dicts."""

    def __init__(self, dataroot: str):
        from nuscenes.nuscenes import NuScenes

        self.root = dataroot
        self.nusc = NuScenes(VERSION, dataroot=dataroot, verbose=False)
        self._map: Any = None

    def _map_api(self) -> Any:
        if self._map is None:
            NuScenesMap = nuscenes_map_class()
            self._map = NuScenesMap(dataroot=self.root, map_name=LOCATION)
        return self._map

    def sweep_records(self, scene_token: str) -> list[dict]:
        """LIDAR_TOP sweeps of the scene, in time order, every sweep (not only keyframes)."""
        nusc = self.nusc
        scene = nusc.get("scene", scene_token)
        first = nusc.get("sample", scene["first_sample_token"])
        token = first["data"]["LIDAR_TOP"]
        out = []
        while token:
            rec = nusc.get("sample_data", token)
            out.append(
                {
                    "token": token,
                    "timestamp": rec["timestamp"],
                    "path": os.path.join(self.root, rec["filename"]),
                    "calibrated_sensor": nusc.get(
                        "calibrated_sensor", rec["calibrated_sensor_token"]
                    ),
                    "ego_pose": nusc.get("ego_pose", rec["ego_pose_token"]),
                }
            )
            token = rec["next"]
        return out

    # DECISION: intensity is the raw 0-255 value from the file (not normalised).
    def sweep_points(self, rec: dict) -> np.ndarray:
        """(N, 4) x, y, z, intensity. Intensity is the raw 0-255 value from the file."""
        from nuscenes.utils.data_classes import LidarPointCloud

        return LidarPointCloud.from_file(rec["path"]).points.T

    def keyframes(self, scene_token: str) -> list[dict]:
        nusc = self.nusc
        sample_token = nusc.get("scene", scene_token)["first_sample_token"]
        out = []
        while sample_token:
            sample = nusc.get("sample", sample_token)
            anns = []
            for ann_token in sample["anns"]:
                ann = nusc.get("sample_annotation", ann_token)
                inst = nusc.get("instance", ann["instance_token"])
                category = nusc.get("category", inst["category_token"])["name"]
                attrs = [
                    nusc.get("attribute", a)["name"] for a in ann["attribute_tokens"]
                ]
                anns.append(
                    {
                        "instance": ann["instance_token"],
                        "category": category,
                        "center": ann["translation"],
                        "size": ann["size"],
                        "rotation": ann["rotation"],
                        "parked": PARKED_ATTRIBUTE in attrs,
                    }
                )
            out.append({"timestamp": sample["timestamp"], "anns": anns})
            sample_token = sample["next"]
        return out

    # DECISION: cameras are the keyframe samples' CAM_* records only (6 per keyframe); extrinsics are relative to the ego body frame, which is not georeferenced, so they are not converted.
    def cameras(self, scene_token: str) -> list[dict]:
        nusc = self.nusc
        out = []
        sample_token = nusc.get("scene", scene_token)["first_sample_token"]
        while sample_token:
            sample = nusc.get("sample", sample_token)
            for channel, sd_token in sorted(sample["data"].items()):
                if not channel.startswith(CAMERA_PREFIX):
                    continue
                sd = nusc.get("sample_data", sd_token)
                cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
                out.append(
                    {
                        "channel": channel,
                        "sample_token": sample_token,
                        "timestamp_us": int(sd["timestamp"]),
                        "image": sd["filename"],
                        "intrinsics": cs["camera_intrinsic"],
                        "extrinsics": {
                            "translation": cs["translation"],
                            "rotation_wxyz": cs["rotation"],
                        },
                    }
                )
            sample_token = sample["next"]
        return out

    def map_view(self, patch: tuple[float, float, float, float]) -> MapView:
        return from_nuscenes_map(self._map_api(), patch)

    def map_layers(
        self, patch: tuple[float, float, float, float]
    ) -> list[tuple[str, str, Any]]:
        from shapely.geometry import LineString

        nm = self._map_api()
        recs = nm.get_records_in_patch(patch, list(MAP_LAYERS), mode="intersect")
        out: list[tuple[str, str, Any]] = []
        for layer in ("lane_divider", "road_divider"):
            for tok in recs[layer]:
                line = nm.extract_line(nm.get(layer, tok)["line_token"])
                out.append((layer, tok, LineString(line.coords)))
        for tok in recs["drivable_area"]:
            for poly_tok in nm.get("drivable_area", tok)["polygon_tokens"]:
                out.append(("drivable_area", poly_tok, nm.extract_polygon(poly_tok)))
        for tok in recs["ped_crossing"]:
            poly_tok = nm.get("ped_crossing", tok)["polygon_token"]
            out.append(("ped_crossing", tok, nm.extract_polygon(poly_tok)))
        return out

    # DECISION: `params` is accepted for signature parity and unused; the load stage has no params in spec section 4.


def load_scene(dataroot: str, scene_token: str, params: Any = None) -> LoadedScene:
    """Adapter entry point. `params` only supplies `workers` (None or absent: the default)."""
    return assemble(
        DevkitSource(dataroot),
        scene_token,
        run_crs(MAP_ORIGIN_LATLON),
        getattr(params, "workers", None),
    )


# ------------------------------------------------------------------ stage


@register("load", "nuscenes")
def run(ctx: Any, params: Any) -> StageResult:
    out: Path = ctx.stage_dir("load")
    out.mkdir(exist_ok=True)
    dataroot = os.environ.get("NUSCENES_ROOT", DATAROOT_DEFAULT)
    tr = run_crs(MAP_ORIGIN_LATLON)
    scene = load_scene(dataroot, ctx.scene_token, params)

    # Names: one cached Overpass query. Any network or parse error leaves IDs as names.
    streets, query_date = None, None
    try:
        streets, query_date = fetch_streets(
            wgs84_bbox(scene.extent, tr), osm_cache_dir()
        )
    except Exception as exc:  # noqa: BLE001 # DECISION: names are best-effort; any failure keeps facility IDs
        ctx.log.warning("osm names unavailable, using facility IDs: %s", exc)
    names = name_facilities(scene.facilities, streets)
    write_outputs(out, scene, names)

    # DECISION: on network or parse failure no query date exists, so metrics osm_names is None and names fall back to IDs. Runner must allow data.osm_names null (contract currently requires it).
    osm = None
    if query_date is not None:
        meta = osm_names_meta(query_date)
        # Runner lifts this into manifest data.osm_names (see PR notes).
        osm = {
            "overpass_query_date": meta["overpass_query_date"].isoformat(),
            "licence": meta["licence"],
        }
    return StageResult(
        status="ok",
        files=list(OUTPUT_FILES),
        metrics={
            "n_sweeps": len(scene.sweeps),
            "n_points": len(scene.x),
            "n_facilities": len(scene.facilities),
            "osm_names": osm,
        },
    )
