"""Area build -> recon-core Posed Capture adapter.

Writes a recon-core Posed Capture (capture.json, colmap/, lidar.laz) from an
area merge output. images/ holds absolute symlinks into the nuScenes
dataroot. Coordinates are local metres: absolute merged EPSG:32619 xyz minus a
deterministic origin_offset = [floor(min x), floor(min y), 0.0].

Pose conventions (verified from twin code):
- cameras.json extrinsics are ego->camera: {"translation", "rotation_wxyz"}
  (nuScenes calibrated_sensor, relative to ego body). See twin/stages/load.py
  DevkitSource.cameras and twin/stages/zbuffer.py camera_to_world.
- 3_align/poses.json matrices are ego->world in the run CRS (EPSG:32619), the
  refined sweep poses. See twin/stages/align.py _write and twin/areatwin.py
  stand-in identity poses.
- T_world_cam = T_world_ego(nearest sweep by timestamp_us) @ T_ego_cam.
- COLMAP images.txt stores world->camera (qvec, tvec) where X_cam = R*X_world + t,
  R from qvec, t = -R*C, C = camera center in world. This matches
  twin/stages/zbuffer.py project(): cam = R_cw^T (p - C).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from twin.areastore import open_area
from twin.contracts import stage_dir
from twin.dataset import DatasetConfig
from twin.runner import default_store

EPSG = 32619
DATA_LICENCE = "CC BY-NC-SA"
IMAGE_WIDTH = 1600
IMAGE_HEIGHT = 900
COLMAP_DIR = "colmap"
IMAGES_DIR = "images"
CAPTURE_FILE = "capture.json"
LIDAR_FILE = "lidar.laz"


def area_origin(x: np.ndarray, y: np.ndarray) -> list[float]:
    """Deterministic local origin: floor(min x/y), z 0."""
    return [float(math.floor(float(np.min(x)))), float(math.floor(float(np.min(y)))), 0.0]


def _quat_to_matrix(q: list[float] | tuple[float, ...] | np.ndarray) -> np.ndarray:
    """[w, x, y, z] -> 3x3 rotation matrix."""
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if n == 0:
        raise ValueError("zero quaternion")
    w, x, y, z = q / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def _matrix_to_qvec(R: np.ndarray) -> tuple[float, float, float, float]:
    """3x3 rotation matrix -> COLMAP qvec [qw, qx, qy, qz], world->camera."""
    tr = float(R[0, 0] + R[1, 1] + R[2, 2])
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        qw = 0.25 * s
        qx = (R[2, 1] - R[1, 2]) / s
        qy = (R[0, 2] - R[2, 0]) / s
        qz = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        qw = (R[2, 1] - R[1, 2]) / s
        qx = 0.25 * s
        qy = (R[0, 1] + R[1, 0]) / s
        qz = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        qw = (R[0, 2] - R[2, 0]) / s
        qx = (R[0, 1] + R[1, 0]) / s
        qy = 0.25 * s
        qz = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        qw = (R[1, 0] - R[0, 1]) / s
        qx = (R[0, 2] + R[2, 0]) / s
        qy = (R[1, 2] + R[2, 1]) / s
        qz = 0.25 * s
    q = np.array([qw, qx, qy, qz], dtype=float)
    q /= np.linalg.norm(q)
    return tuple(float(v) for v in q)


def _pose_matrix(translation: list[float] | np.ndarray, rotation_wxyz: list[float] | np.ndarray) -> np.ndarray:
    m = np.eye(4, dtype=float)
    m[:3, :3] = _quat_to_matrix(rotation_wxyz)
    m[:3, 3] = np.asarray(translation, dtype=float)
    return m


def world_camera(ego_world: np.ndarray, extrinsics: dict) -> np.ndarray:
    """T_world_cam = T_world_ego @ T_ego_cam."""
    T_ego_cam = _pose_matrix(extrinsics["translation"], extrinsics["rotation_wxyz"])
    return np.asarray(ego_world, dtype=float) @ T_ego_cam


def nearest_pose(poses: np.ndarray, stamps: list[int] | np.ndarray, t_us: int) -> np.ndarray:
    """Nearest ego->world pose by timestamp_us."""
    stamps = np.asarray(stamps, dtype=np.int64)
    if stamps.size == 0:
        raise ValueError("no poses")
    idx = int(np.argmin(np.abs(stamps - int(t_us))))
    return np.asarray(poses[idx], dtype=float).reshape(4, 4)


def _colmap_w2c(T_world_cam: np.ndarray) -> tuple[tuple[float, ...], tuple[float, ...]]:
    R_cw = T_world_cam[:3, :3]
    C = T_world_cam[:3, 3]
    R_wc = R_cw.T
    t = -R_wc @ C
    return _matrix_to_qvec(R_wc), tuple(float(v) for v in t)


def _camera_key(cam: dict) -> tuple:
    K = np.asarray(cam["intrinsics"], dtype=float)
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    model = "SIMPLE_PINHOLE" if abs(fx - fy) <= 1e-6 else "PINHOLE"
    params = (fx, cx, cy) if model == "SIMPLE_PINHOLE" else (fx, fy, cx, cy)
    return (cam["channel"], model, int(IMAGE_WIDTH), int(IMAGE_HEIGHT), params)


def _load_merged(merged_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict]]:
    npz_path = merged_dir / "merged.npz"
    drives_path = merged_dir / "drives.json"
    if not npz_path.is_file() or not drives_path.is_file():
        raise FileNotFoundError(f"missing merged inputs in {merged_dir}")
    with np.load(npz_path) as f:
        x = np.asarray(f["x"], dtype=float)
        y = np.asarray(f["y"], dtype=float)
        z = np.asarray(f["z"], dtype=float)
        drive = np.asarray(f["drive"], dtype=np.int64)
    drives = json.loads(drives_path.read_text())
    if not isinstance(drives, list):
        raise TypeError("drives.json must be a list")
    return x, y, z, drive, drives


def colmap_model(drives: list[dict], merged_dir: Path, origin: np.ndarray):
    """Build recon-core ColmapModel from per-drive cameras and align poses.

    Also returns {COLMAP image name: dataroot-relative nuScenes image path}
    and {COLMAP image name: scene name}.
    """
    from recon_core.capture.colmap import Camera, ColmapModel, Image

    cameras: dict[int, Camera] = {}
    images: dict[int, Image] = {}
    cam_id_by_key: dict[tuple, int] = {}
    sources: dict[str, str] = {}
    image_captures: dict[str, str] = {}
    image_id = 1

    for d in drives:
        scene = d["scene"]
        drive_dir = merged_dir / "drives" / scene
        cams_path = stage_dir(drive_dir, "load") / "cameras.json"
        poses_path = stage_dir(drive_dir, "align") / "poses.json"
        if not cams_path.is_file() or not poses_path.is_file():
            raise FileNotFoundError(f"missing cameras/poses for drive {scene}")
        cams_doc = json.loads(cams_path.read_text())
        poses_doc = json.loads(poses_path.read_text())
        cam_records = cams_doc.get("cameras", cams_doc) if isinstance(cams_doc, dict) else cams_doc
        pose_rows = poses_doc.get("poses", poses_doc) if isinstance(poses_doc, dict) else poses_doc
        pose_mats = np.array([r["matrix"] for r in pose_rows], dtype=float).reshape(-1, 4, 4)
        pose_stamps = [int(r["timestamp_us"]) for r in pose_rows]

        for cam in cam_records:
            key = _camera_key(cam)
            cam_id = cam_id_by_key.get(key)
            if cam_id is None:
                cam_id = len(cameras) + 1
                cam_id_by_key[key] = cam_id
                cameras[cam_id] = Camera(
                    camera_id=cam_id,
                    model=key[1],
                    width=key[2],
                    height=key[3],
                    params=tuple(float(p) for p in key[4]),
                )

            t_us = int(cam["timestamp_us"])
            T_world_ego = nearest_pose(pose_mats, pose_stamps, t_us)
            T_world_cam = world_camera(T_world_ego, cam["extrinsics"])
            T_world_cam = T_world_cam.copy()
            T_world_cam[:3, 3] -= origin
            qvec, tvec = _colmap_w2c(T_world_cam)
            name = f"{scene}/{cam['channel']}/{t_us}.jpg"
            if any(ch.isspace() for ch in name):
                raise ValueError(f"image name has whitespace: {name!r}")
            prev = sources.get(name)
            if prev is not None and prev != str(cam["image"]):
                raise ValueError(
                    f"duplicate capture image name {name!r}: {prev!r} and {cam['image']!r}"
                )
            sources[name] = str(cam["image"])
            image_captures[name] = str(scene)
            images[image_id] = Image(
                image_id=image_id,
                qvec=qvec,
                tvec=tvec,
                camera_id=cam_id,
                name=name,
                points2d=(),
            )
            image_id += 1

    return ColmapModel(cameras=cameras, images=images, points3d={}), sources, image_captures


def link_images(images_dir: Path, sources: dict[str, Path]) -> None:
    """Create images_dir/<name> symlinks to dataroot files. Copies no bytes."""
    missing = [(name, src) for name, src in sources.items() if not src.is_file()]
    if missing:
        name, src = missing[0]
        raise FileNotFoundError(
            f"{len(missing)} capture image(s) missing; first missing: {name!r} (looked for {src})"
        )
    for name, src in sources.items():
        dst = images_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(src.resolve(), dst)


def build_area_capture(
    merged_dir: Path, out: Path, name: str, dataroot: Path | None = None
) -> Path:
    """Build a recon-core Posed Capture from an area merged dir.

    Symlinks images/<name> for every COLMAP image; bytes stay in the dataroot.
    """
    from datetime import UTC, datetime

    from recon_core.capture import Capture, CaptureMeta, save_capture
    from recon_core.capture.lidar import Lidar

    merged_dir = Path(merged_dir)
    out = Path(out)
    dataroot_path = Path(dataroot) if dataroot is not None else Path(DatasetConfig.from_env().root)
    x, y, z, drive, drives = _load_merged(merged_dir)
    if len(drives) == 0:
        raise ValueError("drives.json is empty")
    if drive.size and (drive.min() < -1 or drive.max() >= len(drives)):
        bad = int(drive.max()) if drive.size else -1
        raise ValueError(
            f"drive index out of range: max {bad} for {len(drives)} drives (allowed -1..{len(drives)-1})"
        )

    origin = np.array(area_origin(x, y), dtype=float)
    captures = tuple(str(d["scene"]) for d in drives)
    colmap, image_sources, image_captures = colmap_model(drives, merged_dir, origin)
    meta = CaptureMeta(
        epsg=EPSG,
        origin_offset=tuple(float(v) for v in origin),
        source=f"area:{name}",
        data_licence=DATA_LICENCE,
        captures=captures,
        image_captures=tuple(sorted(image_captures.items())),
        name=name,
        created=datetime.now(UTC).isoformat(),
    )

    xyz_local = np.column_stack([x, y, z]).astype(np.float64) - origin.reshape(1, 3)
    lidar = Lidar(xyz=xyz_local, capture_index=drive.astype(np.int32))
    capture = Capture(meta=meta, colmap=colmap, lidar=lidar)

    parent = out.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=parent, prefix=f".{out.name}-", suffix=".tmp"))
    try:
        save_capture(capture, tmp)
        link_images(tmp / IMAGES_DIR, {n: dataroot_path / rel for n, rel in image_sources.items()})
        if out.exists():
            if out.is_dir() and not out.is_symlink():
                shutil.rmtree(out)
            else:
                out.unlink()
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def capture_area_command(name: str, store: Path | None = None) -> int:
    store = store or default_store()
    area = open_area(store, name)
    merged_dir = area.merged_dir
    out = area.root / f"{area.name}-capture"
    if area.definition_path is None or not merged_dir.is_dir():
        print(f"twin capture area: missing area or merged dir for {name}", file=sys.stderr)
        return 2
    try:
        build_area_capture(merged_dir, out, name)
    except Exception as exc:  # noqa: BLE001
        print(f"twin capture area: {exc}", file=sys.stderr)
        return 2
    print(out)
    return 0
