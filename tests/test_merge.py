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

    pts = np.column_stack([_cloud(1), np.ones(len(_cloud(1))), np.zeros(len(_cloud(1)))])
    monkeypatch.setattr(merge, "build_drive", lambda *a: pts)
    area = {
        "name": "a",
        "dataset_version": "v1.0-trainval",
        "polygon": mapping(box(0, 0, 40, 20)),
        "drives": [{"scene": "s1", "date": "2018-01-01", "build_input": True, "scene_token": "t"}],
    }
    log = logging.getLogger("t")
    merge.merge_area(area, tmp_path, Params(), log)
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["data"]["nuscenes_version"] == "v1.0-trainval"
    with pytest.raises(ValueError, match="dataset version"):
        merge.merge_area({**area, "dataset_version": "v1.0-mini"}, tmp_path, Params(), log)
