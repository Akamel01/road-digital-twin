import numpy as np
import pytest

from twin import fixtures, joint_align, merge, reference_split


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


def _joint_expected(drives, clouds, anchors, centre):
    """Mirror align_joint seeding/solve for provenance checks."""
    graph = joint_align.build_edges(drives, clouds, clouds, anchors, centre)
    chained = merge.register_drives(
        {k: np.asarray(clouds[k], float)[:, :3] for k in graph["ids"]},
        centre,
        seed=0,
        ground={k: np.asarray(clouds[k], float)[:, :3] for k in graph["ids"]},
    )
    x0 = np.zeros(3 * len(graph["nonref"]))
    for i, k in enumerate(graph["nonref"]):
        t = chained["corrections"].get(k, np.eye(4))
        x0[3 * i] = float(t[0, 3])
        x0[3 * i + 1] = float(t[1, 3])
        x0[3 * i + 2] = float(np.arctan2(t[1, 0], t[0, 0]))
    graph["x0"] = x0

    if graph["anchor_c"].shape[0] > 0 and graph["A_tree"] is not None:
        bnd = np.array([2.0, 2.0, 0.1])
        anchor_seeds = {}

        def _anchor_cost(xi, pk):
            cur = joint_align._apply(joint_align._transform(xi[0], xi[1], xi[2]), pk)
            _, idx = graph["A_tree"].query(cur[:, :2], k=1)
            dist = np.linalg.norm(cur[:, :2] - graph["anchor_c"][idx, :2], axis=1)
            mask = dist <= merge.OVERLAP_DIST_M
            if mask.sum() < 20:
                return float(np.mean(dist * dist))
            d = cur[mask, :2] - graph["anchor_c"][idx[mask], :2]
            return float(np.mean(np.sum(d * d, axis=1)))

        grid = (-0.6, -0.3, 0.0, 0.3, 0.6)
        for i, k in enumerate(graph["nonref"]):
            pk = graph["src_sets"][k]
            if len(pk) == 0:
                continue
            candidates = [np.clip(graph["x0"][3 * i : 3 * i + 3], -bnd, bnd), np.zeros(3)]
            for dx in grid:
                for dy in grid:
                    candidates.append(np.array([dx, dy, 0.0]))
            scored = []
            for xinit in candidates:
                xi = np.clip(np.array(xinit, float), -bnd, bnd)
                scored.append((_anchor_cost(xi, pk), xi))
            scored.sort(key=lambda t: t[0])
            best_x, best_c = scored[0][1], scored[0][0]
            refine_n = 6 if len(graph["nonref"]) <= 2 else min(len(scored), 12)
            for _, xinit in scored[:refine_n]:
                xi = np.clip(np.array(xinit, float), -bnd, bnd)
                for radius in (2.0, 1.0, merge.OVERLAP_DIST_M):
                    for _ in range(8):
                        cur = joint_align._apply(joint_align._transform(xi[0], xi[1], xi[2]), pk)
                        _, idx = graph["A_tree"].query(cur[:, :2], k=1)
                        dist = np.linalg.norm(cur[:, :2] - graph["anchor_c"][idx, :2], axis=1)
                        mask = dist <= radius
                        if mask.sum() < 20:
                            break
                        a = cur[mask, :2]
                        b = graph["anchor_c"][idx[mask], :2]
                        ca, cb = a.mean(0), b.mean(0)
                        aa, bb = a - ca, b - cb
                        h = aa.T @ bb
                        u, _, vt = np.linalg.svd(h)
                        r2 = vt.T @ u.T
                        if np.linalg.det(r2) < 0:
                            vt[1, :] *= -1
                            r2 = vt.T @ u.T
                        t2 = cb - r2 @ ca
                        delta = np.eye(4)
                        delta[:2, :2] = r2
                        delta[0, 3] = t2[0]
                        delta[1, 3] = t2[1]
                        newT = delta @ joint_align._transform(xi[0], xi[1], xi[2])
                        nx = np.array([newT[0, 3], newT[1, 3], np.arctan2(newT[1, 0], newT[0, 0])], float)
                        nx = np.clip(nx, -bnd, bnd)
                        if np.linalg.norm(nx - xi) < 1e-7:
                            xi = nx
                            break
                        xi = nx
                cst = _anchor_cost(xi, pk)
                if cst < best_c:
                    best_c, best_x = cst, xi
            anchor_seeds[k] = best_x
        x_chained = np.array(graph["x0"], float)
        x_anchor = np.array(graph["x0"], float)
        for i, k in enumerate(graph["nonref"]):
            if k in anchor_seeds:
                x_anchor[3 * i : 3 * i + 3] = anchor_seeds[k]
        candidates = [x_chained, x_anchor] if len(graph["nonref"]) <= 2 else [x_anchor, x_chained]
        graph["x0"] = joint_align._select_multistart(graph, candidates)

    seed_poses = joint_align._unpack(graph, graph["x0"])
    graph["pair_corr"] = joint_align._pair_correspondences(graph, seed_poses)
    solve_params = {"max_nfev": 2000, "outer": 2}
    solve_out = joint_align.solve(graph, params=solve_params)
    sol = solve_out["sol"]
    return joint_align._unpack(graph, sol.x), solve_out


def test_joint_recovers_known_shift():
    rng = np.random.default_rng(7)
    ref = _cloud(0)
    # same geometry, independent observation noise - ground-truth shift is recoverable
    other = ref + rng.uniform(-0.02, 0.02, ref.shape)
    other = _moved(other, 1.0, [0.4, -0.3, 0.05])
    centre = np.array([20.0, 10.0, 0.0])
    clouds = {"a": ref, "b": other}
    anchors = ref[::4]
    res = joint_align.align_joint(list(clouds), clouds, clouds, anchors, centre)
    assert res["method"] == "joint-pose-graph"
    moved = "b" if res["reference"] == "a" else "a"
    t = res["corrections"][moved]
    err = np.linalg.norm(t[:2, 3] + np.array([0.4, -0.3]))
    # CR3: prove returned value came from solver, not chained seed.
    expected, solve_out = _joint_expected(list(clouds), clouds, anchors, centre)
    assert np.allclose(res["corrections"][moved], expected[moved], rtol=1e-3, atol=1e-3)
    assert res["convergence"]["success"] is True
    assert res["convergence"]["nfev"] == solve_out["convergence"]["nfev"]
    assert res["convergence"]["cost"] == pytest.approx(solve_out["convergence"]["cost"], rel=1e-2)
    assert res["solver_params"]["loss"] == "huber"
    assert res["solver_params"]["f_scale"] == 0.5
    assert res["solver_params"]["max_nfev"] == 2000
    assert res["solver_params"]["max_nfev_effective_per_call"] == 2000
    assert err < 0.05, f"joint err {err:.3f}m"
    pair = res["pairs"][0]
    assert pair["after"] is not None
    assert pair["after"]["p95_m"] < 0.1
    assert "anchor_residuals" in res
    assert "pair_residuals" in res


def test_joint_fallback_low_anchors():
    ref = _cloud(0)
    other = _moved(_cloud(5), 1.0, [0.4, -0.3, 0.05])
    centre = np.array([20.0, 10.0, 0.0])
    clouds = {"a": ref, "b": other}
    res = joint_align.align_joint(list(clouds), clouds, clouds, [], centre)
    assert res["method"] == "chained-icp-fallback"
    assert res["fallback_reason"] is not None


def test_joint_deterministic():
    ref = _cloud(0)
    other = _moved(_cloud(5), 1.0, [0.4, -0.3, 0.05])
    centre = np.array([20.0, 10.0, 0.0])
    clouds = {"a": ref, "b": other}
    anchors = ref[::4]
    r1 = joint_align.align_joint(list(clouds), clouds, clouds, anchors, centre)
    r2 = joint_align.align_joint(list(clouds), clouds, clouds, anchors, centre)
    assert r1["method"] == r2["method"]
    c1, c2 = r1["convergence"], r2["convergence"]
    assert c1["success"] == c2["success"]
    if c1.get("cost") is not None and c2.get("cost") is not None:
        assert abs(float(c1["cost"]) - float(c2["cost"])) < 1e-6


def test_anchors_exclude_heldout():
    feats = [{"properties": {"layer": "x", "token": str(i)}} for i in range(10)]
    anchors, heldout, _meta = reference_split.split_reference(feats)
    anchor_ids = {reference_split.element_id(f) for f in anchors}
    heldout_ids = {reference_split.element_id(f) for f in heldout}
    assert anchor_ids.isdisjoint(heldout_ids)


def test_joint_anchor_residuals_xy_only():
    rng = np.random.default_rng(9)
    ref = _cloud(0)
    ref[:, 2] += np.linspace(0.0, 5.0, len(ref))  # large z should not inflate XY metric
    other = ref + rng.uniform(-0.02, 0.02, ref.shape)
    other = _moved(other, 0.5, [0.2, -0.1, 0.0])
    centre = np.array([20.0, 10.0, 0.0])
    clouds = {"a": ref, "b": other}
    anchors = ref[::4]
    res = joint_align.align_joint(list(clouds), clouds, clouds, anchors, centre)
    assert res["method"] == "joint-pose-graph"
    for r in res["anchor_residuals"]:
        assert r is not None
        assert r < 0.5, f"anchor residual inflated by z: {r}"


def _four_drive_clouds(rng_seed=11):
    rng = np.random.default_rng(rng_seed)
    ref = _cloud(0)
    shifts = {
        "b": (0.8, [0.35, -0.25, 0.0]),
        "c": (-0.6, [-0.30, 0.40, 0.0]),
        "d": (1.2, [0.20, 0.30, 0.0]),
    }
    clouds = {"a": ref.copy()}
    for k, (yaw, t) in shifts.items():
        obs = ref + rng.uniform(-0.02, 0.02, ref.shape)
        clouds[k] = _moved(obs, yaw, t)
    return ref, clouds, shifts


def test_joint_four_drives_recovers_known_shifts():
    ref, clouds, shifts = _four_drive_clouds()
    centre = np.array([20.0, 10.0, 0.0])
    anchors = ref[::4]
    res = joint_align.align_joint(sorted(clouds), clouds, clouds, anchors, centre)
    assert res["method"] == "joint-pose-graph"
    assert res["convergence"]["success"] is True
    # CR1: multi-drive recovery must be <=5cm
    errs = []
    for k, (_yaw, t) in shifts.items():
        err = np.linalg.norm(res["corrections"][k][:2, 3] + np.array(t[:2]))
        errs.append(err)
        assert err <= 0.05, f"{k} err {err:.3f}m"
    assert max(errs) <= 0.05


def test_joint_partial_overlap_recovers_or_falls_back():
    ref, clouds, shifts = _four_drive_clouds()
    mask_b = clouds["a"][:, 0] < 20.0
    mask_c = clouds["a"][:, 0] >= 20.0
    clouds["b"] = clouds["b"][mask_b]
    clouds["c"] = clouds["c"][mask_c]
    centre = np.array([20.0, 10.0, 0.0])
    anchors = ref[::4]
    res = joint_align.align_joint(sorted(clouds), clouds, clouds, anchors, centre)
    if res["method"] == "joint-pose-graph":
        for k, (_yaw, t) in shifts.items():
            err = np.linalg.norm(res["corrections"][k][:2, 3] + np.array(t[:2]))
            assert err <= 0.05, f"{k} err {err:.3f}m {res.get('convergence')}"
    else:
        assert res["method"] == "chained-icp-fallback"
        assert res.get("fallback_reason")


def test_joint_sparse_anchor_density_falls_back():
    ref, clouds, shifts = _four_drive_clouds()
    centre = np.array([20.0, 10.0, 0.0])
    for step in (8, 32, 100):
        anchors = ref[::step]
        res = joint_align.align_joint(sorted(clouds), clouds, clouds, anchors, centre)
        if res["method"] == "joint-pose-graph":
            for k, (_yaw, t) in shifts.items():
                err = np.linalg.norm(res["corrections"][k][:2, 3] + np.array(t[:2]))
                assert err <= 0.05, f"step {step} {k} err {err:.3f}m"
        else:
            assert res["method"] == "chained-icp-fallback"
            assert res.get("fallback_reason")


def test_merge_area_joint_diagnostics_persist_and_excludes_heldout(tmp_path, monkeypatch):
    import json
    import logging

    from shapely.geometry import box, mapping

    from twin.contracts import Params

    ref = _cloud(0)
    other = _moved(_cloud(5), 1.0, [0.4, -0.3, 0.05])
    clouds = {
        "a": np.column_stack([ref, np.ones(len(ref)), np.zeros(len(ref))]),
        "b": np.column_stack([other, np.ones(len(other)), np.zeros(len(other))]),
    }

    def fake_build_drive(scene, work, polygon, params, log):
        return clouds[scene["scene"]]

    monkeypatch.setattr(merge, "build_drive", fake_build_drive)
    monkeypatch.setattr(merge, "drive_ground", lambda *a, **k: None)
    monkeypatch.setattr(merge, "fit_heights", lambda *a, **k: ({}, {"summary": {}, "sweeps": []}))

    feats = [
        {
            "type": "Feature",
            "properties": {"layer": "l", "token": str(i)},
            "geometry": {"type": "Point", "coordinates": [20.0 + (i % 5) * 0.1, 10.0 + (i // 5) * 0.1]},
        }
        for i in range(40)
    ]
    captured = {}

    import twin.areatwin as areatwin_mod

    monkeypatch.setattr(areatwin_mod, "area_inputs", lambda drives, work, polygon: ([], feats))

    real_align = joint_align.align_joint

    def spy_align(drives, clouds_in, ground, anchors, centre):
        captured["anchors"] = anchors
        captured["n_drives"] = len(drives)
        return real_align(drives, clouds_in, ground, anchors, centre)

    monkeypatch.setattr(joint_align, "align_joint", spy_align)

    area = {
        "name": "a",
        "dataset_version": "v1.0-test",
        "polygon": mapping(box(0, 0, 40, 20)),
        "drives": [
            {"scene": "a", "date": "2018-01-01", "build_input": True, "scene_token": "ta"},
            {"scene": "b", "date": "2018-01-02", "build_input": True, "scene_token": "tb"},
        ],
    }
    params = Params(merge={"method": "joint-pose-graph"})
    qa = merge.merge_area(area, tmp_path, params, logging.getLogger("t"))

    # C3: diagnostics persisted in qa.json and run.json
    assert qa["method"] == "joint-pose-graph"
    assert qa["convergence"] is not None
    assert qa["anchor_residuals"] is not None
    assert qa["pair_residuals"] is not None
    qa_disk = json.loads((tmp_path / "qa.json").read_text())
    run_disk = json.loads((tmp_path / "run.json").read_text())
    assert qa_disk["convergence"]["success"] is True
    assert run_disk["metrics"]["align"]["method"] == "joint-pose-graph"
    assert run_disk["metrics"]["align"]["anchor_residuals"] == qa_disk["anchor_residuals"]

    # C3: heldout excluded from anchors passed to solver
    anchors, heldout, _meta = reference_split.split_reference(feats)
    anchor_ids = {reference_split.element_id(f) for f in anchors}
    heldout_ids = {reference_split.element_id(f) for f in heldout}
    passed_ids = {reference_split.element_id(f) for f in captured["anchors"]}
    assert passed_ids == anchor_ids
    assert passed_ids.isdisjoint(heldout_ids)
    assert len(heldout_ids) > 0


def test_joint_memory_scales_with_thinned_size():
    import tracemalloc

    def make_drive(seed):
        return _cloud(seed)

    centre = np.array([20.0, 10.0, 0.0])
    clouds = {}
    for i in range(15):
        clouds[f"d{i}"] = make_drive(i)
    anchors = _cloud(0)[::4]
    tracemalloc.start()
    joint_align.align_joint(sorted(clouds), clouds, clouds, anchors, centre)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # peak should stay well below raw-size scale (20x replication)
    assert peak < 500 * 1024 * 1024, f"peak memory {peak/1024/1024:.1f} MB"


def test_joint_offroad_points_do_not_pull():
    ref = _cloud(0)
    other = _moved(_cloud(5), 1.0, [0.4, -0.3, 0.05])
    offroad = np.tile(np.array([[100.0, 100.0, 0.0]]), (2000, 1))
    other2 = np.vstack([other, offroad])
    centre = np.array([20.0, 10.0, 0.0])
    anchors = ref[::4]
    clouds1 = {"a": ref.copy(), "b": other.copy()}
    clouds2 = {"a": ref.copy(), "b": other2.copy()}
    r1 = joint_align.align_joint(sorted(clouds1), clouds1, clouds1, anchors, centre)
    r2 = joint_align.align_joint(sorted(clouds2), clouds2, clouds2, anchors, centre)
    t1 = r1["corrections"]["b" if r1["reference"] == "a" else "a"]
    t2 = r2["corrections"]["b" if r2["reference"] == "a" else "a"]
    assert np.allclose(t1, t2, rtol=1e-2, atol=1e-2)
