"""Cross-drive registration: synthetic clouds only."""

import numpy as np

from twin import fixtures, merge


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
    man = json.loads((tmp_path / "manifest.json").read_text())
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
    deltas, qa = merge.fit_heights(works, corr, np.zeros(3), box(0, 0, 80, 40))
    assert qa["summary"]["n_fitted"] == 60
    # a and b meet halfway: the mean correction is zero, the gap of 0.4 m closes
    assert abs((deltas["a"][:, 2, 3] - deltas["b"][:, 2, 3]).mean() + 0.4) < 0.01
