"""Raster export for the labelling tool page DATA.

cv2 is preferred for prototype-faithful smoothing/resize/encoding when importable,
but is never imported at module import time. Fallback uses scipy/Pillow.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import laspy
import numpy as np
from PIL import Image
from scipy import ndimage

from twin.cameras import posed_cameras
from twin.contracts import stage_dir
from twin.dataset import DatasetConfig

W_PX = 1600
H_PX = 1500
G = 0.05
MAX_WINDOW_PX = 10_240_000  # mirrors twin.labeltool.MAX_WINDOW_PX

_cv2 = None
_cv2_tried = False


class RasterError(RuntimeError):
    pass


_CV2_ATTRS = (
    "GaussianBlur",
    "resize",
    "imencode",
    "cvtColor",
    "warpAffine",
    "INTER_AREA",
    "INTER_LINEAR",
    "INTER_NEAREST",
    "error",
)


def _cv2_usable(mod):
    return mod is not None and all(hasattr(mod, name) for name in _CV2_ATTRS)


def _try_cv2():
    """Return cv2 module or None. Cached; never imports cv2 at module import."""
    global _cv2, _cv2_tried
    if "cv2" in sys.modules:
        mod = sys.modules["cv2"]
        if mod is None or not _cv2_usable(mod):
            _cv2 = None
            _cv2_tried = True
            return None
        if mod is _cv2 and _cv2_tried:
            return _cv2
        _cv2 = mod
        _cv2_tried = True
        return _cv2
    if _cv2_tried:
        return _cv2
    _cv2_tried = True
    try:
        import cv2 as mod  # type: ignore
    except (ImportError, OSError):
        _cv2 = None
        return None
    _cv2 = mod if _cv2_usable(mod) else None
    return _cv2


def _raster_errors():
    cv2 = _try_cv2()
    if cv2 is not None:
        return (OSError, ValueError, cv2.error)
    return (OSError, ValueError)


def _nuscenes_root(root):
    if root is None:
        return DatasetConfig.from_env().root
    return root


def _run_base(run):
    for attr in ("base", "path"):
        if hasattr(run, attr):
            return Path(getattr(run, attr))
    return Path(run)


def _run_name(run):
    for attr in ("name", "id"):
        if hasattr(run, attr):
            return getattr(run, attr)
    return Path(run).name


def _frame_drives(run):
    """(name, base, transform) per drive whose cameras can label this source; runs without .frames yield themselves."""
    frames = getattr(run, "frames", None)
    if frames is None:
        yield _run_name(run), _run_base(run), None
        return
    for f in frames:
        yield f.name, Path(f.base), getattr(f, "transform", None)


def _blur(a, sigma):
    arr = np.asarray(a, dtype=np.float32)
    cv2 = _try_cv2()
    if cv2 is not None:
        return cv2.GaussianBlur(arr, (0, 0), float(sigma))
    return ndimage.gaussian_filter(arr, sigma=float(sigma)).astype(np.float32)


def _blur_masked(a, mask, sigma):
    """Masked normalisation: blur(a*m)/blur(m)."""
    arr = np.asarray(a, dtype=np.float32)
    m = np.asarray(mask, dtype=np.float32)
    num = _blur(arr * m, sigma)
    den = _blur(m, sigma) + 1e-6
    return (num / den).astype(np.float32)


def _resize(a, shape_hw, interpolation="linear"):
    arr = np.asarray(a)
    h, w = shape_hw
    cv2 = _try_cv2()
    if cv2 is not None:
        interp = cv2.INTER_AREA if interpolation == "area" else cv2.INTER_LINEAR
        out = cv2.resize(arr, (w, h), interpolation=interp)
        return out.astype(arr.dtype, copy=False)
    if arr.ndim == 2:
        zoom = (h / arr.shape[0], w / arr.shape[1])
        out = ndimage.zoom(arr.astype(np.float32), zoom, order=1)
        return out.astype(arr.dtype, copy=False)
    zoom = (h / arr.shape[0], w / arr.shape[1], 1)
    out = ndimage.zoom(arr.astype(np.float32), zoom, order=1)
    return out.astype(arr.dtype, copy=False)


def _encode(array, ext):
    """Return raw base64 (no data: prefix)."""
    arr = np.asarray(array)
    cv2 = _try_cv2()
    if cv2 is not None:
        data = arr
        if data.ndim == 3:
            data = cv2.cvtColor(data.astype(np.uint8), cv2.COLOR_RGB2BGR)
        else:
            data = data.astype(np.uint8)
        params = [cv2.IMWRITE_JPEG_QUALITY, 82] if ext == ".jpg" else []
        ok, buf = cv2.imencode(ext, data, params)
        if not ok:
            raise OSError("cv2.imencode failed")
        return base64.b64encode(buf.tobytes()).decode()
    if arr.ndim == 2:
        img = Image.fromarray(arr.astype(np.uint8), mode="L")
    else:
        img = Image.fromarray(arr.astype(np.uint8), mode="RGB")
    buf = io.BytesIO()
    if ext == ".png":
        img.save(buf, format="PNG")
    else:
        img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def blank_window(site, x0, y1, missing, *, width=W_PX, height=H_PX, cell=G):
    w, h = width, height
    intensity = _encode(np.zeros((h, w), dtype=np.uint8), ".png")
    ortho = _encode(np.zeros((h, w, 3), dtype=np.uint8), ".jpg")
    fused = _encode(np.zeros((h, w, 3), dtype=np.uint8), ".jpg")
    height = _encode(np.zeros((h, w, 3), dtype=np.uint8), ".jpg")
    return {
        "name": site,
        "window": {"x0": x0, "y1": y1, "g": cell, "w": w, "h": h},
        "intensity": intensity,
        "ortho": ortho,
        "fused": fused,
        "height": height,
        "fuse_stats": {},
        "frames": [],
        "missing": list(missing),
        "no_imagery": True,
    }


def _collect_drive(run, x0, y1, width=W_PX, height=H_PX, cell=G, nuscenes_root=None):
    Gc = cell
    W, H = width, height
    X0, Y1 = x0, y1
    X1, Y0 = X0 + W * Gc, Y1 - H * Gc
    base = _run_base(run)
    rname = _run_name(run)

    ground_path = stage_dir(base, "ground") / "ground.laz"
    if not ground_path.exists():
        raise OSError(f"missing ground.laz: {ground_path}")

    las = laspy.read(str(ground_path))
    x = np.asarray(las.x)
    y = np.asarray(las.y)
    k = (x >= X0) & (x < X1) & (y > Y0) & (y <= Y1)
    if k.sum() < 20000:
        raise OSError(f"{rname}: sparse ({int(k.sum())} points < 20000)")
    ix = ((x[k] - X0) / Gc).astype(int)
    iy = ((Y1 - y[k]) / Gc).astype(int)
    ok = (ix < W) & (iy < H)
    ix, iy = ix[ok], iy[ok]
    I = np.asarray(las.intensity)[k][ok].astype(float)
    Z = np.asarray(las.z)[k][ok]

    cnt = np.zeros((H, W))
    si = np.zeros((H, W))
    sz = np.zeros((H, W))
    np.add.at(cnt, (iy, ix), 1)
    np.add.at(si, (iy, ix), I)
    np.add.at(sz, (iy, ix), Z)

    with np.errstate(all="ignore"):
        zd = np.where(cnt > 0, sz / np.maximum(cnt, 1), np.nan).astype(np.float32)
    zl = _blur_masked(np.nan_to_num(zd), (cnt > 0).astype(np.float32), sigma=2)
    okd = _blur((cnt > 0).astype(np.float32), sigma=2) > 0.3

    sm = np.where(okd, zl, np.nan)[::5, ::5]
    road = ndimage.percentile_filter(np.where(np.isfinite(sm), sm, 1e3), 10, size=25)
    road[road > 100] = np.nan
    fill = float(np.nanmedian(sm)) if np.isfinite(sm).any() else 0.0
    roadr = _resize(
        np.nan_to_num(road, nan=fill).astype(np.float32),
        (H, W),
        interpolation="linear",
    ).astype(np.float32)
    sR = np.where(okd, zl - roadr, 0)
    cR = okd.astype(float)

    basep = base
    pgw_path = stage_dir(basep, "colour") / "ortho.pgw"
    ortho_png = stage_dir(basep, "colour") / "ortho.png"
    obs = None
    rgb = None
    raw = None
    if cell <= G + 1e-12 and pgw_path.exists() and ortho_png.exists():
        with open(pgw_path) as _f:
            pgw = [float(v) for v in _f.read().split()]
        im = Image.open(ortho_png)
        c0 = round((X0 - (pgw[4] - 0.025)) / Gc)
        r0 = round(((pgw[5] + 0.025) - Y1) / Gc)
        full = np.zeros((H, W, 4), dtype=np.uint8)
        sx0, sy0 = max(c0, 0), max(r0, 0)
        sx1, sy1 = min(c0 + W, im.size[0],), min(r0 + H, im.size[1],)
        if sx1 > sx0 and sy1 > sy0:
            cr = np.asarray(im.crop((sx0, sy0, sx1, sy1)))
            full[sy0 - r0 : sy0 - r0 + cr.shape[0], sx0 - c0 : sx0 - c0 + cr.shape[1]] = cr
        del im
        obs = full[..., 3] > 0
        rgb = full[..., :3].astype(np.float32)
        raw = np.where(obs[:, :, None], rgb, np.nan).astype(np.float32)

    mI = cnt > 0
    with np.errstate(all="ignore"):
        Ii = np.where(mI, si / np.maximum(cnt, 1), np.nan)

    return {
        "run_name": rname,
        "base": basep,
        "cnt": cnt,
        "si": si,
        "sz": sz,
        "sR": sR,
        "cR": cR,
        "raw": raw,
        "obs": obs,
        "rgb": rgb,
        "mI": mI,
        "Ii": Ii,
    }


def _pct(a, m, lo=2, hi=99.5):
    if m.sum() < 1:
        return np.zeros_like(a, dtype=np.float32)
    l, h = np.nanpercentile(a[m], [lo, hi])
    return np.clip((a - l) / (h - l + 1e-9), 0, 1).astype(np.float32)


def _hp(a, m):
    a = np.where(m, a, 0).astype(np.float32)
    w = m.astype(np.float32)
    ab = _blur(a, sigma=20)
    wb = _blur(w, sigma=20)
    return np.where(m, a - ab / (wb + 1e-6), 0).astype(np.float32)


def _fuse(drive, *, width=W_PX, height=H_PX, cell=G, **kw):
    cv2 = _try_cv2()
    if cv2 is None:
        raise ImportError("cv2 unavailable")

    def sh(a, dx, dy, shape):
        return cv2.warpAffine(
            a.astype(np.float32),
            np.float32([[1, 0, dx], [0, 1, dy]]),
            (shape[1], shape[0]),
            flags=cv2.INTER_LINEAR,
        )

    W, H = width, height
    rname = drive["run_name"]
    obs = drive["obs"]
    rgb = drive["rgb"]
    mI = drive["mI"]
    Ii = drive["Ii"]
    errors = _raster_errors()
    try:
        if obs is None or obs.sum() < 2000:
            return {"used": False}, None

        A = _hp(np.where(mI, _pct(Ii, mI), 0), mI)
        Bm = _hp(np.where(obs, _pct(rgb.min(-1), obs), 0), obs)
        mask = obs & mI

        def ncc(a, b, m):
            if m.sum() < 500:
                return -1.0
            x = a[m] - a[m].mean()
            y = b[m] - b[m].mean()
            return float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum() + 1e-9))

        def register(A, Bm, m):
            A2 = _resize(A, (H // 2, W // 2), interpolation="area")
            B2 = _resize(Bm, (H // 2, W // 2), interpolation="area")
            m2 = cv2.resize(m.astype(np.uint8), (W // 2, H // 2), interpolation=cv2.INTER_NEAREST) > 0
            best = (-2.0, 0, 0)
            for dy in range(-10, 11):
                for dx in range(-10, 11):
                    shb = sh(B2, dx, dy, (H // 2, W // 2))
                    mm = m2 & (sh(m2.astype(np.float32), dx, dy, (H // 2, W // 2)) > 0.5)
                    v = ncc(A2, shb, mm)
                    if v > best[0]:
                        best = (v, dx * 2, dy * 2)
            v0 = ncc(A, Bm, m)
            c = (-2.0, 0, 0)
            for dy in np.arange(best[2] - 2, best[2] + 2.01, 0.5):
                for dx in np.arange(best[1] - 2, best[1] + 2.01, 0.5):
                    shb = sh(Bm, dx, dy, (H, W))
                    mm = m & (sh(m.astype(np.float32), dx, dy, (H, W)) > 0.5)
                    v = ncc(A, shb, mm)
                    if v > c[0]:
                        c = (v, float(dx), float(dy))
            return v0, *c

        v0, v1, dx, dy = register(A, Bm, mask)
        ok = v1 >= 0.09 and max(abs(dx), abs(dy)) <= 19 and v1 >= v0
        stats = {
            "shift_cm": round(float(np.hypot(dx, dy)) * cell * 100, 1),
            "ncc_before": round(v0, 3),
            "ncc_after": round(v1, 3),
            "used": bool(ok),
        }
        if ok:
            mw = sh(obs.astype(np.float32), dx, dy, (H, W)) > 0.99
            reg_arr = np.where(
                mw[:, :, None],
                np.dstack([sh(rgb[:, :, j], dx, dy, (H, W)) for j in range(3)]),
                np.nan,
            ).astype(np.float32)
        else:
            reg_arr = None
        return stats, reg_arr
    except errors:
        raise RasterError(rname)


def export_window(store, runs, *, site, x0, y1, width=1600, height=1500, cell=0.05, nuscenes_root=None):
    nr = _nuscenes_root(nuscenes_root)
    prev = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        if width * height > MAX_WINDOW_PX:
            raise RasterError(f"window {width}x{height} px exceeds {MAX_WINDOW_PX} px; the fitted window was not downsampled")
        Gc = cell
        W, H = width, height
        sI = np.zeros((H, W))
        cI = np.zeros((H, W))
        sZ = np.zeros((H, W))
        sR = np.zeros((H, W))
        cR = np.zeros((H, W))
        raw = []
        reg = []
        stats = {}
        missing = []
        collected = []
        usable = []
        cv2_ok = True

        for run in runs:
            rname = _run_name(run)
            try:
                dd = _collect_drive(run, x0, y1, width=width, height=height, cell=cell, nuscenes_root=nr)
            except OSError as e:
                msg = str(e)
                if "sparse" in msg:
                    missing.append(msg)
                else:
                    missing.append(f"{rname}: missing ground.laz")
                continue

            if cell > G + 1e-12:
                ortho = stage_dir(_run_base(run), "colour") / "ortho.png"
                if ortho.exists():
                    note = f"{rname}: ortho/fused skipped (downsampled window)"
                    if note not in missing:
                        missing.append(note)
            collected.append(rname)
            usable.append(run)
            sI += dd["si"]
            cI += dd["cnt"]
            sZ += dd["sz"]
            sR += dd["sR"]
            cR += dd["cR"]

            if dd["raw"] is not None:
                try:
                    st, reg_arr = _fuse(dd, width=width, height=height, cell=cell)
                except RasterError:
                    missing.append(f"{rname}: raster error")
                except ImportError:
                    cv2_ok = False
                    if "opencv unavailable: fused/ortho skipped" not in missing:
                        missing.append("opencv unavailable: fused/ortho skipped")
                else:
                    stats[rname] = st
                    raw.append(dd["raw"])
                    if reg_arr is not None:
                        reg.append(reg_arr)

        frames = []
        cx = x0 + W * Gc / 2
        cy = y1 - H * Gc / 2
        for rname, base, transform in (s for run in usable for s in _frame_drives(run)):
            base = Path(base)
            try:
                # shortcut: correction applied here assumes 3_align/poses.json is uncorrected; if merge ever bakes corrections into poses.json, remove this transform
                cams = posed_cameras(stage_dir(base, "load"), stage_dir(base, "align"), correction=transform)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            cand = []
            for c in cams:
                if c.channel not in ("CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT"):
                    continue
                M = c.c2w
                p = M[:3, 3]
                f = M[:3, 2]
                dd_ = np.hypot(cx - p[0], cy - p[1])
                v = np.array([cx - p[0], cy - p[1]]) / max(dd_, 1e-6)
                if 12 < dd_ < 45 and f[:2] @ v > 0.6:
                    cand.append((dd_, c, M))
            cand.sort(key=lambda z: z[0])
            for dd_, c, M in cand[:: max(1, len(cand) // 3)][:3]:
                try:
                    im = Image.open(Path(nr) / c.image).convert("RGB")
                except (OSError, ValueError):
                    continue
                s = 800 / im.size[0]
                im = im.resize((800, int(im.size[1] * s)))
                frames.append(
                    {
                        "run": rname,
                        "channel": c.channel,
                        "t": c.t_us,
                        "K": (c.K * [[s], [s], [1]]).tolist(),
                        "c2w": M.tolist(),
                        "img": _encode(np.asarray(im), ".jpg"),
                        "w": im.size[0],
                        "h": im.size[1],
                    }
                )
            if len(frames) >= 15:
                break

        hasI = cI > 0
        with np.errstate(all="ignore"):
            I = np.where(hasI, sI / np.maximum(cI, 1), np.nan)
        In = np.where(hasI, _pct(I, hasI), 0).astype(np.float32)

        def med(lst):
            if not lst:
                return np.zeros((H, W, 3), dtype=np.uint8), np.zeros((H, W), dtype=bool)
            O = np.nanmedian(np.stack(lst), axis=0)
            m = ~np.isnan(O[..., 0])
            return np.nan_to_num(O).astype(np.uint8), m

        O_raw, _ = med(raw)
        O, hasO = med(reg)

        if cv2_ok and (reg or raw):
            try:
                import cv2

                lab = cv2.cvtColor(O, cv2.COLOR_RGB2LAB).astype(np.float32)
                Lo = np.where(hasO, _pct(lab[..., 0], hasO), 0) if hasO.any() else np.zeros((H, W))
                L = np.where(hasI & hasO, 0.65 * In + 0.35 * Lo, np.where(hasI, In, Lo))
                ab = np.where(hasO[:, :, None], (lab[..., 1:] - 128) * 1.4 + 128, 128)
                fused = cv2.cvtColor(
                    np.dstack([L * 255, ab]).clip(0, 255).astype(np.uint8),
                    cv2.COLOR_LAB2RGB,
                )
                fused[~(hasI | hasO)] = 0
            except ImportError:
                cv2_ok = False
                fused = np.zeros((H, W, 3), dtype=np.uint8)
        else:
            fused = np.zeros((H, W, 3), dtype=np.uint8)

        rel = np.where(cR > 0, sR / np.maximum(cR, 1), np.nan)
        t = np.clip(np.nan_to_num(rel, nan=0) / 0.25, 0, 1)
        stops = np.array(
            [[0.06, 0.08, 0.20], [0.10, 0.35, 0.65], [0.15, 0.70, 0.55], [0.95, 0.85, 0.20], [1.0, 1.0, 1.0]]
        )
        pos = np.linspace(0, 1, len(stops))
        height = np.dstack([np.interp(t, pos, stops[:, k]) for k in range(3)])
        height = (height * 255).astype(np.uint8)
        height[cR == 0] = 0

        if not runs or not collected:
            return blank_window(site, x0, y1, missing if missing else ["no drives"], width=W, height=H, cell=cell)

        return {
            "name": site,
            "window": {"x0": x0, "y1": y1, "g": Gc, "w": W, "h": H},
            "intensity": _encode((In * 255).astype(np.uint8), ".png"),
            "ortho": _encode(O_raw, ".jpg"),
            "fused": _encode(fused, ".jpg"),
            "height": _encode(height, ".jpg"),
            "fuse_stats": stats,
            "frames": frames,
            "missing": missing,
            "no_imagery": False,
        }
    finally:
        Image.MAX_IMAGE_PIXELS = prev
