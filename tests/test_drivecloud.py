"""drivecloud: a drive folder's poses and its points in the aligned frame, on a synthetic two-sweep drive."""

import json

import numpy as np
import pytest

from twin.contracts import stage_dir
from twin.drivecloud import aligned_cloud, drive_poses


def _pose(x, yaw_deg=0.0):
    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    m = np.eye(4)
    m[:2, :2] = [[c, -s], [s, c]]
    m[0, 3] = x
    return m


def _write_poses(drive, stage, poses):
    d = stage_dir(drive, stage)
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"matrix": p.tolist()} for p in poses]
    (d / "poses.json").write_text(json.dumps({"poses": rows}))


def _write_points(drive, name, sweep, with_labels=False):
    d = stage_dir(drive, "mask")
    d.mkdir(parents=True, exist_ok=True)
    n = len(sweep)
    fields = {
        "x": np.arange(n, dtype=float) + 100.0,
        "y": np.zeros(n),
        "z": np.ones(n),
        "intensity": np.arange(n, dtype=np.float32),
        "sweep": np.asarray(sweep, dtype=np.int32),
    }
    if with_labels:
        fields["lidarseg"] = np.arange(n, dtype=np.uint8) + 10
    np.savez(d / name, **fields)


LOAD = [_pose(100.0), _pose(110.0)]
ALIGN = [_pose(101.0), _pose(108.0, 90.0)]


@pytest.fixture
def drive(tmp_path):
    _write_poses(tmp_path, "load", LOAD)
    _write_poses(tmp_path, "align", ALIGN)
    # sweeps out of order, so the cloud has to sort them
    _write_points(tmp_path, "points.npz", [1, 0, 1, 0], with_labels=True)
    _write_points(tmp_path, "parked.npz", [1, 0])
    return tmp_path


def test_drive_poses_reads_each_stage(drive):
    assert drive_poses(drive, "load").shape == (2, 4, 4)
    assert np.allclose(drive_poses(drive, "align")[1], ALIGN[1])


def test_points_move_through_refined_poses(drive):
    cloud = aligned_cloud(drive)
    assert cloud.sweep.tolist() == [0, 0, 1, 1]
    # input points 1 and 3 are sweep 0, points 0 and 2 are sweep 1 (x = 100 + index)
    for xyz, k, src in zip(cloud.xyz, cloud.sweep, [1, 3, 0, 2], strict=True):
        ego = np.linalg.inv(LOAD[k]) @ [100.0 + src, 0, 1, 1]
        assert np.allclose(xyz, (ALIGN[k] @ ego)[:3])
    assert cloud.intensity.tolist() == [1, 3, 0, 2]


def test_lidarseg_follows_point_order(drive):
    assert aligned_cloud(drive).lidarseg.tolist() == [11, 13, 10, 12]


def test_parked_layer_has_no_labels(drive):
    cloud = aligned_cloud(drive, "parked")
    assert cloud.lidarseg is None
    assert cloud.sweep.tolist() == [0, 1]


def test_identity_when_refined_equals_dataset_poses(drive):
    _write_poses(drive, "align", LOAD)
    cloud = aligned_cloud(drive)
    src = np.array([101.0, 103.0, 100.0, 102.0])
    assert np.allclose(cloud.xyz[:, 0], src)
    assert np.allclose(cloud.xyz[:, 2], 1.0)


def test_empty_parked_layer(drive):
    _write_points(drive, "parked.npz", [])
    assert aligned_cloud(drive, "parked").xyz.shape == (0, 3)


def test_missing_stage_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        aligned_cloud(tmp_path)
    with pytest.raises(FileNotFoundError):
        drive_poses(tmp_path, "align")
