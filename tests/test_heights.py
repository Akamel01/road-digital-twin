"""Heights: synthetic sweeps with injected z, roll and pitch errors; no data, no devkit."""

import numpy as np

from twin import heights

N = 40
STEP_M = 1.0


def _surface(x, y):
    return 0.02 * x + 0.05 * np.sin(x / 7.0) + 0.03 * np.cos(y / 5.0)


def _rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _drifting_sweeps(seed=0):
    """True poses on a line over a gently curved road; estimated poses carry a step, a ramp, roll and pitch errors."""
    rng = np.random.default_rng(seed)
    true = np.tile(np.eye(4), (N, 1, 1))
    true[:, 0, 3] = STEP_M * np.arange(N)
    true[:, 2, 3] = _surface(true[:, 0, 3], 0.0) + 1.0
    err_dz = 0.3 * (np.arange(N) >= N // 2) + 0.01 * np.arange(N)
    err_roll = np.radians(0.5) * np.sin(np.arange(N) / 5.0)
    err_pitch = np.radians(0.3) * np.cos(np.arange(N) / 4.0)
    for e in (err_dz, err_roll, err_pitch):
        e -= e.mean()
    est = true.copy()
    for k in range(N):
        est[k, :3, :3] = true[k, :3, :3] @ _ry(err_pitch[k]) @ _rx(err_roll[k])
        est[k, 2, 3] += err_dz[k]
    ground = []
    for k in range(N):
        g = rng.uniform(-20, 20, (3000, 2))
        world = np.column_stack(
            [
                g[:, 0] + true[k, 0, 3],
                g[:, 1],
                _surface(g[:, 0] + true[k, 0, 3], g[:, 1]),
            ]
        )
        ego = world - true[k, :3, 3]  # true rotation is identity
        # the sensor sees the ground in the *true* ego frame; the estimate is wrong, not the data
        ground.append(ego)
    return true, est, ground


def test_recovers_injected_z_roll_pitch():
    true, est, ground = _drifting_sweeps()
    new, rep = heights.correct_heights(est, ground)
    assert rep["fitted"].all()
    assert rep["converged"]
    assert np.abs(new[:, 2, 3] - true[:, 2, 3]).max() < 0.01
    # tilt: the corrected rotation should be the true one (identity) to 0.05 degrees
    tilt = np.array(
        [
            np.arccos(np.clip((np.trace(new[k, :3, :3]) - 1) / 2, -1, 1))
            for k in range(N)
        ]
    )
    assert np.degrees(tilt).max() < 0.05
    assert np.nanmedian(rep["residual_after_m"]) < 0.5 * np.nanmedian(
        rep["residual_before_m"]
    )


def test_x_y_yaw_unchanged_and_deterministic():
    _, est, ground = _drifting_sweeps()
    a, _ = heights.correct_heights(est, ground)
    b, _ = heights.correct_heights(est, ground)
    assert np.array_equal(a, b)
    assert np.allclose(a[:, :2, 3], est[:, :2, 3])
    yaw = lambda m: np.arctan2(m[:, 1, 0], m[:, 0, 0])
    assert np.abs(yaw(a) - yaw(est)).max() < 1e-4


def test_sweep_without_ground_keeps_its_pose():
    _, est, ground = _drifting_sweeps()
    ground[5] = ground[5][:10]
    new, rep = heights.correct_heights(est, ground)
    assert not rep["fitted"][5]
    assert np.array_equal(new[5], est[5])


def test_ego_ground_uses_labels_else_ransac():
    rng = np.random.default_rng(0)
    flat = np.column_stack(
        [rng.uniform(-15, 15, (4000, 2)), rng.normal(0, 0.005, 4000)]
    )
    wall = np.column_stack(
        [rng.uniform(-1, 1, 500), np.full(500, 8.0), rng.uniform(0.5, 3, 500)]
    )
    pts = np.vstack([flat, wall])
    none = np.full(len(pts), heights.LIDARSEG_NONE, np.uint8)
    lab = none.copy()
    lab[:4000] = 24 + 3  # terrain
    lab[4000:] = 1
    out = heights.ego_ground([pts, pts], [lab, none], 24, workers=1)
    assert (
        0 < len(out[0]) and (out[0][:, 2] < 0.1).all()
    )  # labelled sweep: the flat part
    assert (
        len(out[1]) > 0 and np.median(out[1][:, 2]) < 0.1
    )  # unlabelled: RANSAC finds the plane
    assert (out[1][:, 2] < 0.2).mean() > 0.95
