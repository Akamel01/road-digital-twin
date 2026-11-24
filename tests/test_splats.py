"""Splats stage: the parts that need no GPU (depth maps, geometry check, tiling, pose report, contracts)."""

import numpy as np
import pytest

from twin import gpulease
from twin.contracts import STAGE_NAMES, STAGES, Pipeline, SplatsParams
from twin.sightline import Surface
from twin.stages import splats

K = np.array([[100.0, 0, 50], [0, 100.0, 40], [0, 0, 1]])


def test_scaled_intrinsics_keeps_the_view():
    k, (w, h) = splats.scaled_intrinsics(np.array([[1600.0, 0, 800], [0, 1600.0, 450], [0, 0, 1]]), (1600, 900), 800)
    assert (w, h) == (800, 450) and k[0, 0] == 800 and k[0, 2] == 400 and k[1, 2] == 225


def test_sparse_depth_takes_the_nearest_point_per_pixel():
    c2w = np.eye(4)  # camera at origin, looking along +z
    pts = np.array([[0.0, 0.0, 10.0], [0.0, 0.0, 5.0], [0.0, 0.0, 0.2], [50.0, 0, 5.0]])
    d = splats.sparse_depth(pts, c2w, K, (100, 80))
    assert d[40, 50] == 5.0  # nearer wins; the 0.2 m return is under DEPTH_MIN_M; x = 50 is outside the image
    assert (d > 0).sum() == 1


def test_ground_z_and_geometry_agreement():
    z = np.zeros((20, 20))
    surface = Surface(z=z, count=np.ones((20, 20), int), origin=np.array([0.0, 0.0]), cell_m=0.5)
    assert np.isnan(splats.ground_z_at(surface, np.array([[50.0, 50.0]]))[0])
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 10, (4000, 2))
    on = np.column_stack([xy, rng.normal(0.0, 0.01, 4000)])
    r = splats.geometry_agreement(on, surface)
    assert r["abs_p95_m"] < 0.05 and r["coverage"] > 0.9
    lifted = on + [0, 0, 0.2]
    assert splats.geometry_agreement(lifted, surface)["abs_p50_m"] == pytest.approx(0.2, abs=0.02)


def test_ortho_tiles_cover_the_extent():
    tiles, (w, h) = splats.ortho_tiles(np.array([0.0, 0.0]), np.array([100.0, 60.0]), 0.03, 2048)
    assert (w, h) == (3334, 2000)
    assert sum(t[2] * t[3] for t in tiles) == w * h


def test_pose_report_flags_the_drive_when_a_quarter_is_off():
    p = SplatsParams()
    d = np.zeros((8, 6))
    assert not splats.pose_report(d, ["A"] * 8, p)["drive_flagged"]
    d[:2, 0] = np.radians(2)
    rep = splats.pose_report(d, ["A"] * 8, p)
    assert rep["n_flagged"] == 2 and rep["drive_flagged"] and rep["rotation_deg_max"] == pytest.approx(2.0, abs=1e-3)


def test_initial_splats_flat_ground_and_cap():
    rng = np.random.default_rng(1)
    ground = np.column_stack([rng.uniform(0, 5, (3000, 2)), np.zeros(3000)])
    other = rng.uniform(0, 5, (3000, 3)) + [0, 0, 1]
    init = splats.initial_splats(ground, other, 1500, 0)
    assert len(init["xyz"]) <= 1500 and init["scales"].shape == (len(init["xyz"]), 3)
    assert init["scales"][0, 2] < init["scales"][0, 0]  # a ground disc is flat


def test_ssim_of_an_image_with_itself_is_one():
    torch = pytest.importorskip("torch")
    a = torch.rand(1, 3, 32, 32)
    assert float(splats._ssim_map(torch, a, a).mean()) == pytest.approx(1.0, abs=1e-4)
    assert float(splats._ssim_map(torch, a, 1 - a).mean()) < 0.5


def test_pose_delta_is_identity_at_zero():
    torch = pytest.importorskip("torch")
    assert torch.allclose(splats._delta_matrix(torch, torch.zeros(6)), torch.eye(4))


def test_splats_is_last_optional_off_by_default_and_takes_the_gpu_lease_when_on():
    assert STAGE_NAMES[-1] == "splats" and STAGES["splats"].optional
    assert Pipeline().splats.enabled is False
    rerun = {"type": "rerun", "run_id": "r", "from_stage": "splats"}
    assert not gpulease.needs_gpu(rerun, lambda v: {})
    assert gpulease.needs_gpu(rerun, lambda v: {"splats": {"method": "gsplat-lidar"}})
