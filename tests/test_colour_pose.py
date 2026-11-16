"""colour_pose: per-frame camera pose refinement against lidar paint (CPU only)."""

import json
from types import SimpleNamespace

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from twin import pose
from twin.contracts import STAGES, ColourParams
from twin.stages import colour, colour_pose, zbuffer
from twin.stages.ground import _write_laz

K = np.array([[800.0, 0, 400], [0, 800.0, 300], [0, 0, 1]])
W, H = 800, 600
HALF_WIDTH = 0.075  # 15 cm paint
# Stripe centre lines on the ground plane z = 0 (x forward, y left): lane lines, stop bars, one diagonal.
LINES = [
    ((3.0, 1.75), (12.0, 1.75)),
    ((3.0, -1.75), (12.0, -1.75)),
    ((3.0, 4.5), (11.0, 5.0)),
    ((4.0, -3.0), (4.0, 3.0)),
    ((7.0, -3.5), (7.0, 3.5)),
    ((10.0, -4.0), (10.0, 4.0)),
    ((5.0, -4.5), (9.0, -2.5)),
]


def _camera(pitch_deg=12.0, height=1.6):
    """c2w for a camera at (0, 0, height) looking along +x, pitched down; camera axes x right, y down, z forward."""
    p = np.radians(pitch_deg)
    z = np.array([np.cos(p), 0.0, -np.sin(p)])
    x = np.array([0.0, -1.0, 0.0])
    T = np.eye(4)
    T[:3, :3] = np.column_stack([x, np.cross(z, x), z])
    T[:3, 3] = [0.0, 0.0, height]
    return T


def _render(c2w, ss=3):
    """Ray-cast the painted ground (supersampled ss x ss): paint 220, asphalt 60, sky 0. Pixel centres at integers."""
    o = (np.arange(ss) + 0.5) / ss - 0.5
    u = (np.arange(W)[None, :, None, None] + o[None, None, None, :]) * np.ones((H, 1, ss, 1))
    v = (np.arange(H)[:, None, None, None] + o[None, None, :, None]) * np.ones((1, W, 1, ss))
    rays = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones_like(u)], -1) @ c2w[:3, :3].T
    t = -c2w[2, 3] / np.where(rays[..., 2] < -1e-9, rays[..., 2], np.nan)
    gx, gy = c2w[0, 3] + t * rays[..., 0], c2w[1, 3] + t * rays[..., 1]
    paint = np.zeros(gx.shape, bool)
    for a, b in LINES:
        a, b = np.array(a), np.array(b)
        d = (b - a) / np.linalg.norm(b - a)
        rx, ry = gx - a[0], gy - a[1]
        along = rx * d[0] + ry * d[1]
        across = rx * d[1] - ry * d[0]
        paint |= (np.abs(across) <= HALF_WIDTH) & (along >= 0) & (along <= np.linalg.norm(b - a))
    img = np.where(np.isfinite(t), np.where(paint, 220.0, 60.0), 0.0).mean(axis=(2, 3))
    return np.repeat(img[..., None], 3, axis=2).astype(np.uint8)


def _anchors(step=0.25):
    rows = []
    for i, (a, b) in enumerate(LINES):
        n = int(np.linalg.norm(np.subtract(b, a)) / step) + 1
        for s in np.linspace(0, 1, n)[1:-1]:
            rows.append([a[0] + s * (b[0] - a[0]), a[1] + s * (b[1] - a[1]), 0.0, i])
    return np.array(rows)


def _pose_error(a, b):
    d = np.linalg.inv(a) @ b
    return np.degrees(np.linalg.norm(Rotation.from_matrix(d[:3, :3]).as_rotvec())), np.linalg.norm(d[:3, 3])


def test_recovers_injected_pose_error_from_a_raycast_image():
    truth = _camera()
    img = _render(truth)
    inject = np.concatenate([np.radians([0.12, -0.1, 0.12]), [0.012, -0.01, 0.012]])  # 0.2 deg, 2 cm
    base = truth @ np.linalg.inv(colour_pose._delta_matrix(inject))
    deg0, m0 = _pose_error(truth, base)
    assert 0.19 < deg0 < 0.21 and 0.019 < m0 < 0.021
    corrected, _res, info = colour_pose.refine_one(base, K, img, _anchors(), ColourParams())
    deg, m = _pose_error(truth, corrected)
    assert info["applied"], info
    assert info["hit_bound"] is False
    assert deg < 0.1 and m < 0.01, (deg, m, info)
    assert info["offset_px_after"] < info["offset_px_before"]


def _stage_run(tmp_path, monkeypatch, injects):
    """A one-channel drive on the painted plane: frame i is rendered at its calibrated pose times injects[i]."""
    monkeypatch.setenv("NUSCENES_ROOT", str(tmp_path / "ns"))
    (tmp_path / "ns").mkdir()
    dirs = {name: tmp_path / "run" / f"{s.number}_{name}" for name, s in STAGES.items()}
    for d in dirs.values():
        d.mkdir(parents=True)
    ctx = SimpleNamespace(stage_dir=dirs.__getitem__, input_dir=dirs.__getitem__)
    calib = _camera()
    cams = []
    for i, inj in enumerate(injects):
        Image.fromarray(_render(calib @ colour_pose._delta_matrix(np.asarray(inj)))).save(tmp_path / "ns" / f"{i}.png")
        cams.append({
            "timestamp_us": 100_000 * (i + 1), "image": f"{i}.png", "channel": "CAM_FRONT", "intrinsics": K.tolist(),
            "extrinsics": {"translation": calib[:3, 3].tolist(), "rotation_wxyz": zbuffer.matrix_to_quat(calib[:3, :3]).tolist()},
        })
    x, y = np.meshgrid(np.arange(2.0, 13.0, 0.05), np.arange(-5.0, 5.0, 0.05))
    ground = np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])
    _write_laz(dirs["ground"] / "ground.laz", ground, np.zeros(len(ground)), 2)
    _write_laz(dirs["ground"] / "nonground.laz", np.array([[-50.0, 0.0, 1.0]]), np.zeros(1), 1)
    (dirs["ground"] / "qa.json").write_text(json.dumps({"height_valid": True}))
    feats = [{"type": "Feature", "properties": {"id": f"marking-{i:02d}", "reliability": "observed"},
              "geometry": {"type": "LineString", "coordinates": [[*a, 0.0], [*b, 0.0]]}} for i, (a, b) in enumerate(LINES)]
    (dirs["features"] / "markings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    span = (0, 1_000_000)
    (dirs["align"] / "poses.json").write_text(json.dumps({"poses": [{"timestamp_us": t, "matrix": np.eye(4).tolist()} for t in span]}))
    (dirs["load"] / "cameras.json").write_text(json.dumps({"cameras": cams}))
    (dirs["load"] / "boxes.json").write_text(json.dumps({"sweeps": [{"timestamp_us": t, "boxes": []} for t in span]}))
    return ctx


def test_stage_refines_each_frame_of_a_channel_on_its_own(tmp_path, monkeypatch):
    """Two frames of one channel carry opposite 0.2 deg / 2 cm errors (ego timing, not extrinsics): only a
    per-frame correction can fix both, and the ortho stripes then land on the lidar lines."""
    inj = np.concatenate([np.radians([0.12, -0.1, 0.12]), [0.012, -0.01, 0.012]])
    ctx = _stage_run(tmp_path, monkeypatch, [inj, -inj])
    topk = colour.run_zbuffer_topk(ctx, ColourParams()).metrics
    qa = colour.run_zbuffer_pose_refine(ctx, ColourParams()).metrics
    pc = qa["pose_corrections"]
    assert qa["n_refined"] == 2 and pc["reason"] == "converged" and pc["hit_bound"] is False, pc
    assert abs(pc["rotation_deg_p50"] - 0.197) < 0.1 and abs(pc["translation_m_p50"] - 0.0197) < 0.01, pc
    assert qa["edge_offset_samples"] >= 20
    assert qa["edge_offset_p95_m"] < topk["edge_offset_p95_m"], (qa["edge_offset_p95_m"], topk["edge_offset_p95_m"])


def test_correct_pose_stays_put():
    truth = _camera()
    corrected, _res, info = colour_pose.refine_one(truth, K, _render(truth), _anchors(), ColourParams())
    deg, m = _pose_error(truth, corrected)
    assert deg < 0.05 and m < 0.005, (deg, m, info)


def test_blank_image_reverts():
    truth = _camera()
    corrected, _res, info = colour_pose.refine_one(truth, K, np.full((H, W, 3), 90, np.uint8), _anchors(), ColourParams())
    assert info["applied"] is False and info["reason"] == "insufficient_inliers"
    assert np.array_equal(corrected, truth)


def test_no_anchors_reverts():
    _corrected, _res, info = colour_pose.refine_one(np.eye(4), K, np.zeros((4, 4, 3), np.uint8), None, ColourParams())
    assert info["applied"] is False and info["reason"] == "no_anchors" and info["hit_bound"] is False


def test_lidar_paint_edges_uses_marking_z():
    feats = [
        {"properties": {"reliability": "observed"}, "geometry": {"coordinates": [[0, 0, 1.0], [2, 0, 1.2]]}},
        {"properties": {"reliability": "modelled"}, "geometry": {"coordinates": [[0, 5, 0], [2, 5, 0]]}},
    ]
    a = colour_pose.lidar_paint_edges(feats, None)
    assert a.shape == (9, 4)
    assert np.allclose(a[:, 2], 1.0 + 0.1 * a[:, 0])
    assert colour_pose.lidar_paint_edges([], None).shape == (0, 3)


def test_pose_report_reason_agrees_with_hit_bound():
    p = ColourParams()
    infos = [{"applied": True, "reason": "converged", "hit_bound": False},
             {"applied": False, "reason": "hit_bound", "hit_bound": True},
             {"applied": False, "reason": "no_improvement", "hit_bound": False}]
    rep = pose.pose_report(np.zeros((3, 6)), ["A", "A", "B"], p, info=infos)
    assert rep["applied"] is True and rep["hit_bound"] is True
    assert rep["reasons"] == {"converged": 1, "hit_bound": 1, "no_improvement": 1}
    assert rep["n_applied"] == 1
    rep = pose.pose_report(np.zeros((1, 6)), ["A"], p, info=infos[:1])
    assert rep["reason"] == "converged" and rep["hit_bound"] is False
