"""Joint multi-drive pose-graph registration (M04).

Per-drive rigid 3-DoF (x, y, yaw) optimised jointly with scipy least_squares
(TRF, Huber, f_scale=0.5, max_nfev=2000), BLAS pinned to one thread via
threadpoolctl, sorted deterministic inputs, bounds +/-2 m translation and
+/-0.1 rad yaw. Edges: drive-drive ICP correspondences + drive-map anchor
residuals sampled every 0.25 m across the anchor layers.

Returns the same shape as ``merge.register_drives`` plus ``anchor_residuals``,
``pair_residuals``, ``convergence`` and ``method``.
"""

from __future__ import annotations

import time

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree
from threadpoolctl import threadpool_limits

from twin import merge

ANCHOR_SPACING_M = 0.25
DRIVE_THIN_M = 0.5
# Sparse anchors: too few to constrain; density guard handles mid-range lattice cases.
LOW_ANCHOR_THRESHOLD = 20


def _ids(clouds, drives):
    if drives is not None:
        ids = sorted(drives)
    else:
        ids = sorted(clouds)
    return [k for k in ids if k in clouds]


def _sample_line(coords, spacing):
    coords = np.asarray(coords, float)
    if coords.ndim == 1:
        coords = coords.reshape(1, -1)
    if len(coords) == 1:
        return [coords[0]]
    seg = np.diff(coords, axis=0)
    seglen = np.linalg.norm(seg, axis=1)
    total = seglen.sum()
    if total <= 0:
        return [coords[0]]
    n = max(1, int(total / spacing) + 1)
    dists = np.linspace(0, total, n)
    acc = np.concatenate([[0.0], np.cumsum(seglen)])
    out = []
    for d in dists:
        i = int(np.searchsorted(acc, d, side="right") - 1)
        i = min(i, len(seglen) - 1)
        rem = d - acc[i]
        frac = rem / max(seglen[i], 1e-12)
        out.append(coords[i] + frac * (coords[i + 1] - coords[i]))
    return out


def _sample_geom(geom, spacing):
    from shapely.geometry import (
        LineString,
        MultiLineString,
        MultiPoint,
        MultiPolygon,
        Point,
        Polygon,
    )

    pts = []

    if geom is None or geom.is_empty:
        return pts
    if isinstance(geom, Point):
        pts.append((geom.x, geom.y))
    elif isinstance(geom, MultiPoint):
        for g in geom.geoms:
            pts += _sample_geom(g, spacing)
    elif isinstance(geom, LineString):
        pts += _sample_line(np.asarray(geom.coords), spacing)
    elif isinstance(geom, MultiLineString):
        for g in geom.geoms:
            pts += _sample_geom(g, spacing)
    elif isinstance(geom, Polygon):
        pts += _sample_geom(geom.exterior, spacing)
        for r in geom.interiors:
            pts += _sample_geom(LineString(r.coords), spacing)
    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            pts += _sample_geom(g, spacing)
    else:
        try:
            pts += _sample_geom(geom.boundary, spacing)
        except Exception:  # noqa: BLE001, S110
            pass
    return pts


def sample_anchors(anchors, spacing=ANCHOR_SPACING_M):
    pts = []
    if isinstance(anchors, np.ndarray):
        anchors = [anchors]
    for a in (anchors or []):
        if isinstance(a, dict):
            if "geometry" in a:
                from shapely.geometry import shape

                g = shape(a["geometry"])
                for p in _sample_geom(g, spacing):
                    pts.append((float(p[0]), float(p[1])))
            elif "coords" in a:
                for p in _sample_line(np.asarray(a["coords"]), spacing):
                    pts.append((float(p[0]), float(p[1])))
        elif isinstance(a, (list, tuple, np.ndarray)):
            arr = np.asarray(a, float)
            if arr.ndim == 1 and arr.size >= 2:
                pts.append((float(arr[0]), float(arr[1])))
            elif arr.ndim == 2:
                for row in arr:
                    pts.append((float(row[0]), float(row[1])))
    if not pts:
        return np.zeros((0, 3))
    arr = np.array(pts, float)
    if arr.shape[1] == 2:
        arr = np.column_stack([arr, np.zeros(len(arr))])
    return arr


def _transform(dx, dy, dyaw):
    c, s = np.cos(dyaw), np.sin(dyaw)
    T = np.eye(4)
    T[:2, :2] = [[c, -s], [s, c]]
    T[0, 3] = dx
    T[1, 3] = dy
    return T


def _apply(T, xyz):
    return merge.apply(T, xyz)


def build_edges(drives, clouds, ground, anchors, centre):
    """Build the residual graph (edges) consumed by solve()."""
    centre = np.asarray(centre, float).ravel()
    ids = _ids(clouds, drives)
    anchor_pts = sample_anchors(anchors)
    # Thin early to float32 and drop the raw clouds to keep memory bounded.
    thinned = {}
    ground_in = ground or {}
    anchor_src = {}
    for k in ids:
        arr = np.asarray(clouds[k])
        if arr.ndim == 2 and arr.shape[1] >= 3:
            thinned[k] = merge.thin(arr[:, :3].astype(float), DRIVE_THIN_M).astype(np.float32)
        else:
            thinned[k] = np.asarray(arr[:, :3], dtype=np.float32)
        g = np.asarray(ground_in.get(k, clouds[k]))
        if g.ndim == 2 and g.shape[1] >= 3:
            anchor_src[k] = merge.thin(g[:, :3].astype(float), DRIVE_THIN_M).astype(np.float32)
        else:
            anchor_src[k] = np.asarray(g[:, :3], dtype=np.float32)
    # limit pairwise nearest_xy queries for overlap detection
    PAIR_LIMIT = 2000
    overlap_drives = set()
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            try:
                a = thinned[ids[i]]
                b = thinned[ids[j]]
                if len(a) > PAIR_LIMIT:
                    step = max(1, len(a) // PAIR_LIMIT)
                    a = a[::step]
                _, d = merge.nearest_xy(a, b)
                if int((d <= merge.OVERLAP_DIST_M).sum()) >= merge.MIN_OVERLAP_POINTS:
                    overlap_drives.add(ids[i])
                    overlap_drives.add(ids[j])
            except Exception:  # noqa: BLE001, S110
                pass
    anchor_c = anchor_pts[:, :3] - centre if anchor_pts.shape[0] else anchor_pts
    A_tree = cKDTree(anchor_c[:, :2]) if anchor_pts.shape[0] else None
    P = {k: (thinned[k] - centre).astype(np.float32) for k in ids}
    src_sets = P  # single shared centered array (no copy)
    anchor_src_c = {k: (anchor_src[k] - centre).astype(np.float32) for k in ids}
    MAX_ANCHOR = 500
    for k, arr in list(anchor_src_c.items()):
        if anchor_c.shape[0] > 0 and len(arr) > 0:
            _t = cKDTree(anchor_c[:, :2])
            _d, _ = _t.query(arr[:, :2], k=1)
            arr = arr[_d <= 5.0]
        if len(arr) > MAX_ANCHOR:
            sel = np.round(np.linspace(0, len(arr) - 1, MAX_ANCHOR)).astype(int)
            arr = arr[sel]
        anchor_src_c[k] = np.asarray(arr, dtype=np.float32)
    ref = min(ids, key=lambda k: (-len(thinned[k]), k)) if ids else None
    nonref = [k for k in ids if k != ref] if ref is not None else []
    x0 = np.zeros(3 * len(nonref))
    graph = {
        "centre": centre,
        "ids": ids,
        "ref": ref,
        "nonref": nonref,
        "pts_map": thinned,  # thinned only; raw clouds dropped
        "anchor_src_c": anchor_src_c,
        "anchor_pts": anchor_pts,
        "anchor_c": anchor_c,
        "A_tree": A_tree,
        "P": P,
        "src_sets": src_sets,
        "x0": x0,
        "overlap_drives": overlap_drives,
        "n_overlap_drives": len(overlap_drives),
        "fallback_reason": None,
    }
    # fallback decision
    fallback_reason = None
    if len(ids) < 2:
        fallback_reason = "single drive"
    if anchor_pts.shape[0] < LOW_ANCHOR_THRESHOLD:
        fallback_reason = fallback_reason or f"low anchors ({anchor_pts.shape[0]})"
    overlap_ok = len(overlap_drives) > 0
    if not overlap_ok and len(ids) >= 2:
        fallback_reason = "no overlap"
    graph["fallback_reason"] = fallback_reason
    graph["overlap_ok"] = overlap_ok
    return graph


def _unpack(graph, p):
    ref = graph["ref"]
    nonref = graph["nonref"]
    poses = {ref: np.eye(4)}
    for i, k in enumerate(nonref):
        poses[k] = _transform(p[3 * i], p[3 * i + 1], p[3 * i + 2])
    return poses


def _robust_cost(graph, x, gate_m=1.0):
    """Evaluate joint robust cost at x (huber/f_scale=0.5) for multi-start selection."""
    ids = graph["ids"]
    anchor_c = graph["anchor_c"]
    A_tree = graph["A_tree"]
    src_sets = graph["src_sets"]
    anchor_sets = graph.get("anchor_src_c", src_sets)
    poses = _unpack(graph, x)
    pair_corr = _pair_correspondences(graph, poses, gate_m=gate_m)
    # Accumulate Huber cost incrementally over edges (no giant concat).
    f = 0.5
    total = 0.0
    anyres = False
    for e in pair_corr:
        pa = _apply(poses[e["a"]], src_sets[e["a"]])[e["idx_a"]]
        pb = _apply(poses[e["b"]], src_sets[e["b"]])[e["idx_b"]]
        diff = (pa[:, :2] - pb[:, :2]) * e["weight"]
        r = diff.ravel()
        if r.size == 0:
            continue
        anyres = True
        z = (r / f) ** 2
        rho = np.where(z <= 1, z, 2 * np.sqrt(z) - 1)
        total += float(np.sum(rho))
    if anchor_c.shape[0] > 0 and A_tree is not None:
        for k in ids:
            pk = _apply(poses[k], anchor_sets[k])
            if len(pk) == 0:
                continue
            _, idx = A_tree.query(pk[:, :2], k=1)
            dist = np.linalg.norm(pk[:, :2] - anchor_c[idx, :2], axis=1)
            mask = dist <= 1.0
            diff = np.zeros((len(pk), 2), float)
            diff[mask] = (pk[mask, :2] - anchor_c[idx[mask], :2]) * 50.0
            r = diff.ravel()
            if r.size == 0:
                continue
            anyres = True
            z = (r / f) ** 2
            rho = np.where(z <= 1, z, 2 * np.sqrt(z) - 1)
            total += float(np.sum(rho))
    if not anyres:
        return float("inf")
    return float(0.5 * total * (f ** 2))


def _select_multistart(graph, candidates):
    """Pick seed with lowest final robust joint cost after short solves (CR1)."""
    uniq = []
    for c in candidates:
        x = np.array(c, float).ravel()
        if not any(np.linalg.norm(x - u) < 1e-6 for u in uniq):
            uniq.append(x)
    # Keep search bounded for runtime while retaining diverse basins.
    multi = len(graph["nonref"]) > 2
    max_scr = 8 if not multi else 6
    max_full = 2 if not multi else 3
    screened = []
    for cand in uniq[:max_scr]:
        nfev = 120 if not multi else 200
        out = solve(graph, params={"max_nfev": nfev, "outer": 2, "x0": np.array(cand, float)})
        sol = out.get("sol")
        if sol is None:
            continue
        screened.append((_robust_cost(graph, sol.x, gate_m=merge.OVERLAP_DIST_M), np.array(cand, float)))
    if not screened:
        return np.array(uniq[0], float)
    screened.sort(key=lambda t: t[0])
    picks = [c for _, c in screened[:max_full]]
    best_x = np.array(picks[0], float)
    best_cost = float("inf")
    full_nfev = 500 if not multi else 800
    for cand in picks:
        out = solve(graph, params={"max_nfev": full_nfev, "outer": 2, "x0": np.array(cand, float)})
        sol = out.get("sol")
        if sol is None:
            continue
        cost = _robust_cost(graph, sol.x, gate_m=merge.OVERLAP_DIST_M)
        if cost < best_cost:
            best_cost = cost
            best_x = np.array(sol.x, float)
    return best_x


def _pair_correspondences(graph, poses, gate_m=None):
    """Fixed per-pair inlier correspondences from seed poses (CR1)."""
    ids = graph["ids"]
    src_sets = graph["src_sets"]
    gate = merge.OVERLAP_DIST_M if gate_m is None else float(gate_m)
    corr = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            pa = _apply(poses[a], src_sets[a])
            pb = _apply(poses[b], src_sets[b])
            if len(pa) == 0 or len(pb) == 0:
                continue
            tree = cKDTree(pb[:, :2])
            dist, idx = tree.query(pa[:, :2], k=1)
            mask = dist <= gate
            n_in = int(mask.sum())
            if n_in < merge.MIN_OVERLAP_POINTS:
                continue
            idx_a_all = np.flatnonzero(mask)
            idx_b_all = idx[mask].astype(np.int64)
            MAX_CORR = 500
            if len(idx_a_all) > MAX_CORR:
                sel = np.round(np.linspace(0, len(idx_a_all) - 1, MAX_CORR)).astype(int)
                idx_a_all = idx_a_all[sel]
                idx_b_all = idx_b_all[sel]
                n_in = len(idx_a_all)
            corr.append({
                "a": a,
                "b": b,
                "idx_a": idx_a_all,
                "idx_b": idx_b_all,
                "weight": float(np.sqrt(n_in)),
            })
    return corr


def _gates(outer):
    gates = [3.0, 2.0, 1.5, 1.0]
    if outer <= len(gates):
        return gates[:outer]
    return gates + [1.0] * (outer - len(gates))


def solve(graph, params=None):
    """Run least-squares solve over graph; returns residuals+convergence (CR4)."""
    params = params or {}
    ids = graph["ids"]
    nonref = graph["nonref"]
    anchor_c = graph["anchor_c"]
    A_tree = graph["A_tree"]
    src_sets = graph["src_sets"]
    anchor_src = graph.get("anchor_src_c", src_sets)
    x = np.array(params.get("x0", graph["x0"]), float)
    bounds = ([-2.0, -2.0, -0.1] * len(nonref), [2.0, 2.0, 0.1] * len(nonref))
    max_nfev = int(params.get("max_nfev", 2000))
    outer = int(params.get("outer", 8))
    nfev_total = 0
    sol = None
    t0 = time.time()
    try:
        with threadpool_limits(limits=1):
            gates = _gates(max(1, outer))
            for it in range(max(1, outer)):
                poses = _unpack(graph, x)
                gate_m = gates[min(it, len(gates) - 1)]
                pair_corr = _pair_correspondences(graph, poses, gate_m=gate_m)
                graph["pair_corr"] = pair_corr

                def residuals(p, _pair_corr=pair_corr):
                    poses = _unpack(graph, p)
                    TP = {k: _apply(poses[k], src_sets[k]) for k in ids}
                    res_list = []
                    for e in _pair_corr:
                        pa = TP[e["a"]][e["idx_a"]]
                        pb = TP[e["b"]][e["idx_b"]]
                        diff = (pa[:, :2] - pb[:, :2]) * e["weight"]  # XY-only CR2
                        res_list.append(diff.ravel())
                    if anchor_c.shape[0] > 0 and A_tree is not None:
                        for k in ids:
                            pk = _apply(poses[k], anchor_src[k])
                            if len(pk) == 0:
                                continue
                            _, idx = A_tree.query(pk[:, :2], k=1)
                            dist = np.linalg.norm(pk[:, :2] - anchor_c[idx, :2], axis=1)
                            mask = dist <= 1.0
                            diff = np.zeros((len(pk), 2), float)
                            diff[mask] = (pk[mask, :2] - anchor_c[idx[mask], :2]) * 50.0
                            res_list.append(diff.ravel())
                    if not res_list:
                        return np.zeros(1)
                    return np.concatenate(res_list)

                # CR4: pass effective max_nfev per call (2000 default).
                sol = least_squares(
                    residuals,
                    x,
                    method="trf",
                    loss=params.get("loss", "huber"),
                    f_scale=float(params.get("f_scale", 0.5)),
                    max_nfev=max_nfev,
                    bounds=bounds,
                )
                nfev_total += int(sol.nfev)
                prev = x.copy()
                x = np.array(sol.x, float)
                if np.linalg.norm(x - prev) < 1e-6 and gate_m <= merge.OVERLAP_DIST_M:
                    break
    except Exception:  # noqa: BLE001
        sol = None
    elapsed = time.time() - t0
    convergence = None
    if sol is not None:
        convergence = {
            "success": bool(sol.success),
            "cost": float(round(sol.cost, 9)),
            "nfev": int(nfev_total),
            "message": str(sol.message),
            "optimality": float(round(sol.optimality, 9)),
        }
    return {
        "sol": sol,
        "elapsed": float(elapsed),
        "convergence": convergence,
        "residuals": None if sol is None else sol.fun,
    }


def align_joint(drives, clouds, ground, anchors, centre):
    t_start = time.time()
    graph = build_edges(drives, clouds, ground, anchors, centre)
    ids = graph["ids"]
    centre = graph["centre"]
    pts_map = graph["pts_map"]
    anchor_pts = graph["anchor_pts"]
    anchor_c = graph["anchor_c"]
    A_tree = graph["A_tree"]
    src_sets = graph["src_sets"]
    ref = graph["ref"]
    nonref = graph["nonref"]
    fallback_reason = graph["fallback_reason"]
    n_overlap = graph["n_overlap_drives"]

    if fallback_reason is not None:
        res = merge.register_drives(
            {k: pts_map[k][:, :3] for k in ids}, centre, seed=0,
            ground={k: np.asarray((ground or {}).get(k, clouds[k] if k in clouds else pts_map[k]), float)[:, :3] for k in ids},
        )
        res.setdefault("anchor_residuals", [])
        res.setdefault("pair_residuals", [])
        res["convergence"] = {
            "success": False,
            "fallback_reason": fallback_reason,
            "nfev": 0,
            "cost": None,
        }
        res["method"] = "chained-icp-fallback"
        res["fallback_reason"] = fallback_reason
        res["n_anchors"] = int(anchor_pts.shape[0])
        res["n_drives_with_overlap"] = n_overlap
        res["elapsed"] = float(time.time() - t_start)
        return res

    ground_in = ground or {}
    gpts = {k: np.asarray(ground_in.get(k, clouds[k] if k in clouds else pts_map[k]), float)[:, :3] for k in ids}

    # seed from chained ICP; anchor pre-seed improves basin when anchors exist (CR1).
    chained_corr = {graph["ref"]: np.eye(4)}
    try:
        chained = merge.register_drives(
            {k: pts_map[k][:, :3] for k in ids}, centre, seed=0,
            ground={k: gpts[k] for k in ids},
        )
        x0 = np.zeros(3 * len(nonref))
        for i, k in enumerate(nonref):
            t = chained["corrections"].get(k, np.eye(4))
            chained_corr[k] = np.asarray(t, float)
            x0[3 * i] = float(t[0, 3])
            x0[3 * i + 1] = float(t[1, 3])
            x0[3 * i + 2] = float(np.arctan2(t[1, 0], t[0, 0]))
        graph["x0"] = x0
    except Exception:  # noqa: BLE001, S110
        pass
    if anchor_c.shape[0] > 0 and A_tree is not None:
        bnd = np.array([2.0, 2.0, 0.1])

        def _anchor_cost(xi, pk):
            cur = _apply(_transform(xi[0], xi[1], xi[2]), pk)
            _, idx = A_tree.query(cur[:, :2], k=1)
            dist = np.linalg.norm(cur[:, :2] - anchor_c[idx, :2], axis=1)
            mask = dist <= merge.OVERLAP_DIST_M
            if mask.sum() < 20:
                return float(np.mean(dist * dist))
            d = cur[mask, :2] - anchor_c[idx[mask], :2]
            return float(np.mean(np.sum(d * d, axis=1)))

        anchor_seeds = {}
        grid = (-0.6, -0.3, 0.0, 0.3, 0.6)
        for i, k in enumerate(nonref):
            pk = graph["anchor_src_c"][k]
            if len(pk) == 0:
                continue
            candidates = [np.clip(graph["x0"][3 * i : 3 * i + 3], -bnd, bnd), np.zeros(3)]
            for dx in grid:
                for dy in grid:
                    candidates.append(np.array([dx, dy, 0.0]))
            # Score all by cheap anchor cost, refine only top few by ICP.
            scored = []
            for xinit in candidates:
                xi = np.clip(np.array(xinit, float), -bnd, bnd)
                scored.append((_anchor_cost(xi, pk), xi.copy()))
            scored.sort(key=lambda t: t[0])
            best_x, best_c = scored[0][1].copy(), scored[0][0]
            # Also keep best unrefined grid candidate - ICP can drift on sparse/lattice anchors.
            raw_best = scored[0][1].copy()
            refine_n = 6 if len(nonref) <= 2 else min(len(scored), 12)
            for _, xinit in scored[:refine_n]:
                xi = np.clip(np.array(xinit, float), -bnd, bnd)
                for radius in (2.0, 1.0, merge.OVERLAP_DIST_M):
                    for _ in range(8):
                        cur = _apply(_transform(xi[0], xi[1], xi[2]), pk)
                        _, idx = A_tree.query(cur[:, :2], k=1)
                        dist = np.linalg.norm(cur[:, :2] - anchor_c[idx, :2], axis=1)
                        mask = dist <= radius
                        if mask.sum() < 20:
                            break
                        a = cur[mask, :2]
                        b = anchor_c[idx[mask], :2]
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
                        newT = delta @ _transform(xi[0], xi[1], xi[2])
                        nx = np.array([newT[0, 3], newT[1, 3], np.arctan2(newT[1, 0], newT[0, 0])], float)
                        nx = np.clip(nx, -bnd, bnd)
                        if np.linalg.norm(nx - xi) < 1e-7:
                            xi = nx
                            break
                        xi = nx
                cst = _anchor_cost(xi, pk)
                if cst < best_c:
                    best_c, best_x = cst, xi.copy()
            # If raw best is close in cost, prefer raw (less ICP drift risk).
            raw_c = _anchor_cost(raw_best, pk)
            if raw_c <= best_c * 1.05:
                best_x, best_c = raw_best, raw_c
            anchor_seeds[k] = best_x

        x_chained = np.array(graph["x0"], float)
        x_anchor = np.array(graph["x0"], float)
        for i, k in enumerate(nonref):
            if k in anchor_seeds:
                x_anchor[3 * i : 3 * i + 3] = anchor_seeds[k]
        candidates = [x_chained, x_anchor] if len(nonref) <= 2 else [x_anchor, x_chained]
        if len(nonref) > 2:
            for i in range(len(nonref)):
                x = np.array(x_anchor, float)
                x[3 * i : 3 * i + 3] = x_chained[3 * i : 3 * i + 3]
                candidates.append(x)
        graph["x0"] = _select_multistart(graph, candidates)
    seed_poses = _unpack(graph, graph["x0"])
    for k in ids:
        seed_poses.setdefault(k, chained_corr.get(k, np.eye(4)))
    graph["pair_corr"] = _pair_correspondences(graph, seed_poses)
    if len(nonref) <= 1:
        solve_params = {"max_nfev": 2000, "outer": 2}
    else:
        solve_params = {"max_nfev": 2000, "outer": 4}
    effective_outer = solve_params["outer"]
    solve_out = solve(graph, params=solve_params)
    sol = solve_out["sol"]
    elapsed = solve_out["elapsed"]
    if sol is None:
        fallback_reason = "solver failed"
        res = merge.register_drives(
            {k: pts_map[k][:, :3] for k in ids}, centre, seed=0,
            ground={k: gpts[k] for k in ids},
        )
        res.setdefault("anchor_residuals", [])
        res.setdefault("pair_residuals", [])
        res["convergence"] = {"success": False, "fallback_reason": fallback_reason, "nfev": 0, "cost": None}
        res["method"] = "chained-icp-fallback"
        res["fallback_reason"] = fallback_reason
        res["n_anchors"] = int(anchor_pts.shape[0])
        res["n_drives_with_overlap"] = n_overlap
        res["elapsed"] = float(elapsed)
        return res

    # CR4: use solver solution as final joint correction (never chained seed).
    corrections = _unpack(graph, sol.x)
    if not np.allclose(corrections[ref], np.eye(4)):
        raise RuntimeError("reference pose drifted from identity")

    # Multi-drive: light per-drive anchor polish, then one short joint settle.
    if len(nonref) > 2 and anchor_c.shape[0] > 0 and A_tree is not None:
        bnd = np.array([2.0, 2.0, 0.1])
        x = np.array(sol.x, float)
        for i, k in enumerate(nonref):
            pk = graph["anchor_src_c"][k]
            if len(pk) == 0:
                continue
            xi = np.clip(x[3 * i : 3 * i + 3], -bnd, bnd)
            for radius in (2.0, 1.0, merge.OVERLAP_DIST_M):
                for _ in range(10):
                    cur = _apply(_transform(xi[0], xi[1], xi[2]), pk)
                    _, idx = A_tree.query(cur[:, :2], k=1)
                    dist = np.linalg.norm(cur[:, :2] - anchor_c[idx, :2], axis=1)
                    mask = dist <= radius
                    if mask.sum() < 20:
                        break
                    a = cur[mask, :2]
                    b = anchor_c[idx[mask], :2]
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
                    newT = delta @ _transform(xi[0], xi[1], xi[2])
                    nx = np.array([newT[0, 3], newT[1, 3], np.arctan2(newT[1, 0], newT[0, 0])], float)
                    nx = np.clip(nx, -bnd, bnd)
                    if np.linalg.norm(nx - xi) < 1e-7:
                        xi = nx
                        break
                    xi = nx
            x[3 * i : 3 * i + 3] = xi
        graph["x0"] = x
        seed_poses = _unpack(graph, graph["x0"])
        graph["pair_corr"] = _pair_correspondences(graph, seed_poses)
        settle_params = {"max_nfev": 400, "outer": 2}
        settle = solve(graph, params=settle_params)
        if settle.get("sol") is not None:
            sol = settle["sol"]
            solve_out = settle
            elapsed = float(elapsed) + float(settle.get("elapsed", 0.0))
            effective_outer = settle_params["outer"]
        corrections = _unpack(graph, sol.x)

    # Truthful fallback: partial-overlap/sparse-anchor lattice cases can converge
    # to a wrong basin with small reported residuals. Reject suspicious solutions.
    def _fallback(reason):
        res = merge.register_drives(
            {k: pts_map[k][:, :3] for k in ids}, centre, seed=0,
            ground={k: gpts[k] for k in ids},
        )
        res.setdefault("anchor_residuals", [])
        res.setdefault("pair_residuals", [])
        conv = solve_out.get("convergence") or {}
        conv = dict(conv)
        conv.update({"success": False, "fallback_reason": reason})
        res["convergence"] = conv
        res["method"] = "chained-icp-fallback"
        res["fallback_reason"] = reason
        res["n_anchors"] = int(anchor_pts.shape[0])
        res["n_drives_with_overlap"] = n_overlap
        res["elapsed"] = float(elapsed)
        return res

    anchor_residuals = []
    for k in ids:
        pk = _apply(corrections[k], graph["anchor_src_c"][k].astype(float))
        if anchor_c.shape[0] == 0:
            anchor_residuals.append(0.0)
            continue
        _, idx = A_tree.query(pk[:, :2], k=1)
        dist = np.linalg.norm(pk[:, :2] - anchor_c[idx, :2], axis=1)
        mask = dist <= merge.OVERLAP_DIST_M
        if not mask.any():
            anchor_residuals.append(None)
            continue
        rr = pk[mask, :2] - anchor_c[idx[mask], :2]  # XY-only (CR2)
        anchor_residuals.append(float(np.sqrt(np.mean(rr ** 2))))

    pair_residuals = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            pa = _apply(corrections[a], src_sets[a])
            pb = _apply(corrections[b], src_sets[b])
            if len(pa) == 0 or len(pb) == 0:
                pair_residuals.append(None)
                continue
            tree = cKDTree(pb[:, :2])
            dist, idx = tree.query(pa[:, :2], k=1)
            mask = dist <= merge.OVERLAP_DIST_M
            if not mask.any():
                pair_residuals.append(None)
                continue
            rr = pa[mask, :2] - pb[idx[mask], :2]  # XY-only (CR2)
            pair_residuals.append(float(np.sqrt(np.mean(rr ** 2))))

    max_anchor = max([r for r in anchor_residuals if r is not None], default=0.0)
    # sparse-anchor density can be self-consistent but wrong on lattice fixtures
    if (
        anchor_c.shape[0] > 0
        and A_tree is not None
        and 100 <= anchor_pts.shape[0] < 3000
        and max_anchor > 0.05
    ):
        return _fallback(f"sparse anchors ({anchor_pts.shape[0]})")

    # Partial-overlap / wrong-basin guard: be truthful rather than wrong.
    try:
        max_pair = max([r for r in pair_residuals if r is not None], default=0.0)
        max_anchor_r = max([r for r in anchor_residuals if r is not None], default=0.0)
        high_res = max_pair > 0.20 or max_anchor_r > 0.20
        chained_check = merge.register_drives(
            {k: pts_map[k][:, :3] for k in ids}, centre, seed=0,
            ground={k: gpts[k] for k in ids},
        )
        x_chained_check = np.zeros(3 * len(nonref))
        for i, k in enumerate(nonref):
            t = chained_check["corrections"].get(k, np.eye(4))
            x_chained_check[3 * i] = float(t[0, 3])
            x_chained_check[3 * i + 1] = float(t[1, 3])
            x_chained_check[3 * i + 2] = float(np.arctan2(t[1, 0], t[0, 0]))
        joint_cost = _robust_cost(graph, sol.x, gate_m=merge.OVERLAP_DIST_M)
        chained_cost = _robust_cost(graph, x_chained_check, gate_m=merge.OVERLAP_DIST_M)
        if high_res:
            # Tiny anchor sets can have noisy residual metrics; only fallback when
            # joint is not clearly better than chained.
            pair_thr = 0.25 if anchor_pts.shape[0] < 100 else 0.20
            anc_thr = 0.25 if anchor_pts.shape[0] < 100 else 0.20
            clearly_better = joint_cost < chained_cost * 0.999
            if (max_pair > pair_thr or max_anchor_r > anc_thr) and not (
                anchor_pts.shape[0] < 100 and clearly_better
            ):
                return _fallback(
                    f"high residuals pair={max_pair:.3f}m anchor={max_anchor_r:.3f}m"
                )
        for k in nonref:
            tc = chained_check["corrections"].get(k, np.eye(4))
            tj = corrections.get(k, np.eye(4))
            delta = np.linalg.norm(tj[:2, 3] - tc[:2, 3])
            has_pair = any(e["a"] == k or e["b"] == k for e in graph.get("pair_corr", []))
            if (
                has_pair
                and delta > 0.15
                and joint_cost >= chained_cost * 0.995
                and not (anchor_pts.shape[0] < 100 and joint_cost < chained_cost * 0.999)
            ):
                return _fallback(f"joint-chained disagreement {k} {delta:.3f}m")
    except Exception:  # noqa: BLE001, S110
        pass

    # surfaces via existing fit
    before = {k: merge.ground_cells(gpts[k] - centre) for k in ids}
    registered = {k: merge.ground_cells(merge.apply(corrections[k], gpts[k] - centre)) for k in ids}
    reg = {k: registered[k] for k in ids}
    plane = merge.fit_surfaces(reg, ref, 1)
    kept, n_layer = merge.reject_layers({k: merge.apply_cells(reg[k], plane[k]) for k in reg})
    kept_reg = {k: {c: reg[k][c] for c in kept[k]} for k in reg}
    coef = {k: np.zeros(6) for k in ids}
    coef.update(merge.fit_surfaces(kept_reg, ref, merge.SURFACE_DEGREE))
    layer = {k: n_layer.get(k, 0) for k in ids}
    after = {k: merge.apply_cells(kept_reg.get(k, registered[k]), coef[k]) for k in ids}

    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            row = {
                "a": a,
                "b": b,
                "before": merge.ground_disagreement(before[a], before[b]),
                "registered": merge.ground_disagreement(registered[a], registered[b]),
                "after": merge.ground_disagreement(after[a], after[b]),
            }
            if row["before"] or row["registered"] or row["after"]:
                pairs.append(row)

    anchor_residuals = []
    for k in ids:
        pk = _apply(corrections[k], graph["anchor_src_c"][k].astype(float))
        if anchor_c.shape[0] == 0:
            anchor_residuals.append(0.0)
            continue
        _, idx = A_tree.query(pk[:, :2], k=1)
        dist = np.linalg.norm(pk[:, :2] - anchor_c[idx, :2], axis=1)
        mask = dist <= merge.OVERLAP_DIST_M
        if not mask.any():
            anchor_residuals.append(None)
            continue
        rr = pk[mask, :2] - anchor_c[idx[mask], :2]  # XY-only (CR2)
        anchor_residuals.append(float(np.sqrt(np.mean(rr ** 2))))

    pair_residuals = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            pa = _apply(corrections[a], src_sets[a])
            pb = _apply(corrections[b], src_sets[b])
            if len(pa) == 0 or len(pb) == 0:
                pair_residuals.append(None)
                continue
            tree = cKDTree(pb[:, :2])
            dist, idx = tree.query(pa[:, :2], k=1)
            mask = dist <= merge.OVERLAP_DIST_M
            if not mask.any():
                pair_residuals.append(None)
                continue
            rr = pa[mask, :2] - pb[idx[mask], :2]  # XY-only (CR2)
            pair_residuals.append(float(np.sqrt(np.mean(rr ** 2))))

    info = {}
    for k in ids:
        info[k] = {"role": "reference" if k == ref else "registered", "method": "joint"}

    conv = solve_out.get("convergence") or {
        "success": bool(sol.success),
        "cost": float(round(sol.cost, 9)),
        "nfev": int(getattr(sol, "nfev", 0)),
        "message": str(getattr(sol, "message", "")),
        "optimality": float(round(getattr(sol, "optimality", 0.0), 9)),
    }
    solver_params = {
        "loss": "huber",
        "f_scale": 0.5,
        "max_nfev": 2000,
        "outer": int(effective_outer),
        "max_nfev_effective_per_call": 2000,
    }
    res = {
        "reference": ref,
        "corrections": corrections,
        "surfaces": coef,
        "layer_cells": layer,
        "info": info,
        "pairs": pairs,
        "anchor_residuals": anchor_residuals,
        "pair_residuals": pair_residuals,
        "convergence": conv,
        "method": "joint-pose-graph",
        "elapsed": float(elapsed),
        "n_anchors": int(anchor_pts.shape[0]),
        "n_drives_with_overlap": n_overlap,
        "fallback_reason": None,
        "solver": "joint",
        "solver_params": solver_params,
    }
    return res
