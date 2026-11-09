"""Colour stage on synthetic data: stripes, a box occluder, transparent unseen cells, and the stage wiring."""

import json
from types import SimpleNamespace

import numpy as np
from PIL import Image

from twin.contracts import STAGES, ColourParams
from twin.stages import colour, zbuffer
from twin.stages.ground import _write_laz

W, H = 1600, 900
K = np.array([[800.0, 0, 800.0], [0, 800.0, 450.0], [0, 0, 1.0]])
# Camera 1.6 m above the ground, looking along +x (same axes as test_zbuffer).
R = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
CAM16 = np.eye(4)
CAM16[:3, :3] = R
CAM16[2, 3] = 1.6
BOX = {
    "center": [6.0, 0.0, 0.75],
    "size": [2.0, 2.0, 1.5],
    "rotation": [1.0, 0.0, 0.0, 0.0],
}
RED, BLUE = np.array([200, 40, 40], np.uint8), np.array([40, 40, 200], np.uint8)
NO_POINTS = np.empty((0, 3))


def _ground(x0, x1, y0=-1.0, y1=1.0, step=0.05):
    x, y = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step), indexing="ij")
    return np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)])


def _stripe_image(cam_to_world):
    """Render the striped plane (0.5 m stripes along x) as the camera sees it: ray-plane hit per pixel."""
    u, v = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    d_cam = np.stack(
        [(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones_like(u)], axis=-1
    )
    d = d_cam @ cam_to_world[:3, :3].T
    cam = cam_to_world[:3, 3]
    t = -cam[2] / np.where(d[..., 2] < 0, d[..., 2], -1.0)
    hit = cam + t[..., None] * d
    stripe = np.floor(hit[..., 0] / 0.5).astype(np.int64) % 2 == 0
    img = np.where(stripe[..., None], RED, BLUE).astype(np.uint8)
    img[d[..., 2] >= 0] = 0
    return img


def test_striped_plane_recovers_stripe_colour():
    pts = _ground(4.0, 9.0)
    img = _stripe_image(CAM16)
    view = (CAM16, K, img, [])
    rgb, observed, n_views = colour.colour_points(
        pts, NO_POINTS, [view, view, view], ColourParams()
    )
    assert observed.mean() > 0.95, "the stripe plane in view is observed"
    assert np.all(n_views[observed] == 3), (
        "three identical views are all kept (top_k = 5)"
    )
    # Points sit on either side of a stripe edge; compare only those well inside a stripe.
    inside = observed & (np.abs((pts[:, 0] / 0.5) % 1 - 0.5) < 0.2)
    truth = np.where((np.floor(pts[:, 0] / 0.5) % 2 == 0)[:, None], RED, BLUE)
    err = np.abs(rgb[inside].astype(int) - truth[inside].astype(int)).max(axis=1)
    assert inside.sum() > 1000
    assert np.all(err <= 6), "median colour matches the stripe it lies on"


def test_box_occludes_ground_behind_it():
    img = np.full((H, W, 3), 128, np.uint8)
    view = (CAM16, K, img, [BOX])
    behind, front = (
        _ground(7.5, 8.5, -0.2, 0.2, 0.05),
        _ground(3.0, 4.0, -0.2, 0.2, 0.05),
    )
    _, seen_behind, _ = colour.colour_points(behind, NO_POINTS, [view], ColourParams())
    assert not seen_behind.any(), "the box hides the ground behind it"
    _, seen_front, _ = colour.colour_points(front, NO_POINTS, [view], ColourParams())
    assert seen_front.all(), "ground in front of the box is coloured"


def test_unseen_cells_stay_transparent():
    rng = np.random.default_rng(0)
    seen_xy = rng.uniform(0.0, 1.0, size=(400, 2))
    unseen_xy = rng.uniform(2.0, 3.0, size=(400, 2))
    xy = np.vstack([seen_xy, unseen_xy])
    rgb = np.full((len(xy), 3), 90, np.uint8)
    observed = np.r_[np.ones(400, bool), np.zeros(400, bool)]
    rgba, origin = colour.ortho_raster(xy, rgb, observed, 0.05)
    alpha = rgba[..., 3]
    # Rows run north to south; columns west to east. Column for x in [2, 3) must be transparent.
    cols_unseen = int(np.floor((2.5 - origin[0]) / 0.05))
    assert alpha[:, cols_unseen].max() == 0, (
        "cells with no observed point are transparent"
    )
    assert alpha.max() == 255 and (alpha[alpha > 0] == 255).all()
    assert np.all(rgba[alpha > 0][:, :3] == 90), "observed cells keep their colour"


def test_run_writes_outputs_and_labels_indeterminate_height(tmp_path, monkeypatch):
    root = tmp_path / "nuscenes"
    cam_dir = root / "samples" / "CAM_FRONT"
    cam_dir.mkdir(parents=True)
    cam_file = "samples/CAM_FRONT/f.png"
    cam_to_world = CAM16
    Image.fromarray(_stripe_image(cam_to_world)).save(root / cam_file)
    monkeypatch.setenv("NUSCENES_ROOT", str(root))

    run = tmp_path / "run"
    stage_dirs = {name: run / f"{s.number}_{name}" for name, s in STAGES.items()}
    for d in stage_dirs.values():
        d.mkdir(parents=True)
    ctx = SimpleNamespace(
        stage_dir=lambda name: stage_dirs[name],
        input_dir=lambda name: stage_dirs[name],
    )

    ground_xyz = _ground(4.0, 9.0)
    _write_laz(
        stage_dirs["ground"] / "ground.laz", ground_xyz, np.zeros(len(ground_xyz)), 2
    )
    _write_laz(
        stage_dirs["ground"] / "nonground.laz",
        np.array([[-20.0, 0.0, 1.0]]),
        np.zeros(1),
        1,
    )
    (stage_dirs["ground"] / "qa.json").write_text(json.dumps({"height_valid": False}))
    (stage_dirs["align"] / "poses.json").write_text(
        json.dumps(
            {
                "poses": [
                    {"timestamp_us": t, "matrix": np.eye(4).tolist()}
                    for t in (0, 1_000_000)
                ]
            }
        )
    )
    cam = {
        "timestamp_us": 500_000,
        "image": cam_file,
        "intrinsics": K.tolist(),
        "extrinsics": {
            "translation": [0.0, 0.0, 1.6],
            "rotation_wxyz": zbuffer.matrix_to_quat(R).tolist(),
        },
    }
    (stage_dirs["load"] / "cameras.json").write_text(json.dumps({"cameras": [cam]}))
    (stage_dirs["load"] / "boxes.json").write_text(
        json.dumps(
            {"sweeps": [{"timestamp_us": t, "boxes": []} for t in (0, 1_000_000)]}
        )
    )

    result = colour.run(ctx, ColourParams())

    assert result.status == "ok"
    qa = json.loads((stage_dirs["colour"] / "qa.json").read_text())
    assert qa["height_valid"] is False
    assert qa["ortho_label"] == colour.INDETERMINATE_LABEL, (
        "ortho is still made, labelled"
    )
    assert qa["views_median"] == 1.0
    assert (
        (stage_dirs["colour"] / "ortho.pgw")
        .read_text()
        .splitlines()[0]
        .startswith("0.05")
    )
    assert Image.open(stage_dirs["colour"] / "ortho.png").mode == "RGBA"
    with np.load(stage_dirs["colour"] / "rgb.npz") as f:
        assert f["rgb"].shape == (len(ground_xyz) + 1, 3)
        assert f["observed"][: len(ground_xyz)].mean() > 0.95
