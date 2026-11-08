"""Stage 3 align: synthetic sweeps only, no devkit, no data."""

import json
import logging
import math

import numpy as np
import pytest

from twin import fixtures, registry
from twin.contracts import AlignParams
from twin.runner import StageContext
from twin.stages import align
from twin.stages.load import pose_matrix, qz

STEP_M = 0.2  # per sweep (4 m/s at 20 Hz): the fixture's flat floor needs a short step to track
N_SWEEPS = 20


def _rz(yaw, t=(0.0, 0.0, 0.0)):
    m = np.eye(4)
    m[:3, :3] = pose_matrix([0, 0, 0], list(qz(yaw)))[:3, :3]
    m[:3, 3] = t
    return m


def _ego(k):
    x = 2.0 + STEP_M * k
    return _rz(0.0, (x, 10.0, 1.8 + fixtures.SLOPE * x))


def _world():
    """Fixture scene with lattice-breaking xy jitter (real returns are not on a grid)."""
    world = fixtures.make_scene(seed=0)
    rng = np.random.default_rng(0)
    world[:, :2] += rng.uniform(-0.12, 0.12, (len(world), 2))
    return world[np.hypot(world[:, 0] - 8, world[:, 1] - 10) < 60]


def _write_run(tmp_path, ego_mats, points_per_sweep):
    """load/poses.json (dataset ego poses) and mask/points.npz (masked points, run CRS)."""
    run_dir = tmp_path / "run"
    (run_dir / "1_load").mkdir(parents=True)
    (run_dir / "2_mask").mkdir()
    entries = [
        {"sweep": k, "token": f"t{k}", "timestamp_us": k * 50_000, "matrix": m.tolist()}
        for k, m in enumerate(ego_mats)
    ]
    (run_dir / "1_load" / "poses.json").write_text(
        json.dumps({"crs": "EPSG:32619", "poses": entries})
    )
    xyz, sweep = [], []
    for k, pts in enumerate(points_per_sweep):
        xyz.append(pts[:, :3])
        sweep.append(np.full(len(pts), k, dtype=np.uint16))
    xyz = np.vstack(xyz)
    np.savez_compressed(
        run_dir / "2_mask" / "points.npz",
        x=xyz[:, 0],
        y=xyz[:, 1],
        z=xyz[:, 2],
        intensity=np.zeros(len(xyz), np.float32),
        sweep=np.concatenate(sweep),
    )
    ctx = StageContext(
        run_dir=run_dir, scene_token="s", seed=0, log=logging.getLogger("test")
    )
    return ctx, run_dir / "3_align"


def test_fit_rigid_2d_recovers_known_offset():
    rng = np.random.default_rng(3)
    src = rng.uniform(-20, 20, (30, 2))
    yaw0, t0 = 0.37, np.array([4.2, -1.1])
    r = np.array([[math.cos(yaw0), -math.sin(yaw0)], [math.sin(yaw0), math.cos(yaw0)]])
    dst = src @ r.T + t0
    yaw, t = align.fit_rigid_2d(src, dst)
    assert yaw == pytest.approx(yaw0, abs=1e-9)
    assert t == pytest.approx(t0, abs=1e-9)


def test_anchor_recovers_known_xy_yaw_offset():
    rng = np.random.default_rng(5)
    icp = np.stack(
        [_rz(0.0, (x, 0.5 * math.sin(x), 0.0)) for x in rng.uniform(0, 30, 25)]
    )
    offset = _rz(
        0.21, (3.0, -1.5, 0.0)
    )  # the dataset is the ICP trajectory moved by this
    ref = np.stack([offset @ m for m in icp])
    a = align.fit_anchor(icp, ref)
    assert a[:2, :2] == pytest.approx(offset[:2, :2], abs=1e-9)
    assert a[:2, 3] == pytest.approx(offset[:2, 3], abs=1e-9)
    assert align.anchor(icp, ref, np.zeros(len(icp), int)) == pytest.approx(
        ref, abs=1e-9
    )


def test_dataset_poses_passthrough(tmp_path):
    mats = [_ego(k) for k in range(5)]
    ctx, out = _write_run(tmp_path, mats, [_world()[:500]] * 5)
    result = registry.lookup("align", "dataset-poses")(ctx, AlignParams())
    assert result.status == "ok"
    poses = json.loads((out / "poses.json").read_text())["poses"]
    assert np.array([p["matrix"] for p in poses]) == pytest.approx(
        np.array([m for m in mats])
    )
    qa = json.loads((out / "qa.json").read_text())
    assert qa["fallback_used"] is True
    assert qa["xy_drift_p95_m"] == 0.0


def test_forced_icp_failure_falls_back(tmp_path, monkeypatch):
    mats = [_ego(k) for k in range(5)]
    ctx, out = _write_run(tmp_path, mats, [_world()[:500]] * 5)

    def boom(sweeps, voxel_m):
        raise RuntimeError("forced")

    monkeypatch.setattr(align, "run_kiss_icp", boom)
    result = registry.lookup("align", "kiss-icp")(ctx, AlignParams())
    assert result.status == "ok"
    qa = json.loads((out / "qa.json").read_text())
    assert qa["fallback_used"] is True
    assert "forced" in qa["fallback_reason"]
    poses = json.loads((out / "poses.json").read_text())["poses"]
    assert np.array([p["matrix"] for p in poses]) == pytest.approx(np.array(mats))


def test_too_few_points_falls_back(tmp_path):
    mats = [_ego(k) for k in range(3)]
    world = _world()
    ctx, out = _write_run(tmp_path, mats, [world[:500], world[:5], world[:500]])
    registry.lookup("align", "kiss-icp")(ctx, AlignParams())
    qa = json.loads((out / "qa.json").read_text())
    assert qa["fallback_used"] is True
    assert "sweep 1" in qa["fallback_reason"]


def test_kiss_icp_recovers_motion_end_to_end(tmp_path):
    mats = [_ego(k) for k in range(N_SWEEPS)]
    world = _world()
    ctx, out = _write_run(tmp_path, mats, [world] * N_SWEEPS)
    result = registry.lookup("align", "kiss-icp")(
        ctx, AlignParams(window_s=20, voxel_m=0.5)
    )
    assert result.status == "ok"
    qa = json.loads((out / "qa.json").read_text())
    assert qa["fallback_used"] is False, qa["fallback_reason"]
    poses = json.loads((out / "poses.json").read_text())["poses"]
    refined = np.array([p["matrix"] for p in poses])
    truth = np.array(mats)
    assert np.linalg.norm(refined[:, :2, 3] - truth[:, :2, 3], axis=1).max() < 0.1
