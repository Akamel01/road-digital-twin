import pytest

"""Cross-drive registration: synthetic clouds only."""

import logging

import numpy as np

from twin import fixtures, merge
from twin.contracts import Params, StageResult


def _cloud(seed):
    w = fixtures.make_scene(seed=seed)[:, :3]
    rng = np.random.default_rng(seed)
    w[:, :2] += rng.uniform(-0.1, 0.1, (len(w), 2))
    return w


def _moved(xyz, yaw_deg, t):
    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    m = np.eye(4)
    m[:2, :2] = [[c, -s], [s, c]]
    m[:3, 3] = t
    return merge.apply(m, xyz - [20, 10, 0]) + [20, 10, 0]


def test_register_recovers_known_shift():
    ref = _cloud(0)
    other = _moved(_cloud(5), 1.0, [0.4, -0.3, 0.05])
    centre = np.array([20.0, 10.0, 0.0])
    res = merge.register_drives({"a": ref, "b": other}, centre)
    assert res["reference"] in ("a", "b")
    moved = "b" if res["reference"] == "a" else "a"
    assert res["info"][moved]["role"] == "registered"
    pair = res["pairs"][0]
    assert pair["after"]["p95_m"] < pair["before"]["p95_m"]
    assert pair["after"]["p95_m"] < 0.1


def test_no_overlap_stays_unregistered():
    a = _cloud(0)
    b = a + [500.0, 0, 0]
    res = merge.register_drives({"a": a, "b": b}, np.array([20.0, 10.0, 0.0]))
    assert [v["role"] for v in res["info"].values()].count("unregistered") == 1


def test_area_manifest_records_version_and_refuses_mismatch(tmp_path, monkeypatch):
    import json
    import logging

    import pytest
    from shapely.geometry import box, mapping

    from twin.contracts import Params

    pts = np.column_stack(
        [_cloud(1), np.ones(len(_cloud(1))), np.zeros(len(_cloud(1)))]
    )
    monkeypatch.setattr(merge, "build_drive", lambda *a: pts)
    monkeypatch.setattr(
        merge, "fit_heights", lambda *a: ({}, {"summary": {}, "sweeps": []})
    )
    area = {
        "name": "a",
        "dataset_version": "v1.0-trainval",
        "polygon": mapping(box(0, 0, 40, 20)),
        "drives": [
            {
                "scene": "s1",
                "date": "2018-01-01",
                "build_input": True,
                "scene_token": "t",
            }
        ],
    }
    log = logging.getLogger("t")
    merge.merge_area(area, tmp_path, Params(), log)
    man = json.loads((tmp_path / "run.json").read_text())
    assert man["data"]["nuscenes_version"] == "v1.0-trainval"
    with pytest.raises(ValueError, match="dataset version"):
        merge.merge_area(
            {**area, "dataset_version": "v1.0-mini"}, tmp_path, Params(), log
        )


def test_fit_heights_lifts_a_drive_that_sits_low(tmp_path):
    """Two drives over the same road; drive b's sweeps are 0.4 m too low and one of them is tilted."""
    import json

    from shapely.geometry import box

    rng = np.random.default_rng(0)
    works, corr = {}, {}
    for name, dz in (("a", 0.0), ("b", -0.4)):
        d = tmp_path / name / "3_align"
        d.mkdir(parents=True)
        rows, xs, ys, zs, sw = [], [], [], [], []
        for k in range(30):
            m = np.eye(4)
            m[0, 3], m[1, 3], m[2, 3] = 20 + k, 20, 1.0 + dz
            rows.append({"sweep": k, "matrix": m.tolist()})
            g = rng.uniform(-15, 15, (2500, 2))
            xs.append(g[:, 0])
            ys.append(g[:, 1])
            zs.append(np.full(len(g), -1.0))
            sw.append(np.full(len(g), k))
        (d / "poses.json").write_text(json.dumps({"crs": "x", "poses": rows}))
        np.savez(
            d / "ground_ego.npz",
            x=np.concatenate(xs),
            y=np.concatenate(ys),
            z=np.concatenate(zs),
            sweep=np.concatenate(sw).astype(np.uint16),
        )
        works[name] = tmp_path / name
        corr[name] = np.eye(4)
    drives = {n: merge.drive_ground(w, box(0, 0, 80, 40)) for n, w in works.items()}
    deltas, qa = merge.fit_heights(drives, corr, np.zeros(3))
    assert qa["summary"]["n_fitted"] == 60
    # a and b meet halfway: the mean correction is zero, the gap of 0.4 m closes
    assert abs((deltas["a"][:, 2, 3] - deltas["b"][:, 2, 3]).mean() + 0.4) < 0.01


def _ground(rng, offset, tilt):
    """Synthetic ground on a 40 x 40 m patch, a gentle bump plus a drive's height offset and tilt (slope along x, y)."""
    xy = rng.uniform(-20, 20, (80000, 2))
    z = 0.05 * np.sin(xy[:, 0] / 8) + offset + xy @ np.array(tilt)
    return np.column_stack([xy, z])


def _p95(a, b):
    return merge.ground_disagreement(merge.ground_cells(a), merge.ground_cells(b))[
        "p95_m"
    ]


def test_fit_zplanes_removes_offset_and_tilt_across_drives():
    rng = np.random.default_rng(1)
    truth = {
        "a": (0.0, (0.0, 0.0)),
        "b": (1.2, (0.05, -0.02)),
        "c": (-0.7, (-0.04, 0.03)),
    }
    clouds = {k: _ground(rng, o, t) for k, (o, t) in truth.items()}
    cells = {k: merge.ground_cells(v) for k, v in clouds.items()}
    assert _p95(clouds["a"], clouds["b"]) > 1.0
    planes = merge.fit_surfaces(cells, "a")
    assert np.allclose(planes["a"], 0)
    fixed = {k: merge.apply_surface(v, planes[k]) for k, v in clouds.items()}
    for x, y in (("a", "b"), ("a", "c"), ("b", "c")):
        assert _p95(fixed[x], fixed[y]) < 0.05


def test_fit_zplanes_ignores_a_layer_outlier_and_is_deterministic():
    rng = np.random.default_rng(2)
    a, b = _ground(rng, 0.0, (0, 0)), _ground(rng, 0.5, (0.02, 0))
    b[b[:, 0] > 14, 2] += 4.0  # 15% of b's ground sits on another layer (overpass)
    cells = {"a": merge.ground_cells(a), "b": merge.ground_cells(b)}
    p1, p2 = merge.fit_surfaces(cells, "a"), merge.fit_surfaces(cells, "a")
    assert np.array_equal(p1["b"], p2["b"])
    assert np.allclose(p1["b"], [-0.5, -0.02 * merge.SURFACE_SCALE_M, 0.0], atol=0.03)


def _four(rng, extra=None):
    out = {
        k: _ground(rng, o, (0.0, 0.0))
        for k, o in zip("abcd", (0.0, 0.3, -0.2, 0.1), strict=True)
    }
    if extra:
        out["b"] = extra(out["b"])
    return {k: merge.ground_cells(v) for k, v in out.items()}


def test_reject_layers_drops_an_overhead_patch_only():
    rng = np.random.default_rng(3)

    def roof(p):
        p = p.copy()
        p[(p[:, 0] > 5) & (p[:, 1] > 5), 2] += (
            4.5  # 'ground' points on a gantry above the road
        )
        return p

    cells = _four(rng, roof)
    plane = merge.fit_surfaces(cells, "a", 1)
    shifted = {k: merge.apply_cells(v, plane[k]) for k, v in cells.items()}
    kept, n = merge.reject_layers(shifted)
    assert n["b"] > 400  # about 15 x 15 m of 0.5 m cells
    assert n["a"] + n["c"] + n["d"] < 0.02 * len(cells["a"])
    kept = {k: {c: cells[k][c] for c in kept[k]} for k in cells}
    fit = merge.fit_surfaces(kept, "a", 1)
    d = merge.ground_disagreement(
        merge.apply_cells(kept["a"], fit["a"]), merge.apply_cells(kept["b"], fit["b"])
    )
    assert d["p95_m"] < 0.05


def test_curved_drive_is_recovered_by_degree_two_not_one():
    rng = np.random.default_rng(4)
    bowl = lambda p: (
        p + np.column_stack([np.zeros(len(p)), np.zeros(len(p)), 0.002 * p[:, 0] ** 2])
    )
    cells = _four(rng, bowl)

    def worst(deg):
        c = merge.fit_surfaces(cells, "a", deg)
        return max(
            merge.ground_disagreement(
                merge.apply_cells(cells[x], c[x]), merge.apply_cells(cells[y], c[y])
            )["p95_m"]
            for x, y in (("a", "b"), ("b", "c"), ("b", "d"), ("c", "d"))
        )

    assert worst(1) > 0.15
    assert worst(2) < 0.05


def test_degree_two_does_not_invent_curvature_from_noise():
    rng = np.random.default_rng(5)
    noisy = lambda p: (
        p + np.column_stack([np.zeros((len(p), 2)), rng.normal(0, 0.03, len(p))])
    )
    cells = {
        k: merge.ground_cells(noisy(_ground(rng, o, (0.01, 0.0))))
        for k, o in zip("abc", (0.0, 0.4, -0.3), strict=True)
    }
    c = merge.fit_surfaces(cells, "a", 2)
    assert max(np.abs(c[k][3:]).max() for k in "abc") < 0.02  # in metres at 50 m


def _scene():
    return {"scene_token": "tok", "dataset_version": "v1"}


def test_build_drive_cache_key_changes_with_params():
    scene = _scene()
    k1 = merge.build_drive_cache_key(scene, Params())
    k2 = merge.build_drive_cache_key(scene, Params(seed=7))
    assert k1 != k2


def test_build_drive_reuses_cached_clip_when_key_matches(tmp_path, monkeypatch):
    scene = _scene()
    params = Params()
    monkeypatch.setattr(merge.runner, "_git", lambda *a: "abc\n")
    monkeypatch.setattr(merge.runner, "dataset_version", lambda: "v1")
    key = merge.build_drive_cache_key(scene, params)
    arr = np.arange(10, dtype=float).reshape(2, 5)
    np.save(tmp_path / "clip.npy", arr)
    (tmp_path / "clip.npy.key").write_text(key)

    called = {"n": 0}

    def fake_run(ctx, p):
        called["n"] += 1
        return StageResult(status="ok", files=[], metrics={})

    monkeypatch.setattr(merge.load, "run", fake_run)
    monkeypatch.setattr(merge.mask, "run", fake_run)
    monkeypatch.setattr(merge.align, "run_icp", fake_run)

    out = merge.build_drive(scene, tmp_path, None, params, logging.getLogger("t"))
    assert called["n"] == 0
    assert np.array_equal(out, arr)


def test_cache_key_changes_with_head(monkeypatch):
    monkeypatch.setattr(merge.runner, "_git", lambda *a: "abc\n")
    k1 = merge.build_drive_cache_key(_scene(), Params())
    monkeypatch.setattr(merge.runner, "_git", lambda *a: "def\n")
    assert merge.build_drive_cache_key(_scene(), Params()) != k1


def test_cache_key_changes_with_align_param():
    assert merge.build_drive_cache_key(_scene(), Params()) != merge.build_drive_cache_key(
        _scene(), Params(align={"voxel_m": 0.7})
    )


def test_missing_key_file_rebuilds(tmp_path, monkeypatch):
    np.save(tmp_path / "clip.npy", np.zeros((1, 5)))

    def boom(ctx, p):
        raise RuntimeError("rebuild")

    monkeypatch.setattr(merge.load, "run", boom)
    with pytest.raises(RuntimeError, match="rebuild"):
        merge.build_drive(_scene(), tmp_path, None, Params(), logging.getLogger("t"))


def test_build_drive_rebuilds_and_writes_key(tmp_path, monkeypatch):
    import json

    scene = _scene()
    params = Params()
    monkeypatch.setattr(merge.runner, "_git", lambda *a: "abc\n")
    monkeypatch.setattr(merge.runner, "dataset_version", lambda: "v1")
    work = tmp_path
    np.save(work / "clip.npy", np.zeros((1, 5)))
    (work / "clip.npy.key").write_text("wrong")

    def stage_run_factory(name):
        def run(ctx, p):
            d = ctx.stage_dir(name)
            d.mkdir(parents=True, exist_ok=True)
            if name == "load":
                (d / "poses.json").write_text(
                    json.dumps({"poses": [{"matrix": __import__("numpy").eye(4).flatten().tolist()}]})
                )
            elif name == "mask":
                data = {f: np.array([0.0, 1.0, 2.0]) for f in merge.mask.POINT_FIELDS}
                __import__("numpy").savez(d / "points.npz", **data)
            elif name == "align":
                (d / "poses.json").write_text(
                    json.dumps({"poses": [{"matrix": __import__("numpy").eye(4).flatten().tolist()}]})
                )
            return StageResult(status="ok", files=[], metrics={})

        return run

    monkeypatch.setattr(merge.load, "run", stage_run_factory("load"))
    monkeypatch.setattr(merge.mask, "run", stage_run_factory("mask"))
    monkeypatch.setattr(merge.align, "run_icp", stage_run_factory("align"))

    xyz = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]])
    monkeypatch.setattr(
        merge.ground, "aligned_points", lambda fields, a, b: (xyz, np.ones(3), np.zeros(3, dtype=int))
    )
    monkeypatch.setattr(merge.shapely, "contains_xy", lambda poly, x, y: np.array([True, True, True]))

    out = merge.build_drive(scene, work, None, params, logging.getLogger("t"))
    assert out.shape == (3, 5)
    assert (work / "clip.npy.key").read_text().strip() == merge.build_drive_cache_key(scene, params)
