"""Select: road lidar density and paint contrast, with go/no-go per drive.

Source of truth: docs/design/twin-v1-spec.md, section 6. The measures are pure
functions on numpy arrays and shapely polygons. scan_scenes reads nuScenes.
"""

import sys
from pathlib import Path

import numpy as np
import shapely
from pydantic import ValidationError

from twin.contracts import SelectParams

LOCATION = "boston-seaport"
CELL_M = 5.0  # ground reference: lowest 5th percentile of z per 5 m cell
GROUND_TOL_M = 0.3  # a point counts as road if within this of that z
PAINT_PCT = 95.0  # top 5% of intensity
SWEEP_STEP = 4  # use every 4th keyframe
PATCH_PAD_M = 60.0  # map and points are read within this of the ego path


def road_mask(points_xyz, road_polygons) -> np.ndarray:
    """True for points inside the drivable area and within 0.3 m of their cell's ground z."""
    pts = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    mask = np.zeros(len(pts), dtype=bool)
    if len(pts) == 0 or not road_polygons:
        return mask
    road = shapely.union_all(road_polygons)
    idx = np.flatnonzero(shapely.contains_xy(road, pts[:, 0], pts[:, 1]))
    if idx.size == 0:
        return mask
    cells = np.floor(pts[idx, :2] / CELL_M).astype(np.int64)
    _, inverse = np.unique(cells, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    z = pts[idx, 2]
    keep = np.zeros(idx.size, dtype=bool)
    for c in range(inverse.max() + 1):
        sel = inverse == c
        ground_z = np.percentile(z[sel], 5)
        keep[sel] = np.abs(z[sel] - ground_z) <= GROUND_TOL_M
    mask[idx[keep]] = True
    return mask


def area_m2(road_polygons) -> float:
    if not road_polygons:
        return 0.0
    return float(shapely.union_all(road_polygons).area)


def road_density(points_xyz, road_polygons) -> float:
    """Road points per m² of drivable area."""
    area = area_m2(road_polygons)
    if area <= 0:
        return 0.0
    return float(road_mask(points_xyz, road_polygons).sum()) / area


def paint_contrast(intensity_on_road) -> float:
    """95th percentile intensity over median intensity. Paint is bright, asphalt dark.

    Returns 0.0 when there are no points or the median is not positive.
    """
    values = np.asarray(intensity_on_road, dtype=float).reshape(-1)
    if values.size == 0:
        return 0.0
    median = float(np.percentile(values, 50))
    if median <= 0:
        return 0.0
    return float(np.percentile(values, PAINT_PCT)) / median


def go(density: float, contrast: float, params: SelectParams) -> bool:
    return bool(
        density >= params.min_density_pts_m2 and contrast >= params.min_contrast
    )


def _lidar_global(nusc, sample_data: dict):
    """Keyframe LIDAR_TOP points in global coordinates, as (4, N) with intensity, plus ego xy."""
    from nuscenes.utils.data_classes import LidarPointCloud
    from pyquaternion import Quaternion

    pc = LidarPointCloud.from_file(nusc.get_sample_data_path(sample_data["token"]))
    cs = nusc.get("calibrated_sensor", sample_data["calibrated_sensor_token"])
    ego = nusc.get("ego_pose", sample_data["ego_pose_token"])
    pc.rotate(Quaternion(cs["rotation"]).rotation_matrix)
    pc.translate(np.array(cs["translation"]))
    pc.rotate(Quaternion(ego["rotation"]).rotation_matrix)
    pc.translate(np.array(ego["translation"]))
    return pc.points, np.array(ego["translation"][:2])


def scan_scenes(dataroot, params: SelectParams | None = None) -> list[dict]:
    """One row per Boston scene in v1.0-mini: name, token, keyframes, density, contrast, go."""
    from twin.devkit_compat import nuscenes_map_class

    NuScenesMap = nuscenes_map_class()
    from nuscenes.nuscenes import NuScenes

    params = params or SelectParams()
    root = Path(dataroot)
    nusc = NuScenes("v1.0-mini", dataroot=str(root), verbose=False)
    nusc_map = NuScenesMap(dataroot=str(root), map_name=LOCATION)
    rows = []
    for scene in nusc.scene:
        if nusc.get("log", scene["log_token"])["location"] != LOCATION:
            continue
        keyframes = []
        token = scene["first_sample_token"]
        while token:
            sample = nusc.get("sample", token)
            keyframes.append(sample)
            token = sample["next"]

        clouds, ego_xy = [], []
        for sample in keyframes[::SWEEP_STEP]:
            points, xy = _lidar_global(
                nusc, nusc.get("sample_data", sample["data"]["LIDAR_TOP"])
            )
            clouds.append(points)
            ego_xy.append(xy)
        ego_xy = np.array(ego_xy)
        x0, y0 = ego_xy.min(axis=0) - PATCH_PAD_M
        x1, y1 = ego_xy.max(axis=0) + PATCH_PAD_M

        clip = shapely.box(x0, y0, x1, y1)
        polygons = []
        hits = nusc_map.get_records_in_patch(
            (x0, y0, x1, y1), layer_names=["drivable_area"], mode="intersect"
        )
        for token in hits["drivable_area"]:
            for poly_token in nusc_map.get("drivable_area", token)["polygon_tokens"]:
                polygons.append(nusc_map.extract_polygon(poly_token).intersection(clip))

        points = np.concatenate([c[:3].T for c in clouds])
        intensity = np.concatenate([c[3] for c in clouds])
        mask = road_mask(points, polygons)
        density = road_density(points, polygons)
        contrast = paint_contrast(intensity[mask])
        rows.append(
            {
                "name": scene["name"],
                "token": scene["token"],
                "keyframes": len(keyframes),
                "density": density,
                "contrast": contrast,
                "go": go(density, contrast, params),
            }
        )
    return rows


def run_select(dataroot: Path, min_density=None, min_contrast=None) -> int:
    """Print the drive table. Returns 0, or 2 when the data or the thresholds are wrong."""
    root = Path(dataroot)
    if (
        not (root / "v1.0-mini").is_dir()
        or not (root / "maps" / "expansion" / f"{LOCATION}.json").is_file()
    ):
        print(
            f"nuScenes mini with map expansion not found at {root}. "
            "Run scripts/get_nuscenes_mini.sh or set NUSCENES_ROOT.",
            file=sys.stderr,
        )
        return 2
    overrides = {}
    if min_density is not None:
        overrides["min_density_pts_m2"] = min_density
    if min_contrast is not None:
        overrides["min_contrast"] = min_contrast
    try:
        params = SelectParams(**overrides)
    except ValidationError as err:
        print(f"invalid threshold: {err}", file=sys.stderr)
        return 2

    rows = scan_scenes(root, params)
    if not rows:
        print(f"no {LOCATION} scenes under {root}")
        return 0
    print(
        f"{'scene':<14} {'token':<34} {'keyframes':>9} {'pts/m2':>8} {'contrast':>9}  go"
    )
    for row in rows:
        verdict = "GO" if row["go"] else "NO-GO"
        print(
            f"{row['name']:<14} {row['token']:<34} {row['keyframes']:>9} "
            f"{row['density']:>8.1f} {row['contrast']:>9.2f}  {verdict}"
        )
    print(
        f"thresholds: density >= {params.min_density_pts_m2} pts/m2, "
        f"contrast >= {params.min_contrast}"
    )
    return 0
