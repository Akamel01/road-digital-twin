"""Select: road lidar density and paint contrast, with go/no-go per drive.

Source of truth: docs/design/twin-v1-spec.md, section 6. The measures are pure
functions on numpy arrays and shapely polygons. scan_scenes reads nuScenes.
"""

import sys
from pathlib import Path

import numpy as np
import shapely
from pydantic import ValidationError

from twin.contracts import GroundParams, SelectParams
from twin.stages.ground import ransac_ground, surface_grid, voxel_first

VERSIONS = ("v1.0-mini", "v1.0-trainval")
LOCATION = "boston-seaport"
# Same ground settings as the features stage (ground stage defaults).
GROUND = GroundParams()
CELL_M = 5.0  # ground reference: lowest 5th percentile of z per 5 m cell
GROUND_TOL_M = 0.3  # a point counts as road if within this of that z
PAINT_PCT = 95.0  # top 5% of intensity
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


def drive_measures(xyz, intensity, road_polygons) -> tuple[float, float]:
    """Density (pts/m2) and paint contrast of one drive, measured as the features stage does.

    xyz (N, 3) and intensity (N,) hold every LIDAR_TOP sweep of the drive in one frame. Same steps as
    features: voxel-first, ground split (ground stage functions), then the area of ground cells that
    have points. DECISION: that area is also clipped to the drivable area, select's road mask.
    """
    if not road_polygons:
        return 0.0, 0.0
    keep = voxel_first(xyz, GROUND.voxel_m)
    xyz, intensity = xyz[keep], intensity[keep]
    ground = ransac_ground(xyz, GROUND)
    if not ground.any():
        return 0.0, 0.0
    cell = GROUND.qa_cell_m
    origin = xyz[:, :2].min(axis=0)
    span = np.floor((xyz[:, :2].max(axis=0) - origin) / cell).astype(int)
    shape_yx = (int(span[1]) + 1, int(span[0]) + 1)
    _zmean, count = surface_grid(
        xyz[ground, :2], xyz[ground, 2], origin, cell, shape_yx
    )
    iy, ix = np.nonzero(count > 0)
    x0, y0 = origin[0] + ix * cell, origin[1] + iy * cell
    measured = shapely.union_all(shapely.box(x0, y0, x0 + cell, y0 + cell))
    footprint = measured.intersection(shapely.union_all(road_polygons))
    gpts, gint = xyz[ground], intensity[ground]
    density = road_density(gpts, [footprint])
    on_road = road_mask(gpts, [footprint])
    return density, paint_contrast(gint[on_road])


def go(density: float, contrast: float, params: SelectParams) -> bool:
    return bool(
        density >= params.min_density_pts_m2 and contrast >= params.min_contrast
    )


def _lidar_global(nusc, sample_data: dict):
    """LIDAR_TOP sweep points in global coordinates, as (4, N) with intensity, plus ego xy."""
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


def scan_scenes(
    dataroot, params: SelectParams | None = None, version: str = "v1.0-mini"
) -> list[dict]:
    """One row per Boston scene: name, token, keyframes, sweeps, density, contrast, go."""
    from twin.devkit_compat import nuscenes_map_class

    NuScenesMap = nuscenes_map_class()
    from nuscenes.nuscenes import NuScenes

    params = params or SelectParams()
    root = Path(dataroot)
    nusc = NuScenes(version, dataroot=str(root), verbose=False)
    nusc_map = NuScenesMap(dataroot=str(root), map_name=LOCATION)
    rows = []
    for scene in nusc.scene:
        if nusc.get("log", scene["log_token"])["location"] != LOCATION:
            continue
        # Every LIDAR_TOP sweep of the scene, as the features stage reads them, not only keyframes.
        sweeps = []
        token = nusc.get("sample", scene["first_sample_token"])["data"]["LIDAR_TOP"]
        while token:
            sample_data = nusc.get("sample_data", token)
            sweeps.append(_lidar_global(nusc, sample_data))
            token = sample_data["next"]
        ego_xy = np.array([xy for _, xy in sweeps])
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

        xyz = np.concatenate([p[:3].T for p, _ in sweeps]).astype(np.float64)
        intensity = np.concatenate([p[3] for p, _ in sweeps]).astype(np.float64)
        density, contrast = drive_measures(xyz, intensity, polygons)
        rows.append(
            {
                "name": scene["name"],
                "token": scene["token"],
                "keyframes": scene["nbr_samples"],
                "sweeps": len(sweeps),
                "density": density,
                "contrast": contrast,
                "go": go(density, contrast, params),
            }
        )
    return rows


def run_select(
    dataroot: Path, min_density=None, min_contrast=None, version: str = "v1.0-mini"
) -> int:
    """Print the drive table. Returns 0, or 2 when the data or the thresholds are wrong."""
    root = Path(dataroot)
    if (
        not (root / version).is_dir()
        or not (root / "maps" / "expansion" / f"{LOCATION}.json").is_file()
    ):
        print(
            f"nuScenes {version} with map expansion not found at {root}. "
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

    rows = scan_scenes(root, params, version)
    if not rows:
        print(f"no {LOCATION} scenes under {root}")
        return 0
    print(
        f"{'scene':<14} {'token':<34} {'keyframes':>9} {'sweeps':>7} {'pts/m2':>8} {'contrast':>9}  go"
    )
    for row in rows:
        verdict = "GO" if row["go"] else "NO-GO"
        print(
            f"{row['name']:<14} {row['token']:<34} {row['keyframes']:>9} {row['sweeps']:>7} "
            f"{row['density']:>8.1f} {row['contrast']:>9.2f}  {verdict}"
        )
    print(
        f"thresholds: density >= {params.min_density_pts_m2} pts/m2, "
        f"contrast >= {params.min_contrast}"
    )
    return 0
