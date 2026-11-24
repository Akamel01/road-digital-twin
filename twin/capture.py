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
  refined sweep poses. See twin/stages/align.py _write. twin/cameras.py needs
  timestamped rows with at least two sweeps; the identity stand-in in
  twin/areasteps.py align_step (one row, no timestamp_us) is not consumable here.
- T_world_cam = T_world_ego(interpolated at the image timestamp_us inside the
  sweep span) @ T_ego_cam. See twin/cameras.py posed_cameras.
- Images whose timestamp_us lies outside the sweep span are dropped: they have
  no refined pose (same rule as the colour stage).
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
from twin.cameras import posed_cameras
from twin.contracts import stage_dir
from twin.dataset import DatasetConfig
from twin.runner import default_store
from twin.stages.zbuffer import matrix_to_quat

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


def _colmap_w2c(T_world_cam: np.ndarray) -> tuple[tuple[float, ...], tuple[float, ...]]:
    R_cw = T_world_cam[:3, :3]
    C = T_world_cam[:3, 3]
    R_wc = R_cw.T
    t = -R_wc @ C
    q = matrix_to_quat(R_wc)
    q /= np.linalg.norm(q)
    return tuple(float(v) for v in q), tuple(float(v) for v in t)


def _camera_key(channel: str, K: np.ndarray) -> tuple:
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    model = "SIMPLE_PINHOLE" if abs(fx - fy) <= 1e-6 else "PINHOLE"
    params = (fx, cx, cy) if model == "SIMPLE_PINHOLE" else (fx, fy, cx, cy)
    return (channel, model, int(IMAGE_WIDTH), int(IMAGE_HEIGHT), params)


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
    """Build recon-core ColmapModel from per-drive posed cameras.

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
        load_dir = stage_dir(drive_dir, "load")
        align_dir = stage_dir(drive_dir, "align")
        if not (load_dir / "cameras.json").is_file() or not (align_dir / "poses.json").is_file():
            raise FileNotFoundError(f"missing cameras/poses for drive {scene}")

        for cam in posed_cameras(load_dir, align_dir):
            key = _camera_key(cam.channel, cam.K)
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

            T_world_cam = cam.c2w.copy()
            T_world_cam[:3, 3] -= origin
            qvec, tvec = _colmap_w2c(T_world_cam)
            name = f"{scene}/{cam.channel}/{cam.t_us}.jpg"
            if any(ch.isspace() for ch in name):
                raise ValueError(f"image name has whitespace: {name!r}")
            prev = sources.get(name)
            if prev is not None and prev != str(cam.image):
                raise ValueError(
                    f"duplicate capture image name {name!r}: {prev!r} and {cam.image!r}"
                )
            sources[name] = str(cam.image)
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
