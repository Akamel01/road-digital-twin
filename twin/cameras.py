"""Posed cameras: the load and align outputs turned into per-image camera poses.

Knowledge owned here: how a camera image gets a pose (the refined ego pose at the image time,
composed with the camera extrinsic) and which images get one at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from twin.stages.zbuffer import camera_to_world


@dataclass(frozen=True)
class PosedCamera:
    channel: str
    t_us: int
    image: str  # dataroot-relative path, as in cameras.json
    K: np.ndarray  # 3x3 intrinsics
    c2w: np.ndarray  # 4x4 camera-to-world in the run CRS (interpolated ego pose @ extrinsic)


def camera_count(load_dir: Path) -> int:
    """How many camera images the drive has, inside the sweep span or not (for QA counts)."""
    return len(json.loads((load_dir / "cameras.json").read_text())["cameras"])


def posed_cameras(load_dir: Path, align_dir: Path, *, correction: np.ndarray | None = None) -> list[PosedCamera]:
    """Every camera image of the drive whose time lies inside the sweep span, in cameras.json order.

    correction (4x4) is applied to the ego poses before interpolation (merged-drive registration).
    """
    rows = json.loads((align_dir / "poses.json").read_text())["poses"]
    ego = np.array([r["matrix"] for r in rows], float).reshape(-1, 4, 4)
    if correction is not None:
        ego = correction @ ego
    times = np.array([r["timestamp_us"] for r in rows], np.int64)
    cams = json.loads((load_dir / "cameras.json").read_text())["cameras"]
    # DECISION: a camera outside the sweep span has no refined pose, so it is skipped.
    return [
        PosedCamera(
            channel=str(c.get("channel", "")),
            t_us=int(c["timestamp_us"]),
            image=c["image"],
            K=np.asarray(c["intrinsics"], float),
            c2w=camera_to_world(ego, times, int(c["timestamp_us"]), c["extrinsics"]),
        )
        for c in cams
        if times[0] <= c["timestamp_us"] <= times[-1]
    ]
