"""Semantics stage on synthetic data: a painted stripe on a plane, a stub segmenter, voting, fusion."""

import numpy as np

from tests.test_colour import CAM16, NO_POINTS, H, K, W, _ground
from twin import gpulease
from twin.contracts import Pipeline, SemanticsParams
from twin.stages import semantics
from twin.stages.semantics import MARKING, build_variants, vote

P = SemanticsParams()
STRIPE_HALF_M = 0.15


def stub_segmenter(img):
    """What a perfect segmenter says about the plane z=0 with a stripe along x at |y| < 0.15."""
    u, v = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    d = np.stack(
        [(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones_like(u)], axis=-1
    )
    d = d @ CAM16[:3, :3].T
    t = -CAM16[2, 3] / np.where(d[..., 2] < 0, d[..., 2], -1.0)
    y = CAM16[1, 3] + t * d[..., 1]
    return np.where((d[..., 2] < 0) & (np.abs(y) < STRIPE_HALF_M), MARKING, 0).astype(
        np.uint8
    )


def _raster():
    pts = _ground(4.0, 9.0, -1.0, 1.0)
    view = (CAM16, K, np.zeros((H, W, 3), np.uint8), [])
    return vote(pts, NO_POINTS, [view, view], stub_segmenter, 0.1)


def _line(x0, x1, y):
    coords = [[float(x), y, 0.0] for x in np.arange(x0, x1 + 0.01, 1.0)]
    return {
        "type": "Feature",
        "properties": {
            "id": f"l{y}-{x0}",
            "kind": "marking",
            "evidence": ["lidar"],
            "reliability": "observed",
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def test_vote_labels_the_stripe_only():
    r = _raster()
    p = semantics.probability(r, "marking")
    y = r["origin"][1] + (np.arange(r["ny"]) + 0.5) * 0.1
    on = np.abs(y) < 0.1
    seen = (r["images"] >= 2).reshape(r["ny"], r["nx"])
    p = p.reshape(r["ny"], r["nx"])
    assert seen.sum() >= 1000
    assert p[on][seen[on]].mean() > 0.9, "the stripe cells are marking"
    assert p[np.abs(y) > 0.3][seen[np.abs(y) > 0.3]].max() < 0.1, "the rest is not"


def test_fusion_keeps_supported_drops_unsupported_adds_camera_only():
    r = _raster()
    on_stripe, off_stripe, unseen = (
        _line(5, 8, 0.0),
        _line(5, 8, 0.8),
        _line(40, 45, 0.0),
    )
    lidar = {
        "markings.geojson": [on_stripe, off_stripe, unseen],
        "crosswalks.geojson": [],
        "curbs.geojson": [],
        "ramps.geojson": [],
    }
    camera, fused, counts = build_variants(lidar, r, [], P)
    assert counts["markings.geojson"] == {
        "supported": 1,
        "not_observed": 1,
        "dropped": 1,
        "n_lidar": 3,
        "n_camera": len(camera["markings.geojson"]),
        "added_camera": 0,
    }
    ids = {
        f["properties"]["id"]: f["properties"]["source"]
        for f in fused["markings.geojson"]
    }
    assert ids == {"l0.0-5": "lidar+camera", "l0.0-40": "lidar"}
    # With no lidar feature at all, the camera line is added and flagged.
    camera, fused, _ = build_variants({k: [] for k in lidar}, r, [], P)
    assert len(camera["markings.geojson"]) == 1
    added = fused["markings.geojson"][0]["properties"]
    assert (
        added["source"] == "camera"
        and added["evidence"] == ["camera"]
        and added["n_images"] == 2
    )


def test_semantics_is_off_by_default_but_takes_the_gpu_lease_when_on():
    assert Pipeline().semantics.enabled is False
    rerun = {"type": "rerun", "run_id": "r", "from_stage": "semantics"}
    assert not gpulease.needs_gpu(rerun, lambda v: {"colour": {"enabled": False}})
    assert gpulease.needs_gpu(
        rerun, lambda v: {"semantics": {"method": "mapillary-m2f"}}
    )


def _curb_ramp_raster():
    pts = _ground(4.0, 9.0, -1.0, 1.0)
    view = (CAM16, K, np.zeros((H, W, 3), np.uint8), [])
    seg = lambda img: np.full((H, W), semantics.CURB_RAMP, dtype=np.uint8)
    return vote(pts, NO_POINTS, [view, view], seg, 0.1)


def test_vistas_curb_cut_maps_to_curb_ramp():
    assert semantics.VISTAS_CLASSES["Curb Cut"] == semantics.CURB_RAMP == 6


def test_vote_curb_ramp_bucket_populated():
    r = _curb_ramp_raster()
    assert r["curb_ramp"].sum() > 0


def test_probability_on_evidence_accept_curb_ramp():
    r = _curb_ramp_raster()
    p = semantics.probability(r, "curb_ramp")
    assert np.any(p > 0)
    on = semantics._on(r, "curb_ramp", P)
    assert on.any()
    cells = np.flatnonzero(on)
    ev = semantics._evidence(r, cells[:5], "curb_ramp")
    assert ev["votes"] > 0
    # "ramp" alias equivalence
    assert np.array_equal(semantics.probability(r, "ramp"), p)
    assert np.array_equal(semantics._on(r, "ramp", P), on)


def test_build_variants_lidar_ramps_counts_fused():
    r = _curb_ramp_raster()
    ramp = _line(5, 8, 0.0)
    lidar = {
        "markings.geojson": [],
        "crosswalks.geojson": [],
        "curbs.geojson": [],
        "ramps.geojson": [ramp],
    }
    _camera, fused, counts = build_variants(lidar, r, [], P)
    c = counts["ramps.geojson"]
    assert c["n_lidar"] == 1
    assert c["supported"] + c["not_observed"] + c["dropped"] == 1
    assert len(fused["ramps.geojson"]) >= 1
