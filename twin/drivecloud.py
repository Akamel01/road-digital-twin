"""A drive's poses and aligned points: the one place that reads a drive folder's pose files and moves its lidar
points from the run CRS into the refined (aligned) frame.

`drive` is any folder that holds stage folders: a run folder, the temporary root `twin stage` builds, or an area
drive folder. Stage folders are found only through `stage_dir`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from twin.contracts import stage_dir
from twin.stages import align

LAYER_FILES = {"points": "points.npz", "parked": "parked.npz"}
POINT_FIELDS = ("x", "y", "z", "intensity", "sweep")


@dataclass(frozen=True)
class AlignedCloud:
    xyz: np.ndarray  # (N, 3) in the aligned (refined) frame, sorted by sweep
    intensity: np.ndarray  # (N,)
    sweep: np.ndarray  # (N,)
    lidarseg: np.ndarray | None  # (N,) when the mask stage kept labels, in the same order as xyz


def drive_poses(drive: Path, stage: Literal["load", "align"]) -> np.ndarray:
    """(S, 4, 4) pose matrices from <drive>/<stage folder>/poses.json."""
    rows = json.loads((stage_dir(drive, stage) / "poses.json").read_text())["poses"]
    return np.array([r["matrix"] for r in rows], dtype=float).reshape(-1, 4, 4)


def aligned_cloud(drive: Path, layer: Literal["points", "parked"] = "points") -> AlignedCloud:
    """The drive's masked points (or its parked-vehicle points) moved from the run CRS into the refined frame.

    Each point goes to its ego frame (dataset pose inverse, via align.ego_sweeps), then through its sweep's refined
    pose. With refined poses equal to the dataset poses this is the identity. Points come sorted by sweep (stable).
    """
    with np.load(stage_dir(drive, "mask") / LAYER_FILES[layer]) as f:
        fields = {k: f[k] for k in (*POINT_FIELDS, "lidarseg") if k in f.files}
    order = np.argsort(fields["sweep"].astype(np.int64), kind="stable")
    labels = fields["lidarseg"][order] if "lidarseg" in fields else None
    if len(order) == 0:
        return AlignedCloud(np.empty((0, 3)), fields["intensity"], fields["sweep"], labels)
    refined = drive_poses(drive, "align")
    egos = align.ego_sweeps(fields, drive_poses(drive, "load"))
    xyz = np.vstack([p @ t[:3, :3].T + t[:3, 3] for p, t in zip(egos, refined, strict=False)])
    sweep = np.repeat(np.arange(len(egos), dtype=np.int32), [len(p) for p in egos])
    return AlignedCloud(xyz, fields["intensity"][order], sweep, labels)
