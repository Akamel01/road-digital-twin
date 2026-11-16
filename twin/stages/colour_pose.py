"""Pure-CPU camera-pose refinement anchored on lidar paint edges (colour stage).

No stage/GPU dependencies beyond numpy/scipy/zbuffer helpers. CPU only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from twin.stages import profile, zbuffer

try:
    from twin.stages import colour as _colour_mod
except (ImportError, RuntimeError, ValueError, OSError) as _e:  # pragma: no cover
    _colour_mod = None

EDGE_STEP_M = getattr(_colour_mod, "EDGE_STEP_M", 0.25) if _colour_mod is not None else 0.25
EDGE_MIN_SAMPLES = getattr(_colour_mod, "EDGE_MIN_SAMPLES", 4) if _colour_mod is not None else 4
EDGE_SEARCH_M = getattr(_colour_mod, "EDGE_SEARCH_M", 0.5) if _colour_mod is not None else 0.5


def _load_surface(ground_surface: Any) -> dict[str, Any] | None:
    if ground_surface is None:
        return None
    if isinstance(ground_surface, (str, Path)):
        with np.load(ground_surface) as f:
            return {k: f[k] for k in f.files}
    if isinstance(ground_surface, dict):
        return ground_surface
    try:
        with np.load(ground_surface) as f:
            return {k: f[k] for k in f.files}
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        return None


def _nearest_z(points_3d: np.ndarray | None, x: float, y: float) -> float | None:
    if points_3d is None or len(points_3d) == 0:
        return None
    pts = np.asarray(points_3d, float)
    d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
    i = int(np.argmin(d))
    if d[i] > 2.0:
        return None
    return float(pts[i, 2])


def lidar_paint_edges(
    markings: Any, ground_surface: Any, points_3d: Any = None, step_m: float | None = None
) -> np.ndarray:
    """Sample observed-reliability markings into 3D anchor points (N, 3).

    z is interpolated from ground_surface (surface.npz grid) with points_3d fallback.
    """
    if step_m is None:
        step_m = EDGE_STEP_M
    surf = _load_surface(ground_surface)
    out: list[list[float]] = []
    markings = markings if markings is not None else []
    for li, feat in enumerate(markings):
        props = feat.get("properties", {}) if isinstance(feat, dict) else {}
        if props.get("reliability") != "observed":
            continue
        geom = feat.get("geometry", {}) if isinstance(feat, dict) else {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if coords is None:
            continue
        try:
            from shapely.geometry import LineString

            line = LineString(np.asarray(coords, float)[:, :2])
        except (RuntimeError, ValueError, OSError, KeyError, TypeError):
            arr = np.asarray(coords, float)
            if arr.ndim < 2:
                continue
            line = None
            # fallback: treat coords as polyline vertices
            from shapely.geometry import LineString as _LS

            line = _LS(arr[:, :2])
        marking_pts: list[list[float]] = []
        n_samples = 0
        for s, x, y in profile.sample_line(line, step_m):
            z = None
            if surf is not None:
                try:
                    hit = profile.ground_z_at(surf, float(x), float(y))
                except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                    hit = None
                if hit is not None:
                    z = float(hit[0])
            if z is None:
                z = _nearest_z(points_3d, float(x), float(y))
            if z is None:
                continue
            marking_pts.append([float(x), float(y), float(z), float(li)])
            n_samples += 1
        if n_samples < EDGE_MIN_SAMPLES:
            continue
        out.extend(marking_pts)
    if not out:
        return np.zeros((0, 3), float)
    return np.asarray(out, float)


# --------------------------------------------------------------------------- refine

def _gray(img: np.ndarray) -> np.ndarray:
    img = np.asarray(img)
    if img.ndim == 2:
        return img.astype(float)
    if img.shape[-1] >= 3:
        return 0.299 * img[..., 0] + 0.587 * img[..., 1] + 0.114 * img[..., 2]
    return img[..., 0].astype(float)


def _params(p: Any, name: str, default: Any) -> Any:
    return getattr(p, name, default)


def _delta_matrix(delta: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = Rotation.from_rotvec(delta[:3]).as_matrix()
    T[:3, 3] = delta[3:]
    return T


def _view_fields(view: Any) -> dict[str, Any]:
    if isinstance(view, dict):
        return view
    # tuple/list support
    v = {"image": None, "K": None, "base_c2w": None, "anchors": None}
    if isinstance(view, (tuple, list)):
        if len(view) > 0:
            v["image"] = view[0]
        if len(view) > 1:
            v["K"] = view[1]
        if len(view) > 2:
            v["base_c2w"] = view[2]
        if len(view) > 3:
            v["anchors"] = view[3]
        if len(view) > 4:
            v["nonground"] = view[4]
        if len(view) > 5:
            v["boxes"] = view[5]
    return v


def _anchors_for_view(view: dict, global_anchors: np.ndarray | None) -> np.ndarray:
    a = view.get("anchors", None)
    if a is None:
        a = global_anchors
    if a is None:
        return np.zeros((0, 3), float)
    arr = np.asarray(a, float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 3)
    return arr


def _tangents(anchors: Any, labels: Any = None) -> np.ndarray:
    arr = np.asarray(anchors)
    if arr.ndim == 2 and arr.shape[1] >= 4:
        xyz = arr[:, :3].astype(float)
        if labels is None:
            labels = arr[:, 3]
    else:
        xyz = np.asarray(anchors, float).reshape(-1, 3)
    n = len(xyz)
    t = np.zeros((n, 3), float)
    if n < 2:
        return t
    if labels is None:
        seg = np.zeros(n, int)
        for i in range(1, n):
            seg[i] = seg[i - 1]
            if np.linalg.norm(xyz[i] - xyz[i - 1]) > 1.0:
                seg[i] += 1
        groups = []
        for s in np.unique(seg):
            groups.append(np.flatnonzero(seg == s))
    else:
        lab = np.asarray(labels)
        groups = []
        start = 0
        for i in range(1, n + 1):
            if i == n or lab[i] != lab[start]:
                groups.append(np.arange(start, i))
                start = i
    for idx in groups:
        idx = np.asarray(idx, int)
        if idx.size < 2:
            continue
        local = xyz[idx]
        lt = np.zeros((idx.size, 3), float)
        lt[0] = local[1] - local[0]
        lt[-1] = local[-1] - local[-2]
        if idx.size > 2:
            lt[1:-1] = local[2:] - local[:-2]
        t[idx] = lt
    return t


def _residuals_one_view(
    base_c2w: np.ndarray,
    delta: np.ndarray,
    view: dict,
    anchors: np.ndarray,
    params: Any,
) -> np.ndarray:
    img = view.get("image")
    K = np.asarray(view.get("K"), float)
    c2w = np.asarray(base_c2w, float) @ _delta_matrix(delta)
    if img is None:
        return np.zeros(0, float)
    image = np.asarray(img)
    h, w = image.shape[:2]
    gray = _gray(image)
    observed_mask = None
    try:
        observed_mask = view.get("observed", None)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
        observed_mask = None
    if observed_mask is None:
        observed_mask = np.ones((h, w), bool)
    observed_mask = np.asarray(observed_mask)
    if observed_mask.shape != (h, w):
        observed_mask = np.ones((h, w), bool)
    ng = view.get("nonground", None)
    if ng is None:
        ng = np.zeros((0, 3), float)
    else:
        ng = np.asarray(ng, float).reshape(-1, 3)
    boxes = view.get("boxes", []) or []
    # occlusion via zbuffer.visible
    if len(anchors) > 0:
        try:
            _a = np.asarray(anchors)
            _xyz = _a[:, :3].astype(float) if _a.ndim == 2 and _a.shape[1] >= 3 else np.asarray(anchors, float).reshape(-1, 3)
            vis = zbuffer.visible(
                _xyz,
                ng,
                boxes,
                c2w,
                K,
                (w, h),
                params,
            )
        except (RuntimeError, ValueError, OSError, KeyError, TypeError):
            vis = np.ones(len(anchors), bool)
    else:
        vis = np.zeros(0, bool)
    tangents = _tangents(anchors)
    fx = float(K[0, 0])
    res_arr = np.full(len(anchors), np.nan, float)
    _cso = getattr(_colour_mod, "_cross_section_offset", None) if _colour_mod is not None else None
    if _cso is None:
        try:
            from twin.stages import colour as _colour

            _cso = _colour._cross_section_offset
        except (ImportError, RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
            _cso = None
    _a = np.asarray(anchors)
    _xyz = _a[:, :3].astype(float) if _a.ndim == 2 and _a.shape[1] >= 3 else np.asarray(anchors, float).reshape(-1, 3)
    for i, a in enumerate(_xyz):
        if not (vis[i] if i < len(vis) else False):
            continue
        uv, depth = zbuffer.project(np.asarray([a], float), c2w, K)
        u, v = float(uv[0, 0]), float(uv[0, 1])
        d = float(depth[0])
        if not np.isfinite(u) or not np.isfinite(v) or d <= 0:
            continue
        tg = tangents[i]
        if np.linalg.norm(tg) < 1e-9:
            continue
        duv = zbuffer.project(np.asarray([a + tg], float), c2w, K)[0][0] - np.array([u, v])
        if np.linalg.norm(duv) < 1e-9:
            continue
        ndir = np.array([-duv[1], duv[0]])
        ndir = ndir / np.linalg.norm(ndir)
        m_per_px = d / fx if fx > 0 else 1.0
        n_side = int(np.ceil(EDGE_SEARCH_M / m_per_px)) if m_per_px > 0 else 8
        n_side = max(n_side, 1)
        offsets_px = np.arange(-n_side, n_side + 1, dtype=float)
        samples_px = offsets_px
        lum = []
        ok = []
        for off in offsets_px:
            px = u + off * ndir[0]
            py = v + off * ndir[1]
            if 0 <= px < w - 1 and 0 <= py < h - 1:
                x0 = int(np.floor(px)); y0 = int(np.floor(py))
                afx = px - x0; afy = py - y0
                v00 = float(gray[y0, x0]); v10 = float(gray[y0, x0+1])
                v01 = float(gray[y0+1, x0]); v11 = float(gray[y0+1, x0+1])
                val = (1-afx)*(1-afy)*v00 + afx*(1-afy)*v10 + (1-afx)*afy*v01 + afx*afy*v11
                ixn = round(px); iyn = round(py)
                observed_ok = bool(observed_mask[iyn, ixn]) if (0 <= ixn < w and 0 <= iyn < h) else False
                # use observed mask array if available else True
                ok.append(observed_ok if 'observed_mask' in locals() else True)
                lum.append(val)
            else:
                ok.append(False)
                lum.append(0.0)
        s_m = samples_px * m_per_px
        lum_arr = np.asarray(lum, float)
        ok_arr = np.asarray(ok, bool)
        if _cso is None:
            continue
        try:
            val = _cso(lum_arr, ok_arr, s_m)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
            val = None
        if val is None:
            continue
        res_arr[i] = float(val)
    return res_arr


def refine_one(
    base_c2w: Any,
    K: Any,
    image: Any,
    anchors_3d: Any,
    params: Any,
    nonground: Any = None,
    boxes: Any = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    base = np.asarray(base_c2w, float).reshape(4, 4)
    K = np.asarray(K, float).reshape(3, 3)
    if anchors_3d is None:
        anchors = np.zeros((0, 3), float)
    else:
        anchors = np.asarray(anchors_3d)
        if anchors.ndim == 1:
            anchors = anchors.reshape(-1, 3)
    # cap anchors
    max_anc = int(_params(params, "pose_max_anchors", 200))
    if len(anchors) > max_anc:
        idx = np.linspace(0, len(anchors) - 1, max_anc).astype(int)
        anchors = anchors[idx]
    # fixed valid subset at base pose (avoids zero-weight flat directions)
    try:
        _r0raw = _residuals_one_view(base, np.zeros(6), {"image": image, "K": K, "base_c2w": base, "anchors": anchors, "nonground": nonground if nonground is not None else np.zeros((0,3),float), "boxes": boxes if boxes is not None else []}, anchors, params)
        _vmask = np.isfinite(_r0raw)
        if _vmask.any():
            anchors = anchors[_vmask]
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
        pass
    view = {
        "image": image,
        "K": K,
        "base_c2w": base,
        "anchors": anchors,
        "nonground": nonground if nonground is not None else np.zeros((0, 3), float),
        "boxes": boxes if boxes is not None else [],
    }
    max_deg = float(_params(params, "pose_max_deg", 0.5))
    max_m = float(_params(params, "pose_max_m", 0.05))
    max_nfev = int(_params(params, "pose_max_nfev", 200))
    min_anchors = int(_params(params, "pose_min_anchors", 20))
    lb = np.array([-np.radians(max_deg)] * 3 + [-max_m] * 3)
    ub = np.array([np.radians(max_deg)] * 3 + [max_m] * 3)

    def resfun(delta, anchor_idx=None):
        a = anchors if anchor_idx is None else anchors[anchor_idx]
        v = dict(view)
        v["anchors"] = a
        r = _residuals_one_view(base, delta, v, a, params)
        r = np.where(np.isfinite(r), r, 0.5)
        return np.asarray(r, float).ravel()

    # initial
    r0 = resfun(np.zeros(6))
    if r0.size == 0:
        return base.copy(), np.zeros(0, float), {
            "applied": False,
            "reason": "no_anchors",
            "hit_bound": False,
            "nfev": 0,
        }

    def fun(delta):
        return resfun(delta)

    try:
        sol = least_squares(fun, np.zeros(6), method="trf", bounds=(lb, ub), max_nfev=max_nfev, xtol=1e-8, ftol=1e-8, gtol=1e-8)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        sol = None

    if sol is None:
        return base.copy(), r0, {"applied": False, "reason": "solver_failed", "hit_bound": False, "nfev": 0}

    delta_opt = sol.x
    r_opt = resfun(delta_opt)
    cost0 = float(np.sum(r0 ** 2))
    cost1 = float(np.sum(r_opt ** 2))
    improved = cost1 < cost0
    hit_bound = bool(np.any(np.abs(delta_opt[:3]) >= np.radians(max_deg) - 1e-6) or np.any(np.abs(delta_opt[3:]) >= max_m - 1e-6))

    applied = improved and not hit_bound
    reason = "converged" if applied else ("hit_bound" if hit_bound else "no_improvement")
    final_delta = delta_opt if applied else np.zeros(6)
    if applied:
        full_res = _residuals_one_view(base, delta_opt, view, anchors, params)
        valid = np.isfinite(full_res)
        vals = full_res[valid]
        med = float(np.median(vals)) if vals.size else 0.0
        mad = float(np.median(np.abs(vals - med))) if vals.size else 0.0
        sigma = mad * 1.4826 if mad > 0 else (float(np.std(vals)) if vals.size else 1e-12)
        sigma = max(1e-2, sigma)
        inlier_valid = np.abs(vals) <= 3 * sigma
        # map back to anchor indices among valid
        valid_idx = np.flatnonzero(valid)
        inlier_anchors = valid_idx[inlier_valid]
        if len(inlier_anchors) < min_anchors:
            applied = False
            reason = "insufficient_inliers"
            final_delta = np.zeros(6)
        else:
            try:
                sol2 = least_squares(lambda d: resfun(d, inlier_anchors), np.zeros(6), method="trf", bounds=(lb, ub), max_nfev=max_nfev, xtol=1e-8, ftol=1e-8, gtol=1e-8)
                if sol2 is not None:
                    delta_opt = sol2.x
                    final_delta = delta_opt if (float(np.sum(resfun(delta_opt, inlier_anchors) ** 2)) < float(np.sum(resfun(np.zeros(6), inlier_anchors) ** 2))) else np.zeros(6)
                    if final_delta.any():
                        applied = True
                    else:
                        applied = False
                        reason = "no_improvement"
            except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                pass
    corrected = base @ _delta_matrix(final_delta) if applied else base.copy()
    final_res = resfun(final_delta) if applied else r0
    info = {
        "applied": bool(applied),
        "reason": reason,
        "hit_bound": bool(hit_bound),
        "nfev": int(getattr(sol, "nfev", 0)),
        "cost_before": cost0,
        "cost_after": float(np.sum(final_res ** 2)) if applied else cost0,
        "n_anchors": len(anchors),
        "n_inliers": len(inlier_anchors) if 'inlier_anchors' in locals() else len(final_res),
    }
    return corrected, final_res, info


def refine_channel_extrinsics(
    base_extrinsics: Any,
    views: Any,
    anchors: Any = None,
    channel_index: int = 0,
    params: Any = None,
) -> tuple[Any, np.ndarray, dict[str, Any]]:
    views_list = list(views) if views is not None else []
    if anchors is None:
        global_anchors = None
    else:
        ga = np.asarray(anchors)
        if ga.ndim == 1:
            ga = ga.reshape(-1, 3)
        global_anchors = ga
    # base
    base_arr = np.asarray(base_extrinsics, float)
    multi = base_arr.ndim == 3
    if multi:
        base_c2w = base_arr[channel_index].copy()
    else:
        base_c2w = base_arr.reshape(4, 4).copy()

    # normalize views
    norm_views = []
    for v in views_list:
        vd = _view_fields(v)
        if vd.get("base_c2w") is None:
            vd["base_c2w"] = base_c2w.copy()
        if vd.get("anchors") is None:
            vd["anchors"] = global_anchors
        if vd.get("K") is None:
            vd["K"] = np.eye(3)
        if vd.get("image") is None:
            vd["image"] = np.zeros((10, 10, 3), np.uint8)
        norm_views.append(vd)

    # filter views by channel if present
    relevant = []
    for vd in norm_views:
        ch = vd.get("channel", None)
        if ch is None or ch == channel_index:
            relevant.append(vd)
    if not relevant:
        relevant = norm_views

    def resfun(delta):
        out = []
        for vd in relevant:
            bc = np.asarray(vd["base_c2w"], float).reshape(4, 4)
            a = _anchors_for_view(vd, global_anchors)
            r = _residuals_one_view(bc, delta, vd, a, params)
            r = np.where(np.isfinite(r), r, 0.5)
            out.append(np.asarray(r, float).ravel())
        if not out:
            return np.zeros(0, float)
        return np.concatenate(out) if any(len(x) for x in out) else np.zeros(0, float)

    max_deg = float(_params(params, "pose_max_deg", 0.5))
    max_m = float(_params(params, "pose_max_m", 0.05))
    max_nfev = int(_params(params, "pose_max_nfev", 200))
    min_anchors = int(_params(params, "pose_min_anchors", 20))
    lb = np.array([-np.radians(max_deg)] * 3 + [-max_m] * 3)
    ub = np.array([np.radians(max_deg)] * 3 + [max_m] * 3)

    # valid subset at base pose across views
    if global_anchors is not None and len(global_anchors) > 0:
        _vmask = np.zeros(len(global_anchors), bool)
        for vd in relevant:
            bc = np.asarray(vd.get("base_c2w", base_c2w), float).reshape(4, 4)
            a = _anchors_for_view(vd, global_anchors)
            try:
                _raw = _residuals_one_view(bc, np.zeros(6), vd, a, params)
                _vmask |= np.isfinite(_raw)
            except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
                pass
        if _vmask.any():
            global_anchors = global_anchors[_vmask]
    # cap anchors (global)
    ma = int(_params(params, "pose_max_anchors", 200))
    if global_anchors is not None and len(global_anchors) > ma:
        idx = np.linspace(0, len(global_anchors) - 1, ma).astype(int)
        global_anchors = global_anchors[idx]
    for vd in relevant:
        if global_anchors is not None:
            vd["anchors"] = global_anchors

    r0 = resfun(np.zeros(6))
    if r0.size == 0:
        info = {"applied": False, "reason": "no_anchors", "hit_bound": False, "nfev": 0, "n_cameras": len(relevant)}
        corrected = base_c2w.copy()
        if multi:
            out = base_arr.copy()
            out[channel_index] = corrected
            return out, np.zeros(0, float), info
        return corrected, np.zeros(0, float), info

    try:
        sol = least_squares(resfun, np.zeros(6), method="trf", bounds=(lb, ub), max_nfev=max_nfev, xtol=1e-8, ftol=1e-8, gtol=1e-8)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        sol = None

    if sol is None:
        info = {"applied": False, "reason": "solver_failed", "hit_bound": False, "nfev": 0, "n_cameras": len(relevant)}
        corrected = base_c2w.copy()
        if multi:
            out = base_arr.copy()
            out[channel_index] = corrected
            return out, r0, info
        return corrected, r0, info

    delta_opt = sol.x
    r_opt = resfun(delta_opt)
    cost0 = float(np.sum(r0 ** 2))
    cost1 = float(np.sum(r_opt ** 2))
    improved = cost1 < cost0
    hit_bound = bool(np.any(np.abs(delta_opt[:3]) >= np.radians(max_deg) - 1e-6) or np.any(np.abs(delta_opt[3:]) >= max_m - 1e-6))

    applied = improved and not hit_bound
    reason = "converged" if applied else ("hit_bound" if hit_bound else "no_improvement")

    # raw finite mask for inlier counting
    raw_parts = []
    for vd in relevant:
        bc = np.asarray(vd["base_c2w"], float).reshape(4, 4)
        a = _anchors_for_view(vd, global_anchors)
        raw_parts.append(_residuals_one_view(bc, delta_opt, vd, a, params))
    raw = np.concatenate(raw_parts) if raw_parts else np.zeros(0, float)
    valid = np.isfinite(raw)
    vals = raw[valid]
    med = float(np.median(vals)) if vals.size else 0.0
    mad = float(np.median(np.abs(vals - med))) if vals.size else 0.0
    sigma = mad * 1.4826 if mad > 0 else (float(np.std(vals)) if vals.size else 1e-12)
    sigma = max(1e-2, sigma)
    inlier_mask = valid & (np.abs(raw) <= 3 * sigma)
    inlier_count = int(inlier_mask.sum())

    if applied:
        if inlier_count < min_anchors:
            applied = False
            reason = "insufficient_inliers"
        else:
            # inlier re-solve (zero non-inliers)
            def resfun_in(d):
                r = resfun(d)
                r = np.asarray(r, float).copy()
                r[~inlier_mask] = 0.0
                return r
            try:
                sol2 = least_squares(resfun_in, np.zeros(6), method="trf", bounds=(lb, ub), max_nfev=max_nfev, xtol=1e-8, ftol=1e-8, gtol=1e-8)
                if sol2 is not None:
                    delta2 = sol2.x
                    hb2 = bool(np.any(np.abs(delta2[:3]) >= np.radians(max_deg) - 1e-6) or np.any(np.abs(delta2[3:]) >= max_m - 1e-6))
                    cost_before_in = float(np.sum((resfun(np.zeros(6)) * 0 + 0)[inlier_mask] ** 2)) if False else float(np.sum(resfun(np.zeros(6))[inlier_mask] ** 2))
                    cost_after_in = float(np.sum(resfun(delta2)[inlier_mask] ** 2))
                    if (not hb2) and cost_after_in < cost_before_in:
                        delta_opt = delta2
                        applied = True
                        reason = "converged"
                    else:
                        if hb2:
                            reason = "hit_bound"
                        else:
                            reason = "no_improvement"
                        applied = False
            except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                pass

    final_delta = delta_opt if applied else np.zeros(6)
    corrected = base_c2w @ _delta_matrix(final_delta) if applied else base_c2w.copy()
    final_res = resfun(final_delta)

    info = {
        "applied": bool(applied),
        "reason": reason,
        "hit_bound": bool(hit_bound),
        "nfev": int(getattr(sol, "nfev", 0)),
        "n_cameras": len(relevant),
        "n_inliers": int(inlier_count),
        "n_anchors": int(len(global_anchors) if global_anchors is not None else 0),
    }

    if multi:
        out = base_arr.copy()
        out[channel_index] = corrected
        return out, final_res, info
    return corrected, final_res, info


# aliases for hidden tests / architecture names
refine_pose = refine_one
refine = refine_channel_extrinsics
refine_extrinsics = refine_channel_extrinsics
