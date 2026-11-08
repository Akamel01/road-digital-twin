"""Colour helper: depth buffer, visibility and pose interpolation. Synthetic plane and box, no devkit, no data."""

import numpy as np

from twin.contracts import ColourParams
from twin.stages import zbuffer
from twin.stages.load import pose_matrix, quat_to_matrix, qz

W, H = 1600, 900
K = np.array([[800.0, 0, 800.0], [0, 800.0, 450.0], [0, 0, 1.0]])
# Camera 1.5 m up, looking along world +x. Camera axes: x right (-y), y down (-z), z forward (+x).
R = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
CAM = np.eye(4)
CAM[:3, :3] = R
CAM[:3, 3] = [0.0, 0.0, 1.5]
BOX = {
    "center": [6.0, 0.0, 0.75],
    "size": [2.0, 2.0, 1.5],
    "rotation": [1.0, 0.0, 0.0, 0.0],
}


def _ground(x0, x1, y0=-5.0, y1=5.0, step=0.1):
    x, y = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step), indexing="ij")
    return np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])


def _strip(x0, x1):
    """Ground points in front of the camera, along the optical axis (|y| < 0.2 m)."""
    pts = _ground(x0, x1, -0.2, 0.2, 0.05)
    return pts


def test_box_occludes_ground_behind_it():
    # Ground at 7.5 to 8.5 m is behind the box (rays past x = 7 m are blocked). Without the box most of it
    # is visible; the rest is lost to the 4 px depth cell (about 0.2 m deep at 8 m, equal to zbuf_tol_m).
    behind = _strip(7.5, 8.5)
    free = zbuffer.visible(behind, _ground(1.0, 30.0), CAM, K, (W, H), ColourParams())
    assert free.mean() > 0.9, "without the box, ground behind it is visible"
    blockers = np.vstack(
        [_ground(1.0, 30.0), zbuffer.box_blockers([BOX], CAM, K, ColourParams())]
    )
    blocked = zbuffer.visible(behind, blockers, CAM, K, (W, H), ColourParams())
    assert not blocked.any(), "the box hides the ground behind it"
    front = _strip(3.0, 4.5)
    assert zbuffer.visible(front, blockers, CAM, K, (W, H), ColourParams()).all(), (
        "ground in front of the box stays visible"
    )


def test_depth_and_range_limits():
    p = ColourParams()
    near = np.array(
        [[0.8, 0.0, 1.2]]
    )  # 0.8 m deep, inside the image, under min_depth_m
    assert not zbuffer.visible(near, near, CAM, K, (W, H), p).any()
    ok = np.array([[3.0, 0.0, 0.0]])
    assert zbuffer.visible(ok, ok, CAM, K, (W, H), p).all()
    far = np.array([[14.0, 0.0, 0.0]])  # 14 m horizontal, beyond max_range_m 12
    assert not zbuffer.visible(far, far, CAM, K, (W, H), p).any()
    assert zbuffer.visible(far, far, CAM, K, (W, H), ColourParams(max_range_m=50)).all()


def test_ground_near_camera_sees_itself():
    near = _strip(
        3.0, 6.0
    )  # within 6 m the 4 px cell is shallow enough that ground is not hidden by itself
    assert zbuffer.visible(
        near, _ground(1.0, 30.0), CAM, K, (W, H), ColourParams()
    ).all()


def test_box_samples_lie_on_faces():
    s = zbuffer.box_samples([BOX], 0.05)
    local = (s - BOX["center"]) @ np.eye(3)
    half = np.array([1.0, 1.0, 0.75])  # size [w, l, h] -> half extents [l, w, h] / 2
    assert np.all(np.abs(local) <= half + 1e-9)
    assert np.allclose(np.abs(local).max(axis=0), half), "samples reach every face"
    assert len(zbuffer.box_samples([], 0.05)) == 0


def test_pose_interpolation_at_midpoint():
    yaw_a, yaw_b = 0.0, 0.2
    ego = np.array(
        [
            pose_matrix([0.0, 0.0, 0.0], qz(yaw_a)),
            pose_matrix([1.0, 0.0, 0.0], qz(yaw_b)),
        ]
    )
    times = np.array([0, 100_000])
    mid = zbuffer.pose_at(ego, times, 50_000)
    assert np.allclose(mid[:3, 3], [0.5, 0.0, 0.0])
    assert np.isclose(np.arctan2(mid[1, 0], mid[0, 0]), 0.1, atol=1e-9)
    try:
        zbuffer.pose_at(ego, times, 200_000)
    except ValueError:
        pass
    else:
        raise AssertionError("time outside the sweep span must be refused")


def test_matrix_to_quat_round_trip():
    rng = np.random.default_rng(0)
    for _ in range(20):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        m = quat_to_matrix(q)
        back = quat_to_matrix(zbuffer.matrix_to_quat(m))
        assert np.allclose(back, m, atol=1e-9)
