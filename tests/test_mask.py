"""Stage 2 mask: synthetic points and boxes, no devkit, no data."""

import json
import logging
import math

import numpy as np
import pytest

from twin import registry
from twin.contracts import MaskParams
from twin.runner import StageContext
from twin.stages import mask
from twin.stages.load import qz

FIELDS = ("x", "y", "z", "intensity", "sweep")
CENTRE = [10.0, 5.0, 0.0]


def _box(size=(2.0, 4.0, 1.5), yaw_deg=0.0, parked=False, centre=CENTRE):
    """nuScenes-style box: size is [w, l, h], length along the box's local x axis."""
    q = qz(math.radians(yaw_deg))
    return {
        "token": "t",
        "category": "vehicle.car",
        "center": list(centre),
        "size": list(size),
        "rotation": [float(v) for v in q],
        "parked": parked,
    }


def _local_to_global(local, yaw_deg, centre=CENTRE):
    a = math.radians(yaw_deg)
    lx, ly, lz = local
    return [
        centre[0] + lx * math.cos(a) - ly * math.sin(a),
        centre[1] + lx * math.sin(a) + ly * math.cos(a),
        centre[2] + lz,
    ]


def _stage(tmp_path, pts, sweep_boxes):
    """Write a synthetic load folder and return a StageContext whose mask folder is empty.

    pts: list of (x, y, z, intensity, sweep). sweep_boxes: {sweep index: [box dicts]}.
    """
    run_dir = tmp_path / "run"
    load_dir = run_dir / "1_load"
    load_dir.mkdir(parents=True)
    arr = np.array(pts, dtype=float)
    np.savez_compressed(
        load_dir / "points.npz",
        x=arr[:, 0].astype(np.float64),
        y=arr[:, 1].astype(np.float64),
        z=arr[:, 2].astype(np.float64),
        intensity=arr[:, 3].astype(np.float32),
        sweep=arr[:, 4].astype(np.uint16),
    )
    n_sweeps = max([*sweep_boxes, *arr[:, 4].astype(int).tolist()], default=-1) + 1
    sweeps = [
        {"sweep": i, "timestamp_us": i, "boxes": sweep_boxes.get(i, [])}
        for i in range(n_sweeps)
    ]
    (load_dir / "boxes.json").write_text(
        json.dumps({"crs": "EPSG:32619", "sweeps": sweeps})
    )
    ctx = StageContext(
        run_dir=run_dir, scene_token="s", seed=0, log=logging.getLogger("test")
    )
    return ctx, run_dir / "2_mask"


def _run(tmp_path, pts, sweep_boxes, margin=0.3):
    ctx, out = _stage(tmp_path, pts, sweep_boxes)
    result = mask.run(ctx, MaskParams(box_margin_m=margin))
    assert result.status == "ok"
    return result, out


def _load(path):
    with np.load(path) as f:
        return {k: f[k] for k in f.files}


def test_oriented_box_removes_inside_points_and_keeps_outside(tmp_path):
    yaw = 30.0
    box = _box(size=(2.0, 4.0, 1.5), yaw_deg=yaw)
    inside = [
        _local_to_global((1.5, 0.5, 0.2), yaw),
        _local_to_global((-1.9, 0.9, 0.0), yaw),
    ]
    outside = [
        _local_to_global((2.5, 0.0, 0.0), yaw),
        _local_to_global((0.0, 1.5, 0.0), yaw),
    ]
    # Global axis-aligned point that lies inside the unrotated box but outside the 30° box.
    axis_only = [CENTRE[0] + 0.0, CENTRE[1] + 1.8, 0.0]
    pts = [(*p, 10.0, 0) for p in inside + outside + [axis_only]]

    _, out = _run(tmp_path, pts, {0: [box]}, margin=0.0)

    kept = _load(out / "points.npz")
    assert len(kept["x"]) == 3
    kept_xy = set(zip(np.round(kept["x"], 6), np.round(kept["y"], 6)))
    for p in outside + [axis_only]:
        assert (round(p[0], 6), round(p[1], 6)) in kept_xy
    for p in inside:
        assert (round(p[0], 6), round(p[1], 6)) not in kept_xy


def test_margin_honoured_at_boundary(tmp_path):
    box = _box(size=(2.0, 4.0, 1.5))  # half length 2.0 along x, half width 1.0 along y
    on_edge = _local_to_global((2.5, 0.0, 0.0), 0.0)  # 2.0 + margin 0.5 exactly
    just_out = _local_to_global((2.6, 0.0, 0.0), 0.0)
    _, out = _run(
        tmp_path, [(*on_edge, 1.0, 0), (*just_out, 1.0, 0)], {0: [box]}, margin=0.5
    )

    kept = _load(out / "points.npz")
    assert len(kept["x"]) == 1
    assert kept["x"][0] == pytest.approx(just_out[0])


def test_margin_zero_keeps_points_just_outside_box(tmp_path):
    box = _box(size=(2.0, 4.0, 1.5))
    just_out = _local_to_global((2.05, 0.0, 0.0), 0.0)
    _, out = _run(tmp_path, [(*just_out, 1.0, 0)], {0: [box]}, margin=0.0)
    assert len(_load(out / "points.npz")["x"]) == 1


def test_parked_points_go_to_parked_file_with_box_index(tmp_path):
    moving = _box(centre=[50.0, 5.0, 0.0])
    parked = _box(parked=True)
    p_in = _local_to_global((0.5, 0.0, 0.3), 0.0)
    m_in = _local_to_global((0.0, 0.0, 0.2), 0.0, centre=[50.0, 5.0, 0.0])
    free = [30.0, 5.0, 0.0]
    pts = [(*p_in, 2.0, 0), (*m_in, 3.0, 0), (*free, 4.0, 0)]
    result, out = _run(tmp_path, pts, {0: [moving, parked]}, margin=0.0)

    kept = _load(out / "points.npz")
    park = _load(out / "parked.npz")
    assert list(kept["intensity"]) == [4.0]
    assert list(park["intensity"]) == [2.0]
    assert list(park["box"]) == [1]  # index 1: the parked box in sweep 0's list
    assert result.metrics == {
        "n_in": 2,
        "n_kept": 1,
        "n_parked": 1,
        "n_dropped_moving": 1,
    }


def test_box_applies_only_to_its_own_sweep(tmp_path):
    box = _box()
    inside = _local_to_global((0.0, 0.0, 0.0), 0.0)
    pts = [(*inside, 1.0, 0), (*inside, 2.0, 1)]  # same place, two sweeps
    _, out = _run(tmp_path, pts, {0: [box]}, margin=0.0)

    kept = _load(out / "points.npz")
    assert list(kept["sweep"]) == [1]
    assert list(kept["intensity"]) == [2.0]


def test_output_fields_and_dtypes_match_input(tmp_path):
    parked = _box(parked=True)
    pts = [(*_local_to_global((0.0, 0.0, 0.0), 0.0), 9.0, 0), (30.0, 5.0, 1.0, 7.0, 1)]
    _, out = _run(tmp_path, pts, {0: [parked]})
    source = _load(tmp_path / "run" / "1_load" / "points.npz")

    points = _load(out / "points.npz")
    park = _load(out / "parked.npz")
    assert set(points) == set(FIELDS)
    assert set(park) == set(FIELDS) | {"box"}
    for data in (points, park):
        for field in FIELDS:
            assert data[field].dtype == source[field].dtype, field
    assert len(park["x"]) == 1 and len(points["x"]) == 1


def test_no_boxes_keeps_every_point(tmp_path):
    pts = [(1.0, 2.0, 0.0, 5.0, 0), (3.0, 4.0, 0.0, 6.0, 0)]
    result, out = _run(tmp_path, pts, {})
    assert len(_load(out / "points.npz")["x"]) == 2
    assert len(_load(out / "parked.npz")["x"]) == 0
    assert result.metrics == {
        "n_in": 0,
        "n_kept": 2,
        "n_parked": 0,
        "n_dropped_moving": 0,
    }


def test_stage_is_registered():
    assert registry.lookup("mask", "boxes") is mask.run


def test_workers_do_not_change_output(tmp_path):
    rng = np.random.default_rng(0)
    n = 3000
    pts = {
        "x": rng.uniform(5, 15, n),
        "y": rng.uniform(0, 10, n),
        "z": rng.uniform(-1, 2, n),
        "intensity": rng.uniform(0, 255, n).astype(np.float32),
        "sweep": (np.arange(n) % 7).astype(np.uint16),
    }
    boxes = {
        "sweeps": [
            {"sweep": s, "boxes": [_box(parked=s % 4 == 0, centre=[8 + s, 5, 0])]}
            for s in range(0, 7, 2)
        ]
    }
    got = []
    for w in (1, 3):
        run = tmp_path / f"w{w}"
        (run / "1_load").mkdir(parents=True)
        np.savez(run / "1_load" / "points.npz", **pts)
        (run / "1_load" / "boxes.json").write_text(json.dumps(boxes))
        ctx = StageContext(run, "t", 0, logging.getLogger("t"))
        res = mask.run(ctx, MaskParams(workers=w))
        got.append(
            (
                res.metrics,
                (run / "2_mask" / "points.npz").read_bytes(),
                (run / "2_mask" / "parked.npz").read_bytes(),
            )
        )
    assert got[0][0]["n_dropped_moving"] > 0 and got[0][0]["n_parked"] > 0
    assert got[0] == got[1]
