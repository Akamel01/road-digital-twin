"""Stage 4 ground: synthetic plane and sweeps, no devkit, no data."""

import json
import logging

import numpy as np
import pytest

from twin import registry
from twin.contracts import GroundParams
from twin.runner import StageContext

SLOPE = 0.02
NOISE_M = 0.003


def _plane(rng, shift_xy=(0.0, 0.0)):
    x, y = np.meshgrid(
        np.arange(0.0, 40.0, 0.25), np.arange(0.0, 20.0, 0.25), indexing="ij"
    )
    x = x.ravel() + shift_xy[0]
    y = y.ravel() + shift_xy[1]
    z = SLOPE * x + rng.normal(0, NOISE_M, x.size)
    return np.column_stack([x, y, z, np.full(x.size, 0.2)])


def _polygon(x0, x1, y0, y1):
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"type": "Polygon", "coordinates": [ring]}


def _write_run(tmp_path, sweeps, align_qa=None, facilities=None):
    """sweeps: list of (N, 4) world-frame arrays (x, y, z, intensity), one per sweep.

    Dataset poses translate each sweep along x by 0.2 m per sweep; align's refined poses equal them,
    so the ego round trip must return the points to where they were.
    """
    run = tmp_path / "run"
    mats = []
    for k in range(len(sweeps)):
        m = np.eye(4)
        m[0, 3] = 0.2 * k
        mats.append(m.tolist())
    entries = [
        {"sweep": k, "timestamp_us": k * 50_000, "matrix": m}
        for k, m in enumerate(mats)
    ]
    (run / "1_load").mkdir(parents=True)
    (run / "1_load" / "poses.json").write_text(
        json.dumps({"crs": "EPSG:32619", "poses": entries})
    )
    fc = {
        "type": "FeatureCollection",
        "features": facilities or [],
    }
    (run / "1_load" / "facilities.geojson").write_text(json.dumps(fc))

    (run / "2_mask").mkdir()
    xyz = np.vstack([s[:, :3] for s in sweeps])
    inten = np.concatenate([s[:, 3] for s in sweeps]).astype(np.float32)
    sweep = np.concatenate(
        [np.full(len(s), k, np.uint16) for k, s in enumerate(sweeps)]
    )
    np.savez_compressed(
        run / "2_mask" / "points.npz",
        x=xyz[:, 0],
        y=xyz[:, 1],
        z=xyz[:, 2],
        intensity=inten,
        sweep=sweep,
    )

    (run / "3_align").mkdir()
    (run / "3_align" / "poses.json").write_text(
        json.dumps({"crs": "EPSG:32619", "poses": entries})
    )
    qa = align_qa or {"fallback_used": False, "fallback_reason": None}
    (run / "3_align" / "qa.json").write_text(json.dumps(qa))

    ctx = StageContext(
        run_dir=run, scene_token="s", seed=0, log=logging.getLogger("test")
    )
    return ctx, run / "4_ground"


def _sweeps(rng, n=3, offset_sweep=None, offset_m=0.0):
    out = []
    for k in range(n):
        pts = _plane(rng, shift_xy=(0.05 * k, 0.03 * k))
        if offset_sweep == k:
            pts[:, 2] += offset_m
        out.append(pts)
    return out


@pytest.mark.parametrize("method", ["ransac-tiles", "csf"])
def test_plane_ground_rmse_under_2cm(tmp_path, method):
    rng = np.random.default_rng(0)
    ctx, out = _write_run(tmp_path, _sweeps(rng))
    result = registry.lookup("ground", method)(ctx, GroundParams())
    assert result.status == "ok"
    qa = json.loads((out / "qa.json").read_text())
    assert qa["rmse_m"] < 0.02
    assert qa["method"] == method
    assert qa["height_valid"] is True
    assert (out / "ground.laz").is_file() and (out / "nonground.laz").is_file()
    assert (out / "surface.npz").is_file()


def test_sweep_offset_flags_height_invalid(tmp_path):
    rng = np.random.default_rng(0)
    ctx, out = _write_run(tmp_path, _sweeps(rng, offset_sweep=2, offset_m=0.2))
    # the QA counts ground-class points only, and a tight RANSAC calls a 0.2 m offset sweep non-ground, so
    # this test uses a loose threshold (ground-only QA cannot see an offset the split has already thrown out)
    registry.lookup("ground", "ransac-tiles")(ctx, GroundParams(ransac_dist_m=0.3))
    qa = json.loads((out / "qa.json").read_text())
    assert qa["z_disagreement_p95_m"] > GroundParams().qa_max_p95_m
    assert qa["height_valid"] is False
    assert "disagreement" in qa["height_invalid_reason"]


def test_align_fallback_forces_height_invalid(tmp_path):
    rng = np.random.default_rng(0)
    qa_in = {"fallback_used": True, "fallback_reason": "forced"}
    ctx, out = _write_run(tmp_path, _sweeps(rng), align_qa=qa_in)
    registry.lookup("ground", "ransac-tiles")(ctx, GroundParams())
    qa = json.loads((out / "qa.json").read_text())
    assert (
        qa["z_disagreement_p95_m"] < GroundParams().qa_max_p95_m
    )  # the disagreement test alone passes
    assert qa["height_valid"] is False
    assert "align fell back" in qa["height_invalid_reason"]


def test_observed_core_marks_not_scanned(tmp_path):
    rng = np.random.default_rng(0)
    facilities = [
        {
            "type": "Feature",
            "geometry": _polygon(5, 25, 2, 12),
            "properties": {"id": "I-scanned"},
        },
        {
            "type": "Feature",
            "geometry": _polygon(100, 110, 0, 10),
            "properties": {"id": "S-empty"},
        },
    ]
    ctx, out = _write_run(tmp_path, _sweeps(rng), facilities=facilities)
    registry.lookup("ground", "ransac-tiles")(ctx, GroundParams())
    qa = json.loads((out / "qa.json").read_text())
    assert qa["observed_core"]["I-scanned"] > 0.95
    assert qa["observed_core"]["S-empty"] == 0.0
    assert qa["not_scanned_enough"] == ["S-empty"]


def test_ransac_ground_repeats_exactly_and_follows_the_seed():
    """Same points and seed give the same ground mask every time (issue 139); a different seed may differ."""
    from twin.contracts import GroundParams
    from twin.stages.ground import ransac_ground

    rng = np.random.default_rng(0)
    n = 4000
    xyz = np.column_stack(
        [rng.uniform(0, 10, n), rng.uniform(0, 10, n), rng.normal(0, 0.01, n)]
    )
    xyz[:600, 2] += rng.uniform(0.3, 2.0, 600)  # clutter above the road
    first = ransac_ground(xyz, GroundParams(), seed=7)
    for _ in range(3):
        assert (ransac_ground(xyz, GroundParams(), seed=7) == first).all()
    assert first[600:].mean() > 0.9 and first[:600].mean() < 0.2
