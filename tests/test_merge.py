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
